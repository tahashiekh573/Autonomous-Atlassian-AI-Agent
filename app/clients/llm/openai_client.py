"""OpenAI-compatible Chat Completions client (OpenAI, Azure OpenAI proxies, local gateways)."""

from typing import Any

import httpx
from pydantic import SecretStr

from app.clients.llm.base import LLMClient
from app.clients.llm.http import post_with_retry
from app.clients.llm.rate_limiter import RateLimiter
from app.core.exceptions import LLMError


def _is_reasoning_model(model: str) -> bool:
    name = model.casefold()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
        temperature: float,
        requests_per_minute: int = 0,
        reasoning_effort: str = "low",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._limiter = RateLimiter(requests_per_minute)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, *, system: str, prompt: str, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if _is_reasoning_model(self.model):
            # GPT-5 / o-series reject a custom temperature; depth is set by reasoning_effort.
            payload["reasoning_effort"] = self._reasoning_effort
            payload["max_completion_tokens"] = 32768
        else:
            payload["temperature"] = self._temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = await post_with_retry(
            self._client,
            "/chat/completions",
            error_cls=LLMError,
            provider=self.provider,
            limiter=self._limiter,
            json=payload,
        )
        choices = response.json().get("choices") or []
        content = (choices[0].get("message") or {}).get("content") if choices else None
        if not content:
            raise LLMError("openai returned empty output")
        return str(content)
