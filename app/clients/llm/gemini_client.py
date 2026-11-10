"""Google Gemini (Generative Language REST API) client.

Docs: https://ai.google.dev/api/generate-content
"""

import base64
from typing import Any

import httpx
from pydantic import SecretStr

from app.clients.llm.base import LLMClient
from app.clients.llm.http import post_with_retry
from app.core.exceptions import LLMError


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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"x-goog-api-key": api_key.get_secret_value()},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _generate(self, payload: dict[str, Any]) -> str:
        response = await post_with_retry(
            self._client,
            f"/models/{self.model}:generateContent",
            error_cls=LLMError,
            provider=self.provider,
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
        config: dict[str, Any] = {"temperature": self._temperature}
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
