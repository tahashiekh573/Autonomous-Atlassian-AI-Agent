"""OpenAI-compatible speech endpoints (transcription + text-to-speech)."""

import httpx
from pydantic import SecretStr

from app.clients.llm.http import post_with_retry
from app.clients.speech.base import SpeechToText, SynthesizedAudio, TextToSpeech
from app.core.exceptions import SpeechError

_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-wav": "wav",
}


class _OpenAISpeechBase:
    provider = "openai"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAISpeechToText(_OpenAISpeechBase, SpeechToText):
    def __init__(self, api_key: SecretStr, *, model: str, **kwargs: object) -> None:
        super().__init__(api_key, **kwargs)  # type: ignore[arg-type]
        self._model = model

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        ext = _EXTENSIONS.get(mime_type.split(";")[0], "webm")
        response = await post_with_retry(
            self._client,
            "/audio/transcriptions",
            error_cls=SpeechError,
            provider="openai-stt",
            files={"file": (f"audio.{ext}", audio, mime_type)},
            data={"model": self._model},
        )
        return str(response.json().get("text", "")).strip()


class OpenAITextToSpeech(_OpenAISpeechBase, TextToSpeech):
    def __init__(self, api_key: SecretStr, *, model: str, voice: str, **kwargs: object) -> None:
        super().__init__(api_key, **kwargs)  # type: ignore[arg-type]
        self._model = model
        self._voice = voice

    async def synthesize(self, text: str) -> SynthesizedAudio:
        response = await post_with_retry(
            self._client,
            "/audio/speech",
            error_cls=SpeechError,
            provider="openai-tts",
            json={
                "model": self._model,
                "voice": self._voice,
                "input": text[:4000],
                "response_format": "mp3",
            },
        )
        return SynthesizedAudio(content=response.content, media_type="audio/mpeg")
