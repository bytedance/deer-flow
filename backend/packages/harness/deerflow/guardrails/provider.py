"""GuardrailProvider protocol and data structures for pre-tool-call authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailRequest:
    """Context passed to the provider for each tool call."""

    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None = None
    thread_id: str | None = None
    is_subagent: bool = False
    timestamp: str = ""


@dataclass
class GuardrailReason:
    """Structured reason for an allow/deny decision (OAP reason object)."""

    code: str
    message: str = ""


@dataclass
class GuardrailDecision:
    """Provider's allow/deny verdict (aligned with OAP Decision object)."""

    allow: bool
    reasons: list[GuardrailReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailProvider(Protocol):
    """Contract for pluggable tool-call authorization.

    Any class with these methods works - no base class required.
    Providers are loaded by class path via resolve_variable(),
    the same mechanism DeerFlow uses for models, tools, and sandbox.
    """

    name: str

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Evaluate whether a tool call should proceed."""
        ...

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Async variant."""
        ...
