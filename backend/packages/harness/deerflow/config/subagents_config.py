"""Configuration for the subagent system loaded from config.yaml."""

import logging

from pydantic import BaseModel, Field

from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)


def default_subagent_token_budget() -> TokenBudgetConfig:
    """Default per-run token budget for subagents (#3875 Phase 2).

    Enabled by default so the pathological-token-burn backstop actually
    engages (per umbrella #3857 point 4 — backstops must engage, not just
    exist). ``max_tokens`` is a deliberately loose ceiling: the reported 4.4M
    burn would have been cut roughly in half, while legitimate deep-research
    runs (``max_turns=150``, no summarization yet) can genuinely accumulate
    >1M cumulative input today. Tighten after Phase 3 lands subagent
    summarization. Flagged tunable in the PR description.
    """
    return TokenBudgetConfig(enabled=True, max_tokens=2_000_000, warn_threshold=0.7)


class SubagentOverrideConfig(BaseModel):
    """Per-agent configuration overrides."""

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Timeout in seconds for this subagent (None = use global default)",
    )
    max_turns: int | None = Field(
        default=None,
        ge=1,
        description="Maximum turns for this subagent (None = use global or builtin default)",
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        description="Model name for this subagent (None = inherit from parent agent)",
    )
    skills: list[str] | None = Field(
        default=None,
        description="Skill names whitelist for this subagent (None = inherit all enabled skills, [] = no skills)",
    )
    token_budget: TokenBudgetConfig | None = Field(
        default=None,
        description="Per-run token budget override for this subagent (None = use the global subagents.token_budget default). Symmetric with timeout_seconds/max_turns.",
    )


class CustomSubagentConfig(BaseModel):
    """User-defined subagent type declared in config.yaml."""

    description: str = Field(
        description="When the lead agent should delegate to this subagent",
    )
    system_prompt: str = Field(
        description="System prompt that guides the subagent's behavior",
    )
    tools: list[str] | None = Field(
        default=None,
        description="Tool names whitelist (None = inherit all tools from parent)",
    )
    disallowed_tools: list[str] | None = Field(
        default_factory=lambda: ["task", "ask_clarification", "present_files"],
        description="Tool names to deny",
    )
    skills: list[str] | None = Field(
        default=None,
        description="Skill names whitelist (None = inherit all enabled skills, [] = no skills)",
    )
    model: str = Field(
        default="inherit",
        description="Model to use - 'inherit' uses parent's model",
    )
    max_turns: int = Field(
        default=50,
        ge=1,
        description="Maximum number of agent turns before stopping",
    )
    timeout_seconds: int = Field(
        default=900,
        ge=1,
        description="Maximum execution time in seconds",
    )


class SubagentsAppConfig(BaseModel):
    """Configuration for the subagent system."""

    timeout_seconds: int = Field(
        default=1800,
        ge=1,
        description="Default timeout in seconds for built-in subagents (default: 1800 = 30 minutes); custom agents use their own timeout_seconds unless given a per-agent override",
    )
    max_turns: int | None = Field(
        default=None,
        ge=1,
        description="Optional default max-turn override for all subagents (None = keep builtin defaults)",
    )
    token_budget: TokenBudgetConfig = Field(
        default_factory=default_subagent_token_budget,
        description="Default per-run token budget for subagents — a cost-ceiling backstop that engages by default (#3875 Phase 2). Set enabled: false to disable, or override per agent via agents.<name>.token_budget.",
    )
    agents: dict[str, SubagentOverrideConfig] = Field(
        default_factory=dict,
        description="Per-agent configuration overrides keyed by agent name",
    )
    custom_agents: dict[str, CustomSubagentConfig] = Field(
        default_factory=dict,
        description="User-defined subagent types keyed by agent name",
    )

    def get_timeout_for(self, agent_name: str) -> int:
        """Get the effective timeout for a specific agent.

        Args:
            agent_name: The name of the subagent.

        Returns:
            The timeout in seconds, using per-agent override if set, otherwise global default.
        """
        override = self.agents.get(agent_name)
        if override is not None and override.timeout_seconds is not None:
            return override.timeout_seconds
        return self.timeout_seconds

    def get_model_for(self, agent_name: str) -> str | None:
        """Get the model override for a specific agent.

        Args:
            agent_name: The name of the subagent.

        Returns:
            Model name if overridden, None otherwise (subagent will inherit parent model).
        """
        override = self.agents.get(agent_name)
        if override is not None and override.model is not None:
            return override.model
        return None

    def get_max_turns_for(self, agent_name: str, builtin_default: int) -> int:
        """Get the effective max_turns for a specific agent."""
        override = self.agents.get(agent_name)
        if override is not None and override.max_turns is not None:
            return override.max_turns
        if self.max_turns is not None:
            return self.max_turns
        return builtin_default

    def get_skills_for(self, agent_name: str) -> list[str] | None:
        """Get the skills override for a specific agent.

        Args:
            agent_name: The name of the subagent.

        Returns:
            Skill names whitelist if overridden, None otherwise (subagent will inherit all enabled skills).
        """
        override = self.agents.get(agent_name)
        if override is not None and override.skills is not None:
            return override.skills
        return None

    def get_token_budget_for(self, agent_name: str) -> TokenBudgetConfig:
        """Get the effective token-budget config for a specific agent.

        Unlike ``max_turns``/``timeout_seconds`` (which keep a custom agent's
        own value), the token budget is a safety backstop that must engage for
        every subagent unless explicitly disabled — so the per-agent override
        wins when set, otherwise the global default applies to built-in AND
        custom agents alike (#3875 Phase 2 / umbrella #3857 point 4).
        """
        override = self.agents.get(agent_name)
        if override is not None and override.token_budget is not None:
            return override.token_budget
        return self.token_budget


_subagents_config: SubagentsAppConfig = SubagentsAppConfig()


def get_subagents_app_config() -> SubagentsAppConfig:
    """Get the current subagents configuration."""
    return _subagents_config


def load_subagents_config_from_dict(config_dict: dict) -> None:
    """Load subagents configuration from a dictionary."""
    global _subagents_config
    _subagents_config = SubagentsAppConfig(**config_dict)

    overrides_summary = {}
    for name, override in _subagents_config.agents.items():
        parts = []
        if override.timeout_seconds is not None:
            parts.append(f"timeout={override.timeout_seconds}s")
        if override.max_turns is not None:
            parts.append(f"max_turns={override.max_turns}")
        if override.model is not None:
            parts.append(f"model={override.model}")
        if override.skills is not None:
            parts.append(f"skills={override.skills}")
        if parts:
            overrides_summary[name] = ", ".join(parts)

    custom_agents_names = list(_subagents_config.custom_agents.keys())

    if overrides_summary or custom_agents_names:
        logger.info(
            "Subagents config loaded: default timeout=%ss, default max_turns=%s, per-agent overrides=%s, custom_agents=%s",
            _subagents_config.timeout_seconds,
            _subagents_config.max_turns,
            overrides_summary or "none",
            custom_agents_names or "none",
        )
