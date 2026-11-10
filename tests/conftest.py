from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from tests.fakes import FakeAtlassian, FakeLLM, FakeSTT

API_KEY = "test-admin-key-123456"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
        database_url=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db",
        admin_api_key=SecretStr(API_KEY),
        credential_encryption_key=SecretStr(Fernet.generate_key().decode()),
        jwt_secret=SecretStr("test-jwt-secret-with-enough-entropy-1234567890"),
        atlassian_max_retries=2,
        atlassian_backoff_base_seconds=0.0,
        verification_retry_delay_seconds=0.0,
    )


@pytest.fixture
def fake_atlassian() -> FakeAtlassian:
    return FakeAtlassian()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_stt() -> FakeSTT:
    return FakeSTT()


@pytest.fixture
async def app(
    settings: Settings, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM, fake_stt: FakeSTT
) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings, atlassian_transport=fake_atlassian.transport, llm=fake_llm, stt=fake_stt, tts=None
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {API_KEY}"},
    ) as http:
        yield http


async def wait_for_run(app: FastAPI, run_id: str) -> None:
    await app.state.engine.tasks.wait(run_id)


async def tested_connection(client: httpx.AsyncClient, **overrides: Any) -> str:
    payload = {
        "name": "acme",
        "site_url": "https://acme.atlassian.net",
        "email": "ada@acme.com",
        "api_token": "tok-123",
        **overrides,
    }
    created = await client.post("/api/v1/connections", json=payload)
    assert created.status_code == 201, created.text
    connection_id: str = created.json()["id"]
    tested = await client.post(f"/api/v1/connections/{connection_id}/test")
    assert tested.status_code == 200, tested.text
    return connection_id
