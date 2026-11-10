"""Base classes for all agents.

Every agent has one focused responsibility and exposes exactly one public coroutine: ``run``.
Agents never call each other; the orchestrators coordinate them.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.clients.llm.base import LLMClient
from app.core.exceptions import LLMError
from app.core.prompts import load_prompt

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
ModelT = TypeVar("ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    name: str = "agent"

    @abstractmethod
    async def run(self, data: InputT) -> OutputT:
        """Perform the agent's single task."""


class LLMAgent(BaseAgent[InputT, OutputT]):
    """An agent whose task is performed by a language model with a Markdown system prompt."""

    prompt_name: str = ""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.prompt_name)

    async def _structured(
        self, prompt: str, output: type[ModelT], system: str | None = None
    ) -> ModelT:
        """Ask for JSON matching ``output``; one repair round-trip on invalid output."""
        system = system or self.system_prompt
        schema = json.dumps(output.model_json_schema(), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\nRespond with a single JSON object matching this JSON Schema:\n{schema}"
        )
        raw = await self._llm.generate(system=system, prompt=full_prompt, json_mode=True)
        try:
            return output.model_validate_json(_strip_fences(raw))
        except ValidationError as first_error:
            logger.warning("%s: invalid structured output, asking model to repair", self.name)
            repair = (
                f"{full_prompt}\n\nYour previous answer was invalid:\n{raw[:4000]}\n\n"
                f"Validation errors:\n{_error_summary(first_error)}\n\nReturn corrected JSON only."
            )
            raw = await self._llm.generate(system=system, prompt=repair, json_mode=True)
            try:
                return output.model_validate_json(_strip_fences(raw))
            except ValidationError as exc:
                raise LLMError(
                    f"{self.name}: model output did not match the expected schema",
                    details={"errors": _error_summary(exc)},
                ) from exc


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _error_summary(exc: ValidationError) -> str:
    return "\n".join(f"- {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:20])
