"""Configuration and loaders for custom agents.

Custom agents are stored per-user under ``{base_dir}/users/{user_id}/agents/{name}/``.
A legacy shared layout at ``{base_dir}/agents/{name}/`` is still readable so that
installations that pre-date user isolation continue to work until they run the
``scripts/migrate_user_isolation.py`` migration. New writes always target the
per-user layout.
"""

import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
MAX_AGENT_OUTPUT_TOKENS = 200_000


def _blank_to_none(value: str | None) -> str | None:
    """Normalize a whitespace-only string to ``None``; leave real values untouched.

    A whitespace-only string (e.g. ``"   "``) is truthy in Python, so an
    unstripped ``value or fallback`` expression never falls through to the
    fallback. The ``require_mention`` precedence chain (``trigger.mention_login``
    -> ``github.bot_login`` -> ``channels.github.default_mention_login`` ->
    ``agent.name``, see AGENTS.md) relies on exactly that fallthrough, so both
    of the config-sourced links are normalized here, once, at the model layer
    — every reader downstream (today's and any future one) sees an honest
    "unset" instead of a literal whitespace string that can never match a
    real ``@mention``.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class GitHubTriggerConfig(BaseModel):
    """Per-event trigger filter inside a :class:`GitHubBinding`."""

    # If set, only these GitHub action values fire the agent. None means "any
    # action allowed". Example: ["opened"] for pull_request restricts the agent
    # to only respond to brand-new PRs.
    actions: list[str] | None = None
    # If True, comment events only fire when the bot login is @-mentioned in
    # the comment body. Ignored on non-comment events.
    require_mention: bool = False
    # GitHub logins whose events bypass require_mention. Lets a repo owner
    # talk to the bot without typing the handle every time.
    allow_authors: list[str] = Field(default_factory=list)
    # Override the global default bot mention login for this trigger only.
    # Useful when one agent answers as @bot-a and another as @bot-b. A
    # whitespace-only value is normalized to None (see ``_blank_to_none``) so
    # it is treated as unset and falls through to ``github.bot_login`` instead
    # of being compared against literally.
    mention_login: str | None = None

    @field_validator("mention_login")
    @classmethod
    def _normalize_mention_login(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class GitHubBinding(BaseModel):
    """One (agent, repo) binding with per-event trigger overrides."""

    # GitHub "owner/name" string.
    repo: str
    # Event name → trigger override. Missing keys fall back to the dispatcher's
    # default trigger for that event.
    triggers: dict[str, GitHubTriggerConfig] = Field(default_factory=dict)


class GitHubAgentConfig(BaseModel):
    """Top-level ``github:`` block on a custom agent's ``config.yaml``."""

    # GitHub App installation id used to mint per-repo access tokens. The
    # ``ChannelManager`` mints a 1h installation token from this and injects it
    # into ``run_context["github_token"]``, which the ``bash`` tool exposes to
    # the agent's sandbox as ``GH_TOKEN`` / ``GITHUB_TOKEN``. The agent then
    # uses ``gh`` to read repo state, push branches, and post comments itself.
    # None means no token is minted: the agent still runs but cannot push or
    # post (effectively read-only via unauthenticated ``gh`` for public repos,
    # or fully blind for private ones).
    installation_id: int | None = None
    # GitHub App login this agent posts as (e.g. ``llm-gateway-ai`` for the
    # ``llm-gateway-ai[bot]`` App identity, without the ``[bot]`` suffix).
    # The dispatcher's self-event gate uses this to recognize webhook
    # deliveries triggered by this agent's own activity, regardless of what
    # ``mention_login`` the agent uses for trigger matching. None means
    # "fall back to mention_login / agent name", which is fine when those
    # match the bot identity, but should be set explicitly when they differ.
    # A whitespace-only value is normalized to None (see ``_blank_to_none``)
    # so it is treated as unset and falls through the rest of the chain.
    bot_login: str | None = None
    # Override the default github-channel ``recursion_limit`` (250). GitHub
    # runs are autonomous and long-running by nature — clone, explore, edit,
    # test, push, comment — but the right ceiling varies a lot by workload:
    # a review-only agent might be happy at 50, a multi-file refactor agent
    # might need 500+. Setting None means "use the channel default (250)".
    # Any positive integer is honored verbatim — including values below the
    # channel default and below the global 100-step floor — so an explicit
    # safety setting like ``recursion_limit: 50`` halts the agent at 50
    # super-steps as configured. Values <=0 are ignored (treated as None)
    # — a negative/zero limit would halt the agent before the first step.
    recursion_limit: int | None = None
    # Repos this agent is bound to. Empty list = bound to nothing = the agent
    # never fires from a webhook, even if it has a ``github:`` block.
    bindings: list[GitHubBinding] = Field(default_factory=list)

    @field_validator("bot_login")
    @classmethod
    def _normalize_bot_login(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _unique_binding_repos(self) -> "GitHubAgentConfig":
        """Reject duplicate ``repo`` values across ``bindings``.

        At most one binding per repo is allowed. The per-event ``triggers``
        map on a single binding already expresses "this agent listens to N
        events on this repo", so multiple bindings for the same repo would
        either duplicate events (silent first-wins / double-registration —
        see PR feedback R3) or fragment them across rows for no benefit.
        Since this is the initial implementation and no existing operator
        config relies on duplicate-repo bindings, we fail loudly at config
        load instead of papering over the ambiguity at dispatch time.
        """
        seen: set[str] = set()
        dupes: set[str] = set()
        for binding in self.bindings:
            if binding.repo in seen:
                dupes.add(binding.repo)
            seen.add(binding.repo)
        if dupes:
            raise ValueError(f"Agent github.bindings has duplicate repos {sorted(dupes)}. Each repo must appear at most once — merge their `triggers:` maps into a single binding.")
        return self


def validate_agent_name(name: str | None) -> str | None:
    """Validate a custom agent name before using it in filesystem paths."""
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError("Invalid agent name. Expected a string or None.")
    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    return name


class AgentModelSettings(BaseModel):
    """Per-agent LLM sampling overrides layered on top of the model profile.

    These are provider sampling knobs (not DeerFlow runtime switches like
    ``thinking_enabled``). They let two agents that reference the *same*
    ``models:`` profile still run with different temperature / output length —
    the core ask of issue #4336, where "different agents have different
    capabilities, so a shared temperature is a poor fit".

    ``extra="forbid"``: the sampling surface is an explicit allowlist so a
    stray key never reaches the provider request body and fails at request
    time with an opaque error. Widen it by adding a declared field (e.g.
    ``top_p``) rather than relaxing the model config. Every field is optional;
    ``None`` means "do not override the profile value".
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature override (0.0-2.0). None = inherit the model profile's value.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=MAX_AGENT_OUTPUT_TOKENS,
        description=f"Max output tokens override (1-{MAX_AGENT_OUTPUT_TOKENS}). None = inherit the model profile's value.",
    )


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    # skills controls which skills are discoverable and may be activated by the
    # agent. It does not activate their allowed-tools policies at construction:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"]: load only the specified skills
    skills: list[str] | None = None
    # Per-agent LLM sampling overrides (temperature / max_tokens) layered on top
    # of the referenced model profile. None = no overrides (issue #4336).
    model_settings: AgentModelSettings | None = None
    # Per-agent thinking-mode default. None = do not override the runtime
    # default (a request-supplied thinking flag still wins over this).
    thinking_enabled: bool | None = None
    # Per-agent reasoning-effort default for models that support it. None = do
    # not override (a request-supplied reasoning_effort still wins over this).
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    # Optional binding to GitHub repositories so this agent can respond to
    # webhook events from the gateway dispatcher. None means "no GitHub
    # integration", which is the case for every existing agent.
    github: GitHubAgentConfig | None = None


# Fields explicitly managed by agent-update surfaces. Anything else declared
# on :class:`AgentConfig` — currently ``github``, and any future field — is
# preserved verbatim by :func:`preserve_non_managed_fields` so update surfaces
# do not silently drop hand-authored configuration. Some surfaces expose only a
# subset of these managed fields (for example, the harness ``update_agent``
# tool does not accept model-behavior arguments), so they must carry their
# unsupported managed fields forward explicitly when rewriting config.yaml.
# ``name`` is included because updaters always re-emit it from the directory
# name (it must never come from the request body).
MANAGED_AGENT_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "model",
        "tool_groups",
        "skills",
        "model_settings",
        "thinking_enabled",
        "reasoning_effort",
    }
)


def preserve_non_managed_fields(existing_cfg: AgentConfig) -> dict[str, object]:
    """Return every top-level field on ``existing_cfg`` not in :data:`MANAGED_AGENT_CONFIG_FIELDS`.

    Used by the two surfaces that rewrite a custom agent's ``config.yaml``
    (the ``update_agent`` harness tool and the HTTP ``PATCH /api/agents/{name}``
    route) to carry forward any hand-authored field — currently ``github``,
    and any field added to :class:`AgentConfig` in the future — that the
    update API does not expose as an argument. Without this, operators who
    hand-author a ``github:`` block on a custom agent would silently lose
    it the next time the agent or a UI editor touched ``description`` /
    ``model`` / ``tool_groups`` / ``skills``.

    ``exclude_unset=True`` is recursive in Pydantic v2, so a sub-field the
    user did not write (and that defaulted to a Pydantic default) is not
    materialized into the dict — the file round-trips visually intact.
    """
    return existing_cfg.model_dump(exclude_unset=True, exclude=MANAGED_AGENT_CONFIG_FIELDS)


def resolve_agent_dir(name: str, *, user_id: str | None = None) -> Path:
    """Return the on-disk directory for an agent, preferring the per-user layout.

    Resolution order:
    1. ``{base_dir}/users/{user_id}/agents/{name}/`` (per-user, current layout).
    2. ``{base_dir}/agents/{name}/`` (legacy shared layout — read-only fallback).

    If neither exists, the per-user path is returned so callers that intend to
    create the agent write into the new layout.

    Args:
        name: Validated agent name.
        user_id: Owner of the agent. Defaults to the effective user from the
            request context (or ``"default"`` in no-auth mode).
    """
    paths = get_paths()
    effective_user = user_id or get_effective_user_id()
    user_path = paths.user_agent_dir(effective_user, name)
    # Require config.yaml to confirm this is a genuine agent directory,
    # not a leftover from memory/storage writes (see #3390).
    if user_path.exists() and (user_path / "config.yaml").exists():
        return user_path

    legacy_path = paths.agent_dir(name)
    if legacy_path.exists() and (legacy_path / "config.yaml").exists():
        return legacy_path

    return user_path


def load_agent_config(name: str | None, *, user_id: str | None = None) -> AgentConfig | None:
    """Load the custom or default agent's config.

    Dispatches to the configured agent store (``agent_storage.backend``): the
    ``file`` backend reads the per-user layout first and falls back to the legacy
    shared layout; the ``db`` backend reads the shared ``agents`` table. Behaviour
    and error semantics are unchanged from the historical file-only loader.

    Args:
        name: The agent name.
        user_id: Owner of the agent. Defaults to the effective user from the
            current request context.

    Returns:
        AgentConfig instance, or ``None`` if ``name`` is ``None``.

    Raises:
        FileNotFoundError: If the agent does not exist.
        ValueError: If the stored config cannot be parsed.
    """
    if name is None:
        return None
    # Lazy import: the store package imports back from this module.
    from deerflow.persistence.agents import get_agent_store

    return get_agent_store().get(name, user_id=user_id)


def load_agent_soul(agent_name: str | None, *, user_id: str | None = None) -> str | None:
    """Read the SOUL.md content for an agent, if any.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.
    The default agent (``agent_name`` falsy) always reads ``{base_dir}/SOUL.md``
    directly — it is not a custom-agent record — regardless of backend. A named
    agent dispatches to the configured store.

    Args:
        agent_name: The name of the agent or None for the default agent.
        user_id: Owner of the agent. Defaults to the effective user from the
            current request context.

    Returns:
        The SOUL.md content as a string, or None if not set.
    """
    if not agent_name:
        soul_path = get_paths().base_dir / SOUL_FILENAME
        if not soul_path.exists():
            return None
        content = soul_path.read_text(encoding="utf-8").strip()
        return content or None
    from deerflow.persistence.agents import get_agent_store

    return get_agent_store().get_soul(agent_name, user_id=user_id)


def list_custom_agents(*, user_id: str | None = None) -> list[AgentConfig]:
    """Return all valid custom agents for ``user_id``.

    Dispatches to the configured agent store. The ``file`` backend returns the
    union of the per-user layout and the legacy shared layout (per-user entries
    shadow legacy entries with the same name); the ``db`` backend returns the
    user's rows. Sorted by name.

    Args:
        user_id: Owner whose agents to list. Defaults to the effective user
            from the current request context.

    Returns:
        List of AgentConfig for each valid agent found.
    """
    from deerflow.persistence.agents import get_agent_store

    return get_agent_store().list(user_id=user_id)
