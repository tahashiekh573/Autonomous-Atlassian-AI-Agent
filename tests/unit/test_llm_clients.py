import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.llm.gemini_client import GeminiClient
from app.clients.llm.openai_client import OpenAIClient
from app.core.exceptions import LLMError


def _gemini(handler: httpx.MockTransport) -> GeminiClient:
    return GeminiClient(
        SecretStr("g-key"),
        model="gemini-test",
        base_url="https://gl.test/v1beta",
        timeout_seconds=5,
        temperature=0.1,
        transport=handler,
    )


async def test_gemini_sends_system_instruction_and_json_mode() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]}
        )

    client = _gemini(httpx.MockTransport(handler))
    assert await client.generate(system="SYS", prompt="hi", json_mode=True) == '{"a": 1}'
    sent = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1beta/models/gemini-test:generateContent"
    assert seen[0].headers["x-goog-api-key"] == "g-key"
    assert sent["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert sent["generationConfig"]["responseMimeType"] == "application/json"


async def test_gemini_blocked_prompt_raises() -> None:
    client = _gemini(
        httpx.MockTransport(
            lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        )
    )
    with pytest.raises(LLMError, match="SAFETY"):
        await client.generate(system="s", prompt="p")


async def test_gemini_http_error_does_not_leak_key() -> None:
    client = _gemini(httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "bad"})))
    with pytest.raises(LLMError) as info:
        await client.generate(system="s", prompt="p")
    assert "g-key" not in str(info.value) and "g-key" not in str(info.value.details)


async def test_openai_compatible_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer o-key"
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = OpenAIClient(
        SecretStr("o-key"),
        model="m",
        base_url="https://oa.test/v1",
        timeout_seconds=5,
        temperature=0,
        transport=httpx.MockTransport(handler),
    )
    assert await client.generate(system="s", prompt="p", json_mode=True) == "{}"
