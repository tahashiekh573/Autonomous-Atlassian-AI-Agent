"""Provider-agnostic speech interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SynthesizedAudio:
    content: bytes
    media_type: str


class SpeechToText(ABC):
    provider: str = "base"

    @abstractmethod
    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        """Return a verbatim transcript (Urdu script, Roman Urdu or English as spoken)."""


class TextToSpeech(ABC):
    provider: str = "base"

    @abstractmethod
    async def synthesize(self, text: str) -> SynthesizedAudio:
        """Return spoken audio for ``text``."""
