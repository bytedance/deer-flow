"""Subagent configuration definitions."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SubagentConfig:
    """Configuration for a subagent.

    Attributes:
        name: Unique identifier for the subagent.
        description: When Claude should delegate to this subagent.
        system_prompt: The system prompt that guides the subagent's behavior.
        tools: Optional list of tool names to allow. If None, inherits all tools.
        disallowed_tools: Optional list of tool names to deny.
        model: Model to use - 'inherit' uses parent's model.
        thinking_enabled: Whether to enable model thinking for this subagent.
            - "inherit": use parent run setting
            - True/False: explicit override per subagent type
        thinking_effort: Adaptive reasoning effort for providers that support it.
            - "inherit": use parent run effort
            - None: do not set an explicit effort (provider default)
            - "low"/"medium"/"high"/...: explicit override per subagent type
        max_turns: Maximum number of agent turns before stopping.
        timeout_seconds: Maximum execution time in seconds (default: 900 = 15 minutes).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    model: str = "inherit"
    thinking_enabled: bool | Literal["inherit"] = "inherit"
    thinking_effort: str | Literal["inherit"] | None = "inherit"
    max_turns: int = 50
    timeout_seconds: int = 900
