"""Provider-agnostic LLM interface."""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    provider: str = "base"
    model: str = ""

    @abstractmethod
    async def generate(self, *, system: str, prompt: str, json_mode: bool = False) -> str:
        """Return the model's text completion (a JSON string when ``json_mode``)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""
