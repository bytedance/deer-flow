"""Subagent configuration definitions."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from deerflow.config.prompt_overlay import PromptOverlay

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig


@dataclass
class SubagentConfig:
    """Configuration for a subagent.

    Attributes:
        name: Unique identifier for the subagent.
        description: When Claude should delegate to this subagent.
        system_prompt: Operator-owned system instructions.
        user_soul: User-authored persona, injected as sanitized request data.
        tools: Optional list of tool names to allow. If None, inherits all tools.
        disallowed_tools: Optional list of tool names to deny.
        skills: Optional list of skill names to make discoverable and activatable.
                If None, all enabled skills are available. If empty, skills are
                disabled for this subagent. Skill bodies and their allowed-tools
                policies take effect only after activation/loading at runtime.
        model: Model to use - 'inherit' uses parent's model.
        max_turns: Maximum agent turns — model call plus the tools it runs —
            before stopping. Built-in agents use the value set here
            (general-purpose=150, bash=60) unless the global
            ``subagents.max_turns`` is set. ``turn_budget.py`` converts this
            into the LangGraph ``recursion_limit`` that buys that many turns
            through the assembled middleware chain; it is not passed through as
            a super-step count.
        timeout_seconds: Bare fallback execution-time cap. For built-in agents the
            effective limit is the global ``subagents.timeout_seconds`` (default
            1800 = 30 min), layered on by the registry; this 900 only applies
            when no differing global value exists.
        prompt_overlay: Operator instructions around the complete system message.
    """

    name: str
    description: str
    system_prompt: str | None = None
    user_soul: str | None = None
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    skills: list[str] | None = None
    model: str = "inherit"
    model_settings: dict[str, object] | None = None
    thinking_enabled: bool | None = None
    reasoning_effort: str | None = None
    max_turns: int = 50
    timeout_seconds: int = 900
    prompt_overlay: PromptOverlay = field(default_factory=PromptOverlay)


def _default_model_name(app_config: "AppConfig") -> str:
    if not app_config.models:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")
    return app_config.models[0].name


def resolve_subagent_model_name(config: SubagentConfig, parent_model: str | None, *, app_config: "AppConfig | None" = None) -> str:
    """Resolve the effective model name a subagent should use."""
    if config.model != "inherit":
        return config.model

    if parent_model is not None:
        return parent_model

    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()
    return _default_model_name(app_config)


def authorize_subagent_model_name(model_name: str, *, context: dict[str, Any], app_config: "AppConfig") -> str:
    """Select an authorized model before assembling model-dependent tools.

    Call off-loop: the shared lead-agent policy may query an external provider.
    The dispatcher must pass this decision and AppConfig snapshot to the executor.
    """
    if getattr(app_config, "authorization", None) is None or app_config.authorization.enabled is not True:
        return model_name

    from deerflow.agents.lead_agent.agent import _authorize_model_name

    return _authorize_model_name(model_name, context=context, app_config=app_config)
