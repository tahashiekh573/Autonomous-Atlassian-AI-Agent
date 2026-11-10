"""Application entry point: `uvicorn app.main:app --reload`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.atlassian.credentials import HttpPolicy
from app.clients.atlassian.factory import AtlassianClientFactory
from app.clients.llm.base import LLMClient
from app.clients.llm.factory import build_llm_client
from app.clients.speech.base import SpeechToText, TextToSpeech
from app.clients.speech.factory import build_stt, build_tts
from app.core.config import Settings, load_settings
from app.core.logging import setup_logging
from app.core.security import CredentialCipher, TokenService
from app.db.session import Database
from app.middlewares.error_handlers import register_exception_handlers
from app.middlewares.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.run_repository import RunRepository
from app.repositories.user_repository import UserRepository
from app.routers import audit, auth, connections, health, runs, voice
from app.services.agent_factory import AgentSetBuilder, build_agent_set
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.login_throttle import LoginThrottle
from app.services.run_engine import RunEngine
from app.services.task_manager import TaskManager
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)

_UNSET = object()


def create_app(
    settings: Settings | None = None,
    *,
    atlassian_transport: httpx.AsyncBaseTransport | None = None,
    llm: LLMClient | object | None = _UNSET,
    stt: SpeechToText | object | None = _UNSET,
    tts: TextToSpeech | object | None = _UNSET,
    agent_builder: AgentSetBuilder = build_agent_set,
) -> FastAPI:
    """Build the app. Keyword overrides exist for tests (fake LLM/speech/Atlassian transport)."""
    settings = settings or load_settings()
    setup_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_url)
        if settings.db_auto_create:
            await database.create_all()
        app.state.database = database
        llm_client = build_llm_client(settings) if llm is _UNSET else llm
        app.state.voice = VoiceService(
            build_stt(settings, llm_client) if stt is _UNSET else stt,  # type: ignore[arg-type]
            build_tts(settings) if tts is _UNSET else tts,  # type: ignore[arg-type]
            settings.max_audio_bytes,
        )
        tasks = TaskManager()
        app.state.engine = RunEngine(
            database,
            app.state.cipher,
            app.state.client_factory,
            llm_client,  # type: ignore[arg-type]
            settings,
            tasks,
            agent_builder,
        )
        async with database.session() as session:
            interrupted = await RunRepository(session).mark_interrupted(
                ["planning", "executing"], "Interrupted by a server restart; resubmit the command."
            )
            if interrupted:
                logger.warning("Marked %d interrupted run(s) as failed.", interrupted)
            await AuthService(
                UserRepository(session),
                app.state.tokens,
                AuditService(AuditLogRepository(session), actor="system"),
            ).bootstrap_admin(
                settings.bootstrap_admin_email,
                settings.bootstrap_admin_password.get_secret_value()
                if settings.bootstrap_admin_password
                else None,
            )
        if settings.open_dev_mode:
            logger.warning(
                "ADMIN_API_KEY is not set: requests without a token act as a local admin "
                "(development only)."
            )
        if llm_client is None:
            logger.warning(
                "No LLM configured: commands cannot be planned until GEMINI_API_KEY is set."
            )
        logger.info("%s started (%s)", settings.app_name, settings.environment)
        yield
        await tasks.shutdown()
        if isinstance(llm_client, LLMClient):
            await llm_client.aclose()
        await database.dispose()

    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.cipher = CredentialCipher(settings.credential_encryption_key)
    app.state.tokens = TokenService(settings.jwt_secret, settings.jwt_ttl_minutes)
    app.state.login_throttle = LoginThrottle()
    app.state.client_factory = AtlassianClientFactory(
        HttpPolicy(
            timeout_seconds=settings.atlassian_timeout_seconds,
            max_retries=settings.atlassian_max_retries,
            backoff_base_seconds=settings.atlassian_backoff_base_seconds,
            backoff_max_seconds=settings.atlassian_backoff_max_seconds,
        ),
        transport=atlassian_transport,
    )

    # Order matters: the last middleware added is the outermost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    for module in (auth, connections, runs, voice, audit):
        app.include_router(module.router, prefix=settings.api_prefix)
    return app


app = create_app()
