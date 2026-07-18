"""Configuration for the subagent system loaded from config.yaml."""

import logging

from pydantic import BaseModel, Field

from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN = 6
MIN_TOTAL_SUBAGENTS_PER_RUN = 1
MAX_TOTAL_SUBAGENTS_PER_RUN = 50
MIN_CONCURRENT_SUBAGENT_CALLS = 2
MAX_CONCURRENT_SUBAGENT_CALLS = 4


def clamp_subagent_concurrency(value: int) -> int:
    """Clamp per-response task call concurrency to the enforced middleware range."""
    return max(MIN_CONCURRENT_SUBAGENT_CALLS, min(MAX_CONCURRENT_SUBAGENT_CALLS, value))


def clamp_total_subagents_per_run(value: int) -> int:
    """Clamp per-run task delegation totals to the enforced middleware range."""
    return max(MIN_TOTAL_SUBAGENTS_PER_RUN, min(MAX_TOTAL_SUBAGENTS_PER_RUN, value))


def default_subagent_token_budget(*, summarization_enabled: bool = False) -> TokenBudgetConfig:
    """Default per-run token budget for subagents (#3875 Phase 2 → Phase 3 coupling).

    Enabled by default so the pathological-token-burn backstop actually
    engages (per umbrella #3857 point 4 — backstops must engage, not just
    exist). ``max_tokens`` is **coupled to whether subagent summarization is
    on** (#3875 Phase 3 review point):

    - ``summarization_enabled=True`` (Phase 3 compacts the running context
      before it reaches pathological size): **1M** — tighter ceiling still
      covers legitimate deep research while catching degenerate runs earlier.
    - ``summarization_enabled=False``: **2M** — the Phase 2 ceiling. Phase 2's
      own docstring noted legitimate deep-research runs (``max_turns=150``,
      no summarization) "can genuinely accumulate >1M cumulative input," so a
      1M ceiling without compaction would prematurely cap them. Keeping 2M
      here preserves that headroom; the tighter 1M only applies when the
      compaction that justifies it is actually running.

    The model-level ``default_factory`` (``SubagentsAppConfig.token_budget``)
    cannot read ``summarization.enabled`` (a sibling top-level field), so it
    falls back to the 2M no-compaction default; the builder
    (``build_subagent_runtime_middlewares``) recomputes via
    ``get_token_budget_for(..., summarization_enabled=...)`` so the live value
    reflects the actual switch. A user-set ``token_budget`` (global or
    per-agent) always wins regardless of the switch. Flagged tunable.
    """
    max_tokens = 1_000_000 if summarization_enabled else 2_000_000
    return TokenBudgetConfig(enabled=True, max_tokens=max_tokens, warn_threshold=0.7)


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
    max_total_per_run: int = Field(
        default=DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
        ge=MIN_TOTAL_SUBAGENTS_PER_RUN,
        le=MAX_TOTAL_SUBAGENTS_PER_RUN,
        description="Default total number of subagent delegations allowed in one lead-agent run. This is a deterministic backstop against repeated legal-sized task batches. Valid range: 1-50.",
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

    # True when ``token_budget`` was NOT explicitly provided by the user, i.e.
    # the field fell back to its default_factory. ``get_token_budget_for`` uses
    # this to decide whether the ceiling may be re-coupled to
    # ``summarization.enabled`` (#3875 Phase 3): a user-set budget is always
    # respected as-is. Set by ``__init__`` from ``model_fields_set`` and
    # preserved across the app-config reload path (which drops a default
    # ``token_budget`` before re-constructing — see
    # ``load_subagents_config_from_dict``).
    _token_budget_is_default: bool = True

    def __init__(self, **data):
        super().__init__(**data)
        self._token_budget_is_default = "token_budget" not in self.model_fields_set

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

    def get_token_budget_for(
        self,
        agent_name: str,
        *,
        summarization_enabled: bool = False,
    ) -> TokenBudgetConfig:
        """Get the effective token-budget config for a specific agent.

        Unlike ``max_turns``/``timeout_seconds`` (which keep a custom agent's
        own value), the token budget is a safety backstop that must engage for
        every subagent unless explicitly disabled — so the per-agent override
        wins when set, otherwise the global default applies to built-in AND
        custom agents alike (#3875 Phase 2 / umbrella #3857 point 4).

        ``summarization_enabled`` couples the DEFAULT ceiling to whether
        subagent summarization is on (#3875 Phase 3 review): 1M when
        compaction is running, 2M otherwise. It ONLY affects the default —
        any explicitly configured ``token_budget`` (global or per-agent)
        wins regardless, so a deployment that pinned a value is never
        silently changed by flipping the summarization switch.
        """
        override = self.agents.get(agent_name)
        if override is not None and override.token_budget is not None:
            return override.token_budget
        # Only recompute when the caller is using the default (no explicit
        # global token_budget was set). A user-set global is respected as-is.
        if self._token_budget_is_default:
            return default_subagent_token_budget(summarization_enabled=summarization_enabled)
        return self.token_budget


_subagents_config: SubagentsAppConfig = SubagentsAppConfig()


def get_subagents_app_config() -> SubagentsAppConfig:
    """Get the current subagents configuration."""
    return _subagents_config


def load_subagents_config_from_dict(config_dict: dict) -> None:
    """Load subagents configuration from a dictionary."""
    global _subagents_config
    # The app-config reload path (app_config.py) round-trips via
    # ``config.subagents.model_dump()``, which serializes a default
    # ``token_budget`` into the dict. Re-constructing from that dict would make
    # ``model_fields_set`` contain ``token_budget`` and flip
    # ``_token_budget_is_default`` to False — breaking the
    # summarization-coupled recompute in ``get_token_budget_for`` (#3875 Phase
    # 3). Drop the key when its value still equals the no-compaction default so
    # the default_factory fires on reconstruction and the "user did not set
    # this" signal is preserved.
    tb = config_dict.get("token_budget")
    if tb is not None and tb == default_subagent_token_budget(summarization_enabled=False).model_dump():
        config_dict = {k: v for k, v in config_dict.items() if k != "token_budget"}
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
