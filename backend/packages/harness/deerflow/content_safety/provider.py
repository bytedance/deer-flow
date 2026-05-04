"""Content safety provider protocol and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ContentSafetyRequest:
    """Context passed to the provider for content evaluation."""

    text: str
    role: str  # "user" or "assistant"
    thread_id: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentSafetyDecision:
    """Provider's content safety verdict."""

    allowed: bool
    flagged_categories: list[str] = field(default_factory=list)
    sanitized_text: str | None = None
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ContentSafetyProvider(Protocol):
    """Contract for pluggable content safety evaluation.

    Separate from GuardrailProvider because content safety operates on
    message text (user input / AI output), while GuardrailProvider
    operates on tool calls.
    """

    name: str

    def evaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        """Evaluate whether content should be allowed."""
        ...

    async def aevaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        """Async variant."""
        ...
