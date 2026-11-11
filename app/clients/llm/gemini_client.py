"""Google Gemini (Generative Language REST API) client.

Docs: https://ai.google.dev/api/generate-content
"""

import base64
import logging
from typing import Any

import httpx
from pydantic import SecretStr

from app.clients.llm.base import LLMClient
from app.clients.llm.http import post_with_retry
from app.clients.llm.rate_limiter import RateLimiter
from app.core.exceptions import LLMError, LLMQuotaExhaustedError

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
        temperature: float,
        requests_per_minute: int = 0,
        fallback_models: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._models = [model, *[m for m in (fallback_models or []) if m != model]]
        self._exhausted: set[str] = set()
        self._temperature = temperature
        self._limiter = RateLimiter(requests_per_minute)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"x-goog-api-key": api_key.get_secret_value()},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _generate(self, payload: dict[str, Any]) -> str:
        """Try the primary model, then fallbacks whose daily quota is not yet exhausted."""
        last_error: LLMQuotaExhaustedError | None = None
        for model in self._models:
            if model in self._exhausted:
                continue
            try:
                text = await self._generate_with(model, payload)
            except LLMQuotaExhaustedError as exc:
                self._exhausted.add(model)
                logger.warning("gemini model %s: daily quota exhausted, trying next model", model)
                last_error = exc
                continue
            self.model = model
            return text
        raise last_error or LLMQuotaExhaustedError(
            "gemini: every configured model has exhausted its daily quota "
            f"({', '.join(self._models)}). Wait for the daily reset or enable billing."
        )

    async def _generate_with(self, model: str, payload: dict[str, Any]) -> str:
        response = await post_with_retry(
            self._client,
            f"/models/{model}:generateContent",
            error_cls=LLMError,
            provider=self.provider,
            limiter=self._limiter,
            json=payload,
        )
        body = response.json()
        candidates = body.get("candidates") or []
        if not candidates:
            reason = (body.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"gemini returned no output ({reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts)
        if not text.strip():
            raise LLMError(
                f"gemini returned empty output ({candidates[0].get('finishReason', 'unknown')})"
            )
        return text

    async def generate(self, *, system: str, prompt: str, json_mode: bool = False) -> str:
        # Large plans (60 steps with form questions and page briefs) need long JSON output.
        config: dict[str, Any] = {"temperature": self._temperature, "maxOutputTokens": 32768}
        if json_mode:
            config["responseMimeType"] = "application/json"
        return await self._generate(
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": config,
            }
        )

    async def generate_from_audio(self, *, prompt: str, audio: bytes, mime_type: str) -> str:
        return await self._generate(
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(audio).decode(),
                                }
                            },
                        ],
                    }
                ],
                "generationConfig": {"temperature": 0.0},
            }
        )
