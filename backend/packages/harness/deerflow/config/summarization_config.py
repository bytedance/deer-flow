"""Configuration for conversation summarization."""

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ContextSizeType = Literal["fraction", "tokens", "messages"]
DEFAULT_SKILL_FILE_READ_TOOL_NAMES: tuple[str, ...] = ("read_file", "read", "view", "cat")
#: Documented default retention policy after summarization. Shared with the
#: summarization middleware's fraction-keep degradation fallback so the two
#: cannot drift apart.
DEFAULT_KEEP: tuple[ContextSizeType, int] = ("messages", 20)


class ContextSize(BaseModel):
    """Context size specification for trigger or keep parameters."""

    type: ContextSizeType = Field(description="Type of context size specification")
    value: int | float = Field(description="Value for the context size specification")

    @model_validator(mode="after")
    def _validate_value_range(self) -> "ContextSize":
        """Reject value ranges that would silently produce a dead threshold.

        A fraction written percent-style (``value: 80`` instead of ``0.8``) resolves
        to ``int(max_input_tokens * 80)`` — a threshold the context can never reach,
        so the trigger silently never fires. Non-finite floats (YAML ``.nan`` /
        ``.inf`` pass pydantic's float parsing) are dead thresholds the same way
        (``count >= nan`` is always False), and ``nan <= 0`` is False so the
        positivity check alone would not catch them. Failing at config load turns
        these foot-guns into actionable errors, consistent with how fraction
        clauses degrade (loudly) elsewhere. Absolute ``tokens`` values must simply
        be positive to describe a usable threshold, while ``messages`` values must
        additionally be whole numbers: langchain slices the message list with them
        (``messages[-keep:]``), and a float index raises ``TypeError: list indices
        must be integers or slices, not float`` mid-compaction.
        """
        if not math.isfinite(self.value):
            raise ValueError(f"ContextSize value must be finite (got {self.value!r})")
        if self.type == "fraction":
            if not 0 < self.value <= 1:
                raise ValueError(f"fraction ContextSize value must be in (0, 1] (got {self.value!r}) — write 0.8 for 80%, not 80")
        elif self.type == "messages" and not isinstance(self.value, int):
            raise ValueError(f"messages ContextSize value must be a whole number of messages (got {self.value!r}) — it slices the message list, so a float index would raise TypeError at compaction time")
        elif self.value <= 0:
            raise ValueError(f"{self.type} ContextSize value must be positive (got {self.value!r})")
        return self

    def to_tuple(self) -> tuple[ContextSizeType, int | float]:
        """Convert to tuple format expected by SummarizationMiddleware."""
        return (self.type, self.value)


class SummarizationConfig(BaseModel):
    """Configuration for automatic conversation summarization."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable automatic conversation summarization",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for summarization. None = summarize with the model the run "
        "actually executes with (the lead run's model, a subagent's own model, or a thread's "
        "custom-agent model), not config.models[0]. When set, that model generates and the run's "
        "own model is used as a fallback if the configured summary provider fails.",
    )
    trigger: ContextSize | list[ContextSize] | None = Field(
        default=None,
        description="One or more thresholds that trigger summarization. When any threshold is met, summarization runs. "
        "Examples: {'type': 'messages', 'value': 50} triggers at 50 messages, "
        "{'type': 'tokens', 'value': 4000} triggers at 4000 tokens, "
        "{'type': 'fraction', 'value': 0.8} triggers at 80% of model's max input tokens",
    )
    keep: ContextSize = Field(
        default_factory=lambda: ContextSize(type=DEFAULT_KEEP[0], value=DEFAULT_KEEP[1]),
        description="Context retention policy after summarization. Specifies how much history to preserve. "
        "Examples: {'type': 'messages', 'value': 20} keeps 20 messages, "
        "{'type': 'tokens', 'value': 3000} keeps 3000 tokens, "
        "{'type': 'fraction', 'value': 0.3} keeps 30% of model's max input tokens",
    )
    trim_tokens_to_summarize: int | None = Field(
        default=4000,
        description="Maximum tokens to keep when preparing messages for summarization. Pass null to skip trimming.",
    )
    summary_prompt: str | None = Field(
        default=None,
        description="Custom prompt template for generating summaries. If not provided, uses the default LangChain prompt.",
    )
    skill_file_read_tool_names: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKILL_FILE_READ_TOOL_NAMES),
        description="Tool names treated as skill-file reads when capturing loaded skills into the durable skill_context channel.",
    )


# Global configuration instance
_summarization_config: SummarizationConfig = SummarizationConfig()


def get_summarization_config() -> SummarizationConfig:
    """Get the current summarization configuration."""
    return _summarization_config


def set_summarization_config(config: SummarizationConfig) -> None:
    """Set the summarization configuration."""
    global _summarization_config
    _summarization_config = config


def load_summarization_config_from_dict(config_dict: dict) -> None:
    """Load summarization configuration from a dictionary."""
    global _summarization_config
    _summarization_config = SummarizationConfig(**config_dict)
