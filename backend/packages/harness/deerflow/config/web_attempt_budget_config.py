"""Optional process-local limit on first-party Web HTTP attempts per run."""

from pydantic import BaseModel, Field, field_validator


class WebAttemptBudgetConfig(BaseModel):
    # None keeps the existing, unlimited behavior. A positive number enables
    # the policy for Serper web/image search and Jina web_fetch.
    max_attempts: int | None = Field(default=None, ge=1)

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("max_attempts must be a positive integer or null")
        return value
