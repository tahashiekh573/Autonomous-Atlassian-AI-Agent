"""Input Understanding Agent: intent, language normalisation and missing-information detection."""

from app.agents.base_agent import LLMAgent
from app.schemas.agents import Intent, UnderstandingInput


class InputUnderstandingAgent(LLMAgent[UnderstandingInput, Intent]):
    name = "input_understanding_agent"
    prompt_name = "input_understanding_system"

    async def run(self, data: UnderstandingInput) -> Intent:
        history = "\n".join(f"{t.role.upper()}: {t.content}" for t in data.history[-10:])
        prompt = (
            f"Input mode: {data.input_mode}"
            + (
                " (speech transcript - expect recognition errors)"
                if data.input_mode == "voice"
                else ""
            )
            + (f"\n\nConversation so far:\n{history}" if history else "")
            + f"\n\nLatest user message:\n{data.text}"
        )
        return await self._structured(prompt, Intent)
