"""Build configured speech providers."""

from app.clients.llm.base import LLMClient
from app.clients.llm.gemini_client import GeminiClient
from app.clients.speech.base import SpeechToText, TextToSpeech
from app.clients.speech.gemini_stt import GeminiSpeechToText
from app.clients.speech.openai_speech import OpenAISpeechToText, OpenAITextToSpeech
from app.core.config import Settings
from app.core.prompts import load_prompt


def build_stt(settings: Settings, llm: LLMClient | None) -> SpeechToText | None:
    if settings.stt_provider == "gemini":
        gemini = llm if isinstance(llm, GeminiClient) else None
        if gemini is None and settings.gemini_api_key:
            gemini = GeminiClient(
                settings.gemini_api_key,
                model=settings.gemini_model,
                base_url=settings.gemini_base_url,
                timeout_seconds=settings.llm_timeout_seconds,
                temperature=0.0,
            )
        return GeminiSpeechToText(gemini, load_prompt("speech_transcription")) if gemini else None
    if settings.stt_provider == "openai" and settings.openai_api_key:
        return OpenAISpeechToText(
            settings.openai_api_key,
            model=settings.openai_stt_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return None


def build_tts(settings: Settings) -> TextToSpeech | None:
    if settings.tts_provider == "openai" and settings.openai_api_key:
        return OpenAITextToSpeech(
            settings.openai_api_key,
            model=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return None
