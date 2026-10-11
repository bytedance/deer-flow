"""Literal operator-owned extensions around an assembled system prompt."""

from pydantic import BaseModel, ConfigDict, Field


class PromptOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prepend: str = Field(default="", strict=True)
    append: str = Field(default="", strict=True)

    def apply(self, prompt: str) -> str:
        return "\n\n".join(part for part in (self.prepend, prompt, self.append) if part)
