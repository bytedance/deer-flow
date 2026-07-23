"""update_agent tool — let a custom agent persist updates to its own SOUL.md / config.

Bound to the lead agent only when ``runtime.context['agent_name']`` is set
(i.e. inside an existing custom agent's chat). The default agent does not see
this tool, and the bootstrap flow continues to use ``setup_agent`` for the
initial creation handshake.

The tool writes back through the configured agent store (file: per-user
``config.yaml``/``SOUL.md``; db: the shared ``agents`` table) so an agent created
by one user is never visible to (or mutable by) another.

Cross-field write atomicity depends on the backend: the ``db`` store commits
config and soul in a single transaction, so a partial failure never leaves one
updated and the other stale. The ``file`` store stages both to temp files and
commits them with two sequential ``os.replace`` calls (see
``FileAgentStore._write``): each file is all-or-nothing, but a crash *between*
the two replaces can leave a freshly-written config.yaml beside a stale SOUL.md
(single-node, sub-millisecond window). The pre-store tool reported that partial
window explicitly ("Partial update for agent 'X': ..."); routing through the
store drops the *reporting* (a mid-replace crash now surfaces as the generic
"Failed to update agent"). That is an intentional tradeoff — the stage-then-
replace *safety* is preserved (no corruption, no leftover temp files), only the
diagnostic is gone. If cross-file atomicity ever matters on ``file``, restore
that reporting in ``FileAgentStore._write``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from pydantic import BaseModel, BeforeValidator

from deerflow.config.agents_config import load_agent_config, preserve_non_managed_fields, validate_agent_name
from deerflow.config.app_config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.persistence.agents import get_agent_store
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

_NULLISH_STRINGS = frozenset({"null", "none", "undefined"})

# Channels whose inbound messages come from untrusted external commenters
# (anyone on a GitHub repo, etc.). The lead-agent factory already drops
# this tool for runs on these channels (see ``_WEBHOOK_CHANNELS`` in
# ``deerflow.agents.lead_agent.agent``); this set is the in-tool mirror
# so a custom factory that re-attaches ``update_agent`` cannot silently
# expose self-mutation over a webhook.
_UNTRUSTED_CHANNELS: frozenset[str] = frozenset({"github"})

_MODEL_BEHAVIOR_FIELDS: tuple[str, ...] = (
    "model_settings",
    "thinking_enabled",
    "reasoning_effort",
)


def _is_nullish_string(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in _NULLISH_STRINGS


def _normalize_nullish_string(value: object) -> object:
    return None if _is_nullish_string(value) else value


OptionalText = Annotated[str | None, BeforeValidator(_normalize_nullish_string)]
OptionalStringList = Annotated[list[str] | None, BeforeValidator(_normalize_nullish_string)]


@tool(parse_docstring=True)
def update_agent(
    runtime: Runtime,
    soul: OptionalText = None,
    description: OptionalText = None,
    skills: OptionalStringList = None,
    tool_groups: OptionalStringList = None,
    model: OptionalText = None,
) -> Command:
    """Persist updates to the current custom agent's SOUL.md and config.yaml.

    Use this when the user asks to refine the agent's identity, description,
    skill whitelist, tool-group whitelist, or default model. Only the fields
    you explicitly pass are updated; omitted fields keep their existing values.

    Pass ``soul`` as the FULL replacement SOUL.md content — there is no patch
    semantics, so always start from the current SOUL and apply your edits.

    Pass ``skills=[]`` to disable all skills for this agent. Omit ``skills``
    entirely to keep the existing whitelist. Do not pass literal strings like
    ``"null"`` / ``"none"`` / ``"undefined"`` for unchanged fields; omit those
    fields instead.

    Args:
        soul: Optional full replacement SOUL.md content.
        description: Optional new one-line description.
        skills: Optional skill whitelist. ``[]`` = no skills, omit = unchanged.
        tool_groups: Optional tool-group whitelist. ``[]`` = empty, omit = unchanged.
        model: Optional model override (must match a configured model name).

    Returns:
        Command with a ToolMessage describing the result. Changes take effect
        on the next user turn (when the lead agent is rebuilt with the fresh
        SOUL.md and config.yaml).
    """
    tool_call_id = runtime.tool_call_id
    agent_name_raw: str | None = runtime.context.get("agent_name") if runtime.context else None
    channel_name: str | None = runtime.context.get("channel_name") if runtime.context else None

    def _err(message: str) -> Command:
        return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id, status="error")]})

    # Defence in depth — the lead-agent factory already withholds this
    # tool from webhook-channel runs (see ``_WEBHOOK_CHANNELS`` in
    # ``deerflow.agents.lead_agent.agent``). The same channel set is
    # mirrored here so a future code path that re-attaches the tool
    # without going through ``_make_lead_agent`` (custom factories,
    # tests, etc.) does not silently accept untrusted self-mutation
    # requests routed from a webhook.
    if channel_name in _UNTRUSTED_CHANNELS:
        return _err(f"update_agent is disabled on the {channel_name!r} channel. Self-mutation requests must come from an operator-trusted surface (chat UI or the HTTP API), not a webhook fan-out.")

    if soul is None and description is None and skills is None and tool_groups is None and model is None:
        return _err('No fields provided. Pass at least one of: soul, description, skills, tool_groups, model. Omit unchanged fields instead of passing null-like strings such as "null", "none", or "undefined".')

    # Reject empty / whitespace-only soul before touching the filesystem.
    # setup_agent already refuses this (#3553 / #3549); update_agent must too,
    # otherwise a custom agent can report success while wiping a working
    # SOUL.md and leaving the next turn with an empty personality.
    if soul is not None and not soul.strip():
        return _err("soul content is empty; refusing to update agent with an empty SOUL.md. Omit the soul field if you do not want to change it.")

    try:
        agent_name = validate_agent_name(agent_name_raw)
    except ValueError as e:
        return _err(str(e))

    if not agent_name:
        return _err("update_agent is only available inside a custom agent's chat. There is no agent_name in the current runtime context, so there is nothing to update. If you are inside the bootstrap flow, use setup_agent instead.")

    # Resolve the active user so that updates only affect this user's agent.
    # ``resolve_runtime_user_id`` prefers ``runtime.context["user_id"]`` (set by
    # the gateway from the auth-validated request) and falls back to the
    # contextvar, then DEFAULT_USER_ID. This matches setup_agent so a user
    # creating an agent and later refining it always touches the same files,
    # even if the contextvar gets lost across an async/thread boundary
    # (issue #2782 / #2862 class of bugs).
    user_id = resolve_runtime_user_id(runtime)

    # Reject an unknown ``model`` *before* touching the filesystem. Otherwise
    # ``_resolve_model_name`` silently falls back to the default at runtime
    # and the user sees confusing repeated warnings on every later turn.
    if model is not None and get_app_config().get_model_config(model) is None:
        return _err(f"Unknown model '{model}'. Pass a model name that exists in config.yaml's models section.")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, agent_name)
    legacy_dir = paths.agent_dir(agent_name)
    # Require config.yaml, not bare directory existence — a per-user agent
    # directory can exist containing only memory.json (written the first
    # time this user chats with a legacy shared agent, before update_agent
    # is ever called). Bare .exists() would miss that case and let this
    # fall through to load_agent_config, which correctly resolves through
    # to the legacy shared config via resolve_agent_dir, silently forking
    # a brand-new config.yaml/SOUL.md into the memory-only directory
    # instead of blocking (mirrors resolve_agent_dir's guard, see #3390).
    if not (agent_dir / "config.yaml").exists() and (legacy_dir / "config.yaml").exists():
        return _err(f"Agent '{agent_name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating.")

    try:
        existing_cfg = load_agent_config(agent_name, user_id=user_id)
    except FileNotFoundError:
        return _err(f"Agent '{agent_name}' does not exist for the current user. Use setup_agent to create a new agent first.")
    except ValueError as e:
        return _err(f"Agent '{agent_name}' has an unreadable config: {e}")

    if existing_cfg is None:
        return _err(f"Agent '{agent_name}' could not be loaded.")

    updated_fields: list[str] = []

    # Force the on-disk ``name`` to match the directory we are writing into,
    # even if ``existing_cfg.name`` had drifted (e.g. from manual yaml edits).
    config_data: dict[str, Any] = {"name": agent_name}
    new_description = description if description is not None else existing_cfg.description
    config_data["description"] = new_description
    if description is not None and description != existing_cfg.description:
        updated_fields.append("description")

    new_model = model if model is not None else existing_cfg.model
    if new_model is not None:
        config_data["model"] = new_model
    if model is not None and model != existing_cfg.model:
        updated_fields.append("model")

    new_tool_groups = tool_groups if tool_groups is not None else existing_cfg.tool_groups
    if new_tool_groups is not None:
        config_data["tool_groups"] = new_tool_groups
    if tool_groups is not None and tool_groups != existing_cfg.tool_groups:
        updated_fields.append("tool_groups")

    new_skills = skills if skills is not None else existing_cfg.skills
    if new_skills is not None:
        config_data["skills"] = new_skills
    if skills is not None and skills != existing_cfg.skills:
        updated_fields.append("skills")

    # This tool intentionally does not expose the #4336 model-behavior fields
    # as LLM-callable arguments yet, but it still rewrites config.yaml when any
    # of its supported fields changes. Carry those values forward explicitly so
    # an agent refining its description/model/skills cannot erase UI/API-owned
    # defaults such as temperature or reasoning effort.
    for key in _MODEL_BEHAVIOR_FIELDS:
        value = getattr(existing_cfg, key, None)
        if value is None:
            continue
        if isinstance(value, BaseModel):
            dumped = value.model_dump(exclude_none=True)
            if dumped:
                config_data[key] = dumped
        else:
            config_data[key] = value

    # Preserve every top-level AgentConfig field that this tool does not
    # expose as an argument (currently ``github:``, plus any future field
    # added to :class:`AgentConfig`). The same helper is used by the HTTP
    # ``PATCH /api/agents/{name}`` route so the two surfaces stay in lockstep.
    # Without this, operators who hand-author a ``github:`` block on a custom
    # agent would silently lose it the next time the agent self-updates via
    # ``update_agent``.
    preserved = preserve_non_managed_fields(existing_cfg)
    for key, value in preserved.items():
        config_data.setdefault(key, value)

    config_changed = bool({"description", "model", "tool_groups", "skills"} & set(updated_fields))
    if soul is not None:
        updated_fields.append("soul")

    # Persist config (when a managed field changed) and/or soul through the
    # store. The db backend commits both in one transaction; the file backend
    # commits each atomically but sequentially (see this module's docstring).
    # Nothing to write if the provided values all matched the existing config
    # and no soul was supplied.
    if config_changed or soul is not None:
        try:
            get_agent_store().update(agent_name, config_data if config_changed else None, soul, user_id=user_id)
        except Exception as e:
            logger.error("[update_agent] Failed to update agent '%s' (user=%s): %s", agent_name, user_id, e, exc_info=True)
            return _err(f"Failed to update agent '{agent_name}': {e}")

    if not updated_fields:
        return Command(update={"messages": [ToolMessage(content=f"No changes applied to agent '{agent_name}'. The provided values matched the existing config.", tool_call_id=tool_call_id)]})

    logger.info("[update_agent] Updated agent '%s' (user=%s) fields: %s", agent_name, user_id, updated_fields)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(f"Agent '{agent_name}' updated successfully. Changed: {', '.join(updated_fields)}. The new configuration takes effect on the next user turn."),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
