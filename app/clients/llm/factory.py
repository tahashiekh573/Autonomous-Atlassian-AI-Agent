"""Build the configured LLM client (or None when no credentials are configured)."""

from app.clients.llm.base import LLMClient
from app.clients.llm.gemini_client import GeminiClient
from app.clients.llm.openai_client import OpenAIClient
from app.core.config import Settings


def build_llm_client(settings: Settings) -> LLMClient | None:
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        return GeminiClient(
            settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            requests_per_minute=settings.llm_requests_per_minute,
            fallback_models=settings.gemini_fallback_models,
        )
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAIClient(
            settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            requests_per_minute=settings.llm_requests_per_minute,
        )
    return None
