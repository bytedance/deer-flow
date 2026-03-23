"""Declarative feature flags for create_deep_agent.

Pure data classes — no I/O, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# Type alias for SummarizationMiddleware trigger/keep specs
_TriggerSpec = tuple[str, int | float]


@dataclass
class MemoryOptions:
    """Options for the memory feature.

    Phase 1: acts as an enabler (equivalent to ``True``).
    Per-instance fields (storage_path, etc.) will be wired in Phase 2
    when MemoryMiddleware accepts explicit parameters.
    """


@dataclass
class SummarizationOptions:
    """Options for context summarization."""

    model: BaseChatModel | str | None = None
    trigger: _TriggerSpec | list[_TriggerSpec] | None = None
    keep: _TriggerSpec | None = None


@dataclass
class SubagentOptions:
    """Options for subagent delegation."""

    max_concurrent: int = 3


@dataclass
class AgentFeatures:
    """Declarative feature flags. ``create_deep_agent`` uses this to auto-assemble the middleware chain.

    Each feature accepts ``True`` (use defaults), ``False`` (disable), or
    an options instance for fine-grained control.
    """

    # -- Sandbox (ThreadData + Uploads + SandboxMiddleware) --
    sandbox: bool = True

    # -- Memory --
    memory: MemoryOptions | bool = False

    # -- Summarization --
    summarization: SummarizationOptions | bool = False

    # -- Plan Mode (TodoList) --
    plan_mode: bool = False

    # -- Subagent --
    subagent: SubagentOptions | bool = False

    # -- Vision --
    vision: bool = False

    # -- Auto Title --
    auto_title: bool = True

    # -- Loop Detection --
    loop_detection: bool = True

    # -- Extra middleware appended before ClarificationMiddleware --
    extra_middleware: list[AgentMiddleware] = field(default_factory=list)
