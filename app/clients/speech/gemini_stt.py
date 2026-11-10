"""Speech-to-text using Gemini's native audio understanding."""

from app.clients.llm.gemini_client import GeminiClient
from app.clients.speech.base import SpeechToText
from app.core.exceptions import LLMError, SpeechError


class GeminiSpeechToText(SpeechToText):
    provider = "gemini"

    def __init__(self, client: GeminiClient, instructions: str) -> None:
        self._client = client
        self._instructions = instructions

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        try:
            text = await self._client.generate_from_audio(
                prompt=self._instructions, audio=audio, mime_type=mime_type
            )
        except LLMError as exc:
            raise SpeechError(f"Transcription failed: {exc.message}") from exc
        return text.strip()
