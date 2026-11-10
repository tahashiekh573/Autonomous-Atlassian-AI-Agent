"""Voice input/output: speech-to-text feeds the same run pipeline as text."""

from app.clients.speech.base import SpeechToText, SynthesizedAudio, TextToSpeech
from app.core.exceptions import ConfigurationError, RequestValidationAppError, SpeechError

ALLOWED_AUDIO = (
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/flac",
)


class VoiceService:
    def __init__(self, stt: SpeechToText | None, tts: TextToSpeech | None, max_bytes: int) -> None:
        self._stt = stt
        self._tts = tts
        self._max_bytes = max_bytes

    @property
    def capabilities(self) -> dict[str, str | None]:
        return {
            "stt": self._stt.provider if self._stt else None,
            "tts": self._tts.provider if self._tts else None,
        }

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        if self._stt is None:
            raise ConfigurationError("Speech-to-text is not configured (STT_PROVIDER).")
        base = (mime_type or "").split(";")[0].strip().lower()
        if base not in ALLOWED_AUDIO:
            raise RequestValidationAppError(f"Unsupported audio type '{mime_type}'.")
        if not audio:
            raise RequestValidationAppError("The audio file is empty.")
        if len(audio) > self._max_bytes:
            raise RequestValidationAppError(f"Audio exceeds {self._max_bytes // (1024 * 1024)} MB.")
        text = await self._stt.transcribe(audio, base)
        if not text:
            raise SpeechError("No speech was recognised in the recording.")
        return text

    async def speak(self, text: str) -> SynthesizedAudio:
        if self._tts is None:
            raise ConfigurationError(
                "Server-side text-to-speech is not configured (TTS_PROVIDER); the dashboard "
                "falls back to the browser's speech synthesis."
            )
        return await self._tts.synthesize(text)
