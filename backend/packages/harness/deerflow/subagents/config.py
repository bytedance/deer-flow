"""Subagent configuration definitions."""

from dataclasses import dataclass, field


@dataclass
class SubagentConfig:
    """Configuration for a subagent.

    Attributes:
        名称: Unique identifier for the subagent.
        描述: When Claude should delegate to this subagent.
        system_prompt: The 系统 提示词 that guides the subagent's behavior.
        tools: Optional 列表 of 工具 names to allow. If None, inherits all tools.
        disallowed_tools: Optional 列表 of 工具 names to deny.
        模型: 模型 to use - 'inherit' uses parent's 模型.
        max_turns: Maximum 数字 of 代理 turns before stopping.
        timeout_seconds: Maximum execution time in seconds (默认: 900 = 15 minutes).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    model: str = "inherit"
    max_turns: int = 50
    timeout_seconds: int = 900
