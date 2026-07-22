"""Run lifecycle service layer.

Centralizes the business logic for creating runs, formatting SSE
frames, and consuming stream bridge events.  Router modules
(``thread_runs``, ``runs``) are thin HTTP handlers that delegate here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import convert_to_messages
from langgraph.types import Command

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from app.gateway.deps import get_checkpointer, get_local_provider, get_run_context, get_run_manager, get_stream_bridge
from app.gateway.internal_auth import (
    INTERNAL_OWNER_USER_ID_HEADER_NAME,
    INTERNAL_SYSTEM_ROLE,
    get_internal_user,
    get_trusted_internal_owner_user_id,
)
from app.gateway.utils import sanitize_log_param
from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY, _REMINDER_DATE_KEY
from deerflow.agents.middlewares.view_image_middleware import _IMAGE_CONTEXT_MESSAGE_MARKER_KEY
from deerflow.config.app_config import get_app_config
from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    CheckpointStateAccessor,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    build_state_mutation_graph,
    run_agent,
)
from deerflow.runtime.checkpoint_mode import (
    INTERNAL_CHECKPOINT_MODE_KEY,
    CheckpointModeMismatchError,
    checkpoint_tuple_uses_delta,
    inject_checkpoint_mode,
)
from deerflow.runtime.checkpoint_state import graph_state_schema
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.runs.naming import resolve_root_run_name
from deerflow.runtime.secret_context import redact_config_secrets
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    RunStatus.success,
    RunStatus.error,
    RunStatus.timeout,
    RunStatus.interrupted,
}

_SERVER_OWNED_MESSAGE_METADATA_KEYS = frozenset(
    {
        _DYNAMIC_CONTEXT_REMINDER_KEY,
        _REMINDER_DATE_KEY,
        _IMAGE_CONTEXT_MESSAGE_MARKER_KEY,
    }
)


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Format a single SSE frame.

    Field order: ``event:`` -> ``data:`` -> ``id:`` (optional) -> blank line.
    This matches the LangGraph Platform wire format consumed by the
    ``useStream`` React hook and the Python ``langgraph-sdk`` SSE decoder.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def _run_is_terminal(record: RunRecord) -> bool:
    return record.status in _TERMINAL_RUN_STATUSES


async def _terminal_record_stream_missing(bridge: StreamBridge, record: RunRecord) -> bool:
    """True when a terminal run has no retained stream on bridges that can tell."""
    if not _run_is_terminal(record):
        return False
    stream_exists = getattr(bridge, "stream_exists", None)
    if stream_exists is None:
        return False
    try:
        return not bool(await stream_exists(record.run_id))
    except Exception:
        logger.debug(
            "Failed to probe stream existence for terminal run %s",
            sanitize_log_param(record.run_id),
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Input / config helpers
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize the stream_mode parameter to a list.

    Default matches what ``useStream`` expects: values + messages-tuple.
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def _strip_external_message_metadata(message: Any) -> Any:
    """Remove server-owned metadata from an untrusted input message."""
    if not isinstance(message, BaseMessage):
        return message
    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs.pop(ORIGINAL_USER_CONTENT_KEY, None)
    for key in _SERVER_OWNED_MESSAGE_METADATA_KEYS:
        additional_kwargs.pop(key, None)
    if additional_kwargs == message.additional_kwargs:
        return message
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def normalize_input(raw_input: dict[str, Any] | None, *, trusted_internal: bool = False) -> dict[str, Any]:
    """Convert LangGraph Platform input format to LangChain state dict.

    Delegates dict→message coercion to ``langchain_core.messages.utils.convert_to_messages``
    so that ``additional_kwargs`` (e.g. uploaded-file metadata — gh #3132), ``id``,
    ``name``, and non-human roles (ai/system/tool) survive unchanged.  An earlier
    hand-rolled version only forwarded ``content`` and collapsed every role to
    ``HumanMessage``, which silently stripped frontend-supplied attachments.

    Malformed message dicts (missing ``role``/``type``/``content``, unsupported
    role, etc.) raise ``HTTPException(400)`` with the offending index, instead
    of bubbling up as a 500.  The gateway is a system boundary, so per-entry
    validation errors are the right shape for clients to retry against.

    ``original_user_content``, dynamic-context reminder markers, and the
    transient view-image context marker are server-owned. External callers
    cannot supply them; trusted internal channel calls may preserve metadata
    they added before invoking this boundary.
    """
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted: list[Any] = []
        for index, msg in enumerate(messages):
            if isinstance(msg, BaseMessage):
                converted.append(msg)
            elif isinstance(msg, dict):
                try:
                    converted.extend(convert_to_messages([msg]))
                except (ValueError, TypeError, NotImplementedError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid message at input.messages[{index}]: {exc}",
                    ) from exc
            else:
                converted.append(msg)
        if not trusted_internal:
            converted = [_strip_external_message_metadata(message) for message in converted]
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = "lead_agent"


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
        "agent_name",
        "is_bootstrap",
    }
)

# Keys honored only for internally-authenticated callers (the scheduler path).
# ``non_interactive`` strips ``ask_clarification`` from the lead-agent toolset;
# arbitrary HTTP/IM clients must not be able to force autonomous execution.
_CONTEXT_INTERNAL_CALLER_KEYS: frozenset[str] = frozenset({"non_interactive"})

# Server-owned authorization identity fields. These must never be accepted from
# client-supplied ``body.config.context`` or ``body.config.configurable``. They
# are either produced by Gateway auth state or admitted from a separately
# authenticated internal request channel.
#   ``is_internal``       — derived from ``request.state.auth_source``
#   ``authz_attributes`` — Phase 1A has no Gateway-side producer; always cleared.
#   ``channel_user_id``  — accepted only from trusted internal ``body.context``.
_SERVER_OWNED_AUTHZ_CONTEXT_KEYS: frozenset[str] = frozenset({"is_internal", "authz_attributes", "channel_user_id"})

# Keys forwarded from ``body.context`` into ``config['context']`` ONLY (the
# runtime context that becomes ``ToolRuntime.context`` / ``runtime.context``),
# never into ``config['configurable']``. These are read by tools and
# middlewares from ``runtime.context`` and have no reason to live in
# ``configurable`` — and ``configurable`` is persisted in checkpoints, so
# keeping secrets like ``github_token`` out of it avoids writing a
# short-lived installation token into the checkpoint store.
#
#   ``github_token``         — App installation token minted by the GitHub
#                              channel; the bash tool exposes it as
#                              ``GH_TOKEN``/``GITHUB_TOKEN`` so ``gh`` and
#                              ``git`` push as the bot, not the host user.
#   ``disable_clarification`` — set for non-interactive channels (GitHub
#                              webhooks) so ClarificationMiddleware proceeds
#                              instead of dead-ending the run.
_CONTEXT_RUNTIME_ONLY_KEYS: frozenset[str] = frozenset({"github_token", "disable_clarification"})


def strip_internal_context_keys(config: dict[str, Any]) -> None:
    """Drop internal-only keys a non-internal caller smuggled into the run config.

    Gating :func:`merge_run_context_overrides` is not enough on its own:
    ``build_run_config`` copies a client-supplied ``body.config['context']`` /
    ``body.config['configurable']`` verbatim, so the same keys must be scrubbed
    from both sections after the config is assembled.
    """
    for section in ("context", "configurable"):
        value = config.get(section)
        if isinstance(value, dict):
            for key in _CONTEXT_INTERNAL_CALLER_KEYS:
                value.pop(key, None)


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None, *, internal: bool = False) -> None:
    """Merge whitelisted keys from ``body.context`` into both ``config['configurable']``
    and ``config['context']`` so they are visible to legacy configurable readers and
    to LangGraph ``ToolRuntime.context`` consumers (e.g. the ``setup_agent`` tool —
    see issue #2677).

    ``user_id`` is intentionally propagated into ``config['context']`` in addition to
    the whitelisted keys, so non-web callers (e.g. IM channels) that supply identity in
    ``body.context`` keep it on ``ToolRuntime.context``. It is merged with
    ``setdefault`` so a server-authenticated id stamped by
    :func:`inject_authenticated_user_context` always wins over the client-supplied one.

    :data:`_CONTEXT_INTERNAL_CALLER_KEYS` are also forwarded when ``internal``
    is True; for non-internal callers those keys are dropped from client requests
    by :func:`strip_internal_context_keys`.

    A second set of keys (``_CONTEXT_RUNTIME_ONLY_KEYS`` — e.g. ``github_token``,
    ``disable_clarification``) is forwarded into ``config['context']`` only, never
    ``configurable``. These are secrets / runtime flags read by tools and middlewares
    from ``runtime.context``; keeping them out of ``configurable`` avoids persisting a
    short-lived token in the checkpoint store.
    """
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    keys = _CONTEXT_CONFIGURABLE_KEYS | _CONTEXT_INTERNAL_CALLER_KEYS if internal else _CONTEXT_CONFIGURABLE_KEYS
    for key in keys:
        if key in context:
            if isinstance(configurable, dict):
                configurable.setdefault(key, context[key])
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, context[key])
    # Context-only keys (secrets / runtime flags) land in ``config['context']``
    # only — never ``configurable`` (which is persisted in checkpoints).
    for key in _CONTEXT_RUNTIME_ONLY_KEYS:
        if key in context and isinstance(runtime_context, dict):
            runtime_context.setdefault(key, context[key])
    if "user_id" in context and isinstance(runtime_context, dict):
        runtime_context.setdefault("user_id", context["user_id"])


async def resolve_trusted_internal_owner_for_attribution(request: Request, owner_user_id: str | None) -> Any | None:
    """Resolve the DeerFlow user used only for trusted internal attribution."""

    if not owner_user_id:
        return None
    user = getattr(request.state, "user", None)
    if getattr(user, "system_role", None) != INTERNAL_SYSTEM_ROLE:
        return None
    try:
        return await get_local_provider().get_user(owner_user_id)
    except Exception:
        logger.exception("Failed to resolve trusted internal owner %s", sanitize_log_param(owner_user_id))
        return None


def inject_authenticated_user_context(
    config: dict[str, Any],
    request: Request,
    *,
    internal_owner_user: Any | None = None,
    request_context: Mapping[str, Any] | None = None,
) -> None:
    """Stamp the authenticated user into the run context for background tools.

    Tool execution may happen after the request handler has returned, so tools
    that persist user-scoped files should not rely only on ambient ContextVars.
    The value comes from server-side auth state, never from client context.

    ``request_context.channel_user_id`` is the sole exception: it is honored
    only after ``request.state.auth_source`` proves the caller is internal.
    Values copied through the free-form RunnableConfig are always cleared.
    """

    # --- Server-owned authorization identity fields ---
    # Clear any client-forged values from both config sections, then write the
    # authoritative is_internal. This runs before ALL early returns so that
    # even user_id-is-None paths get a defined is_internal value.
    runtime_context = config.setdefault("context", {})
    if not isinstance(runtime_context, dict):
        raise TypeError("run context must be a mapping")
    for key in _SERVER_OWNED_AUTHZ_CONTEXT_KEYS:
        runtime_context.pop(key, None)
    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        for key in _SERVER_OWNED_AUTHZ_CONTEXT_KEYS:
            configurable.pop(key, None)
    auth_source = getattr(getattr(request, "state", None), "auth_source", None)
    runtime_context["is_internal"] = auth_source == AUTH_SOURCE_INTERNAL
    if auth_source == AUTH_SOURCE_INTERNAL and request_context is not None:
        channel_user_id = request_context.get("channel_user_id")
        if channel_user_id is not None:
            runtime_context["channel_user_id"] = channel_user_id

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        runtime_context = config.setdefault("context", {})
        if not isinstance(runtime_context, dict):
            return
        if internal_owner_user is None:
            runtime_context.pop("user_role", None)
            runtime_context.pop("oauth_provider", None)
            runtime_context.pop("oauth_id", None)
            return
        owner_user_id = getattr(internal_owner_user, "id", None)
        if owner_user_id is not None:
            runtime_context["user_id"] = str(owner_user_id)
        runtime_context["user_role"] = getattr(internal_owner_user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(internal_owner_user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(internal_owner_user, "oauth_id", None)
        return

    runtime_context = config.setdefault("context", {})
    if isinstance(runtime_context, dict):
        runtime_context["user_id"] = str(user_id)
        runtime_context["user_role"] = getattr(user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(user, "oauth_id", None)


def resolve_agent_factory(assistant_id: str | None):
    """Resolve the agent factory callable from config.

    Custom agents are implemented as ``lead_agent`` + an ``agent_name``
    injected into ``configurable`` or ``context`` — see
    :func:`build_run_config`.  All ``assistant_id`` values therefore map to the
    same factory; the routing happens inside ``make_lead_agent`` when it reads
    ``cfg["agent_name"]``.
    """
    from deerflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


# Lead-agent recursion budget bounds. The Gateway must NOT trust a
# client-supplied ``recursion_limit`` verbatim: an arbitrarily large value lets
# a single run execute unbounded LangGraph super-steps (each at least one LLM
# call), enabling runaway API cost / DoS. ``_DEFAULT_RECURSION_LIMIT`` is the
# server default when the client sends nothing; the hard ceiling any client
# value is clamped to is configurable via ``AppConfig.max_recursion_limit``.
_DEFAULT_RECURSION_LIMIT = 100
_DEFAULT_MAX_RECURSION_LIMIT = 1000


def _resolve_max_recursion_limit() -> int:
    """Resolve the clamp ceiling from ``AppConfig.max_recursion_limit``.

    Falls back to ``_DEFAULT_MAX_RECURSION_LIMIT`` when the app config cannot be
    loaded (e.g. no ``config.yaml`` in a bare unit-test environment) so that the
    clamp still applies rather than crashing the run-config assembly.
    """
    try:
        return get_app_config().max_recursion_limit
    except Exception:
        return _DEFAULT_MAX_RECURSION_LIMIT


def _clamp_recursion_limit(value: Any, max_limit: int) -> int:
    """Clamp a client-supplied ``recursion_limit`` into a safe server range.

    Non-integer values (including ``bool``, an ``int`` subclass) and non-positive
    values fall back to ``_DEFAULT_RECURSION_LIMIT``; valid positive integers are
    capped at ``max_limit`` (from ``AppConfig.max_recursion_limit``).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return _DEFAULT_RECURSION_LIMIT
    return min(value, max_limit)


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent.

    When *assistant_id* refers to a custom agent (anything other than
    ``"lead_agent"`` / ``None``), the name is forwarded as ``agent_name`` in
    both ``configurable`` and ``context`` so it is visible to legacy
    configurable readers and to LangGraph ``ToolRuntime.context`` consumers
    (e.g. the ``setup_agent`` tool, which since LangGraph >=1.1.9 no longer
    falls back from ``context`` to ``configurable``).  An explicit
    ``agent_name`` in either container takes precedence over the value
    derived from ``assistant_id``.  ``make_lead_agent`` reads this key to
    load the matching ``agents/<name>/SOUL.md`` and per-agent config —
    without it the agent silently runs as the default lead agent.

    This mirrors the channel manager's ``_resolve_run_params`` logic so that
    the LangGraph Platform-compatible HTTP API and the IM channel path behave
    identically.
    """
    # Lead-agent recursion budget (LangGraph super-steps for the lead graph
    # only). Independent of subagent depth: a `task()` dispatch runs the whole
    # subagent inside ONE lead tools-node step, and subagents enforce their own
    # limit via `subagents.max_turns`. Do not conflate this 100 with the
    # general-purpose subagent's max_turns.
    config: dict[str, Any] = {"recursion_limit": _DEFAULT_RECURSION_LIMIT}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list((request_config.get("configurable") or {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                # Strip caller-supplied ``__``-prefixed keys: those are the
                # harness's private run-context channels (skill secret-binding
                # sources, the active-secret set, the run journal). A caller must
                # not be able to seed them and forge internal state — e.g. a
                # forged ``__slash_skill_secret_source`` would otherwise bypass the
                # skill enabled/allowlist/declaration gates (#3938). Legitimate
                # caller keys (``secrets``, ``user_id``, model overrides) never use
                # the ``__`` prefix.
                context = {key: value for key, value in context_value.items() if not (isinstance(key, str) and key.startswith("__"))}
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            context["thread_id"] = thread_id
            config["context"] = context
            # The checkpointer always scopes state by configurable["thread_id"],
            # regardless of whether the caller drives the run via context (e.g.
            # request-scoped secrets, #3861). thread_id comes from the URL path,
            # not caller config, so mirror it here while keeping secret-bearing
            # context keys out of configurable.
            config["configurable"] = {"thread_id": thread_id}
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable") or {})
            configurable["thread_id"] = thread_id
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
        # Never trust a client-supplied recursion_limit verbatim: clamp it to a
        # safe server range so a single run cannot execute unbounded LangGraph
        # super-steps (runaway LLM cost / DoS). Applied after the passthrough so
        # it overrides whatever the client sent.
        if "recursion_limit" in request_config:
            max_limit = _resolve_max_recursion_limit()
            clamped = _clamp_recursion_limit(request_config["recursion_limit"], max_limit)
            if clamped != request_config["recursion_limit"]:
                logger.warning(
                    "build_run_config: clamped client recursion_limit %r -> %d (max %d). thread_id=%s",
                    request_config["recursion_limit"],
                    clamped,
                    max_limit,
                    thread_id,
                )
            config["recursion_limit"] = clamped
    else:
        config["configurable"] = {"thread_id": thread_id}

    # Inject custom agent name when the caller specified a non-default assistant.
    # Honour an explicit agent_name in either runtime options container.
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        normalized = assistant_id.strip().lower().replace("_", "-")
        if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError(f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization.")
        configurable = config.setdefault("configurable", {})
        runtime_context = config.setdefault("context", {})
        explicit_agent_name: str | None = None
        if isinstance(configurable, dict) and isinstance(configurable.get("agent_name"), str):
            explicit_agent_name = configurable["agent_name"]
        elif isinstance(runtime_context, dict) and isinstance(runtime_context.get("agent_name"), str):
            explicit_agent_name = runtime_context["agent_name"]
        effective_agent_name = explicit_agent_name or normalized
        if isinstance(configurable, dict):
            configurable["agent_name"] = effective_agent_name
        if isinstance(runtime_context, dict):
            runtime_context["agent_name"] = effective_agent_name
        config.setdefault("run_name", resolve_root_run_name(config, normalized))
    for section in ("configurable", "context"):
        external_values = config.get(section)
        if isinstance(external_values, dict):
            external_values.pop(INTERNAL_CHECKPOINT_MODE_KEY, None)

    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    return config


def build_checkpoint_state_mutation_accessor(
    request: Request,
    *,
    thread_id: str,
    as_node: str,
    checkpoint_id: str | None = None,
    state_schema: Any | None = None,
) -> tuple[CheckpointStateAccessor, dict[str, Any]]:
    """Build a state-only graph whose writer node finishes immediately.

    ``state_schema`` should be the thread's effective schema (from
    :func:`graph_state_schema` on the assistant graph) whenever the write
    carries materialized state; with the base-schema fallback, channels
    contributed by custom middleware are silently discarded.
    """
    mode = getattr(request.app.state, "checkpoint_channel_mode", "full")
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if checkpoint_id is not None:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    inject_checkpoint_mode(config, mode)

    graph = build_state_mutation_graph(as_node, mode, state_schema)
    accessor = CheckpointStateAccessor.bind(
        graph,
        get_checkpointer(request),
        store=getattr(request.app.state, "store", None),
        mode=mode,
    )
    return accessor, config


# Cache of factory-built accessor graphs. Accessor operations (aget_state /
# aupdate_state) never execute graph nodes or middleware, so per-request
# variations (user, model, skills) cannot affect materialization semantics;
# the compiled graph is stable per (assistant_id, mode, app_config). The
# factory and app_config identities are re-validated on every call so patched
# factories take effect immediately and a config.yaml hot-reload (which
# rebuilds the AppConfig object) never serves a stale compiled graph — the
# cached reference keeps the old config alive, so id-reuse cannot produce a
# false hit. Bounded: cleared when too many distinct assistants appear.
_STATE_ACCESSOR_GRAPH_CACHE_MAX = 64
_state_accessor_graph_cache: dict[tuple[str | None, str], tuple[Any, Any, Any]] = {}


def _state_accessor_graph(agent_factory: Any, assistant_id: str | None, mode: str, config: dict[str, Any]) -> Any:
    app_config = (config.get("context") or {}).get("app_config")
    key = (assistant_id, mode)
    cached = _state_accessor_graph_cache.get(key)
    if cached is not None and cached[0] is agent_factory and cached[1] is app_config:
        return cached[2]
    if len(_state_accessor_graph_cache) >= _STATE_ACCESSOR_GRAPH_CACHE_MAX:
        _state_accessor_graph_cache.clear()
    graph = agent_factory(config=config)
    _state_accessor_graph_cache[key] = (agent_factory, app_config, graph)
    return graph


class _RawCheckpointSnapshot:
    """StateSnapshot-shaped view over a raw checkpoint tuple (full mode only).

    ``next``/``tasks`` are not derivable without the compiled graph and
    degrade to empty; everything the read endpoints serialize (values,
    metadata, config ancestry, created_at) comes straight from the tuple.
    """

    __slots__ = ("config", "values", "metadata", "parent_config", "created_at", "tasks", "tasks_known", "next")

    def __init__(self, config: dict[str, Any], tup: Any | None) -> None:
        self.config = getattr(tup, "config", None) or config
        checkpoint = getattr(tup, "checkpoint", None) or {}
        self.values = dict(checkpoint.get("channel_values") or {})
        self.metadata = dict(getattr(tup, "metadata", None) or {})
        self.parent_config = getattr(tup, "parent_config", None)
        self.created_at = checkpoint.get("ts") or self.metadata.get("created_at", "")
        self.tasks: tuple = ()
        self.tasks_known = False
        self.next: tuple = ()


class _RawCheckpointReadAccessor:
    """Degraded full-mode read accessor for when the agent factory is down.

    Full-mode checkpoints persist complete ``channel_values``, so reads do not
    need the compiled graph. The fail-closed delta gate still applies: delta
    checkpoints are rejected with :class:`CheckpointModeMismatchError` instead
    of being served as partial state. Writes are unsupported — mutation paths
    keep using the graph-backed accessor.
    """

    def __init__(self, checkpointer: Any, mode: str) -> None:
        self.checkpointer = checkpointer
        self.mode = mode

    @staticmethod
    def _gate(tup: Any) -> None:
        if checkpoint_tuple_uses_delta(tup):
            raise CheckpointModeMismatchError("Thread requires delta mode; materialize and convert its checkpoints before using full mode.")

    async def aget(self, config: dict[str, Any]) -> _RawCheckpointSnapshot:
        tup = await self.checkpointer.aget_tuple(config)
        self._gate(tup)
        return _RawCheckpointSnapshot(config, tup)

    async def ahistory(self, config: dict[str, Any], *, limit: int | None = None) -> list[_RawCheckpointSnapshot]:
        if limit is not None and limit <= 0:
            return []
        result: list[_RawCheckpointSnapshot] = []
        before = None
        walk_config = config
        if config.get("configurable", {}).get("checkpoint_id"):
            # Pregel's get_state_history treats config.checkpoint_id as the
            # inclusive start of the walk, while alist(before=...) is
            # exclusive — fetch the anchor explicitly so the degraded path
            # matches the graph path.
            before = config
            walk_config = {
                **config,
                "configurable": {k: v for k, v in config.get("configurable", {}).items() if k != "checkpoint_id"},
            }
            anchor = await self.checkpointer.aget_tuple(before)
            self._gate(anchor)
            if anchor is not None:
                result.append(_RawCheckpointSnapshot(config, anchor))
        if limit is None or len(result) < limit:
            remaining = None if limit is None else limit - len(result)
            async for tup in self.checkpointer.alist(walk_config, before=before, limit=remaining):
                self._gate(tup)
                result.append(_RawCheckpointSnapshot(config, tup))
                if limit is not None and len(result) >= limit:
                    break
        return result


def build_checkpoint_state_accessor(
    request: Request,
    *,
    thread_id: str,
    assistant_id: str | None = None,
    checkpoint_id: str | None = None,
) -> tuple[CheckpointStateAccessor, dict[str, Any]]:
    """Build the mode-selected lead graph used for materialized checkpoint state."""
    ctx = get_run_context(request)
    config = build_run_config(thread_id, None, None, assistant_id=assistant_id)
    configurable = config.setdefault("configurable", {})
    configurable["checkpoint_ns"] = ""
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id

    if ctx.app_config is not None:
        config.setdefault("context", {})["app_config"] = ctx.app_config
    inject_checkpoint_mode(config, ctx.checkpoint_channel_mode)

    agent_factory = resolve_agent_factory(assistant_id)
    try:
        graph = _state_accessor_graph(agent_factory, assistant_id, ctx.checkpoint_channel_mode, config)
    except Exception:
        if ctx.checkpoint_channel_mode != "full":
            # Delta materialization needs the graph's channel table; there is
            # no degraded path. Surface the factory failure as-is.
            raise
        # Full-mode checkpoints carry complete channel_values: degrade to raw
        # checkpointer reads so state endpoints survive a broken agent factory
        # (bad model config, MCP server down, misconfigured skill).
        logger.warning(
            "Agent factory unavailable for thread %s; falling back to raw checkpointer reads",
            thread_id,
            exc_info=True,
        )
        return _RawCheckpointReadAccessor(ctx.checkpointer, ctx.checkpoint_channel_mode), config
    accessor = CheckpointStateAccessor.bind(
        graph,
        ctx.checkpointer,
        store=ctx.store,
        mode=ctx.checkpoint_channel_mode,
    )
    return accessor, config


async def resolve_thread_assistant_id(
    request: Request,
    thread_id: str,
    *,
    fail_closed: bool = False,
) -> str | None:
    """Return the assistant_id recorded in thread metadata, or ``None``.

    Missing records degrade to ``None`` (the default lead agent). Store
    failures do the same for read callers, while mutation callers set
    ``fail_closed`` so they cannot compile a write graph with the wrong schema.
    """
    from app.gateway.deps import get_thread_store

    try:
        thread_store = get_thread_store(request)
        record = await thread_store.get(thread_id)
    except Exception:
        logger.warning("Failed to resolve assistant_id for thread %s", thread_id, exc_info=True)
        if fail_closed:
            raise
        return None
    return record.get("assistant_id") if isinstance(record, dict) else None


async def build_thread_checkpoint_state_accessor(
    request: Request,
    *,
    thread_id: str,
    checkpoint_id: str | None = None,
    fail_closed: bool = False,
) -> tuple[CheckpointStateAccessor, dict[str, Any]]:
    """Single resolution boundary for state endpoints.

    Thread metadata -> assistant_id -> effective assistant graph. Materializing
    with the default lead schema would drop channels contributed by a custom
    ``AgentMiddleware.state_schema`` from the response.
    """
    assistant_id = await resolve_thread_assistant_id(request, thread_id, fail_closed=fail_closed)
    return build_checkpoint_state_accessor(
        request,
        thread_id=thread_id,
        assistant_id=assistant_id,
        checkpoint_id=checkpoint_id,
    )


async def build_thread_checkpoint_state_mutation_accessor(
    request: Request,
    *,
    thread_id: str,
    as_node: str,
    checkpoint_id: str | None = None,
) -> tuple[CheckpointStateAccessor, dict[str, Any]]:
    """Mutation accessor compiled with the thread's effective state schema.

    Derives the schema through :func:`build_thread_checkpoint_state_accessor`
    so writes carrying materialized state do not silently discard
    extension-owned channels.
    """
    read_accessor, _read_config = await build_thread_checkpoint_state_accessor(
        request,
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        fail_closed=True,
    )
    state_schema = graph_state_schema(getattr(read_accessor, "graph", None))
    return build_checkpoint_state_mutation_accessor(
        request,
        thread_id=thread_id,
        as_node=as_node,
        checkpoint_id=checkpoint_id,
        state_schema=state_schema,
    )


async def apply_checkpoint_to_run_config(
    config: dict[str, Any],
    *,
    body: Any,
    thread_id: str,
    request: Request,
) -> None:
    """Validate an optional run checkpoint and attach it to RunnableConfig."""
    checkpoint = getattr(body, "checkpoint", None)
    checkpoint_id = getattr(body, "checkpoint_id", None)
    checkpoint_ns = ""
    checkpoint_map = None

    if checkpoint:
        if not isinstance(checkpoint, Mapping):
            raise HTTPException(status_code=400, detail="checkpoint must be an object")
        checkpoint_thread_id = checkpoint.get("thread_id")
        if checkpoint_thread_id is not None and str(checkpoint_thread_id) != thread_id:
            raise HTTPException(status_code=400, detail="checkpoint thread_id does not match request thread_id")
        raw_checkpoint_id = checkpoint.get("checkpoint_id")
        if raw_checkpoint_id:
            checkpoint_id = str(raw_checkpoint_id)
        raw_checkpoint_ns = checkpoint.get("checkpoint_ns")
        if raw_checkpoint_ns is not None:
            checkpoint_ns = str(raw_checkpoint_ns)
        checkpoint_map = checkpoint.get("checkpoint_map")

    if not checkpoint_id:
        return

    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": str(checkpoint_id),
        }
    }
    if checkpoint_map is not None:
        read_config["configurable"]["checkpoint_map"] = checkpoint_map

    checkpointer = get_checkpointer(request)
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception as exc:
        logger.exception("Failed to validate checkpoint %s for thread %s", checkpoint_id, sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to validate checkpoint") from exc
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Checkpoint {checkpoint_id} not found")

    configurable = config.setdefault("configurable", {})
    if not isinstance(configurable, dict):
        raise HTTPException(status_code=400, detail="request config configurable must be an object")
    configurable["thread_id"] = thread_id
    configurable["checkpoint_ns"] = checkpoint_ns
    configurable["checkpoint_id"] = str(checkpoint_id)
    if checkpoint_map is not None:
        configurable["checkpoint_map"] = checkpoint_map


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """Create a RunRecord and launch the background agent task.

    Parameters
    ----------
    body : RunCreateRequest
        The validated request body (typed as Any to avoid circular import
        with the router module that defines the Pydantic model).
    thread_id : str
        Target thread.
    request : Request
        FastAPI request — used to retrieve singletons from ``app.state``.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # Coerce non-string model_name values to str before truncation.
    if model_name is not None and not isinstance(model_name, str):
        model_name = str(model_name)

    # Validate model against the allowlist when a model_name is provided.
    if model_name:
        app_config = get_app_config()
        resolved = app_config.get_model_config(model_name)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_name!r} is not in the configured model allowlist",
            )

    owner_user_id = get_trusted_internal_owner_user_id(request)
    # Stateless run endpoints carry thread_id in the request *body*, so the
    # @require_permission(owner_check=True) decorator -- which resolves ownership
    # from the path param -- cannot protect them. Enforce thread ownership here,
    # before any run is created, so one user cannot start runs on (or read /wait
    # checkpoint state from) another user's thread. Missing rows (auto-created
    # temp threads) and NULL-owner rows (shared / pre-auth data) stay accessible
    # via check_access; only a thread already owned by another user is rejected
    # with 404, matching thread_runs.py's anti-enumeration behaviour. Internal
    # channel runs act on behalf of the connection owner carried in
    # X-DeerFlow-Owner-User-Id, so they are scoped to that owner instead of
    # bypassing the check -- a leaked internal token must not grant cross-user
    # thread access.
    user = getattr(request.state, "user", None)
    if user is not None:
        allowed = await run_ctx.thread_store.check_access(thread_id, str(user.id))
        if not allowed and owner_user_id and getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
            # Channel workers may also act for the connection owner named in
            # the trusted header (e.g. claiming a legacy default-owned channel
            # thread for its real owner).
            allowed = await run_ctx.thread_store.check_access(thread_id, owner_user_id)
        if not allowed:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    owner_context_token = set_current_user(SimpleNamespace(id=owner_user_id)) if owner_user_id else None
    try:
        try:
            async with goal_thread_lock(thread_id):
                record = await run_mgr.create_or_reject(
                    thread_id,
                    body.assistant_id,
                    on_disconnect=disconnect,
                    metadata=body.metadata or {},
                    # Persist a secret-redacted copy of the config: the run record is
                    # written to runs.kwargs_json and echoed by the run API, so a
                    # request-scoped secret (#3861) must not ride along. The live
                    # config built below keeps the secrets for the actual run.
                    kwargs={"input": body.input, "config": redact_config_secrets(body.config)},
                    multitask_strategy=body.multitask_strategy,
                    model_name=model_name,
                    user_id=owner_user_id,
                )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnsupportedStrategyError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        # Upsert thread metadata so the thread appears in /threads/search,
        # even for threads that were never explicitly created via POST /threads
        # (e.g. stateless runs).
        try:
            existing = await run_ctx.thread_store.get(thread_id)
            if existing is None and owner_user_id:
                unscoped_existing = await run_ctx.thread_store.get(thread_id, user_id=None)
                if unscoped_existing is not None:
                    if unscoped_existing.get("user_id") != owner_user_id:
                        await run_ctx.thread_store.update_owner(thread_id, owner_user_id, user_id=None)
                    existing = await run_ctx.thread_store.get(thread_id)
            if existing is None:
                await run_ctx.thread_store.create(
                    thread_id,
                    assistant_id=body.assistant_id,
                    metadata=body.metadata,
                )
            else:
                await run_ctx.thread_store.update_status(thread_id, "running")
        except Exception:
            logger.warning("Failed to upsert thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

        agent_factory = resolve_agent_factory(body.assistant_id)
        is_internal_caller = getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL
        command = getattr(body, "command", None)
        if command and command.get("resume") is not None:
            graph_input = Command(resume=command["resume"])
        else:
            graph_input = normalize_input(body.input, trusted_internal=is_internal_caller)
        config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)
        await apply_checkpoint_to_run_config(config, body=body, thread_id=thread_id, request=request)

        # Merge DeerFlow-specific context overrides into both ``configurable`` and ``context``.
        # The ``context`` field is a custom extension for the langgraph-compat layer
        # that carries agent configuration (model_name, thinking_enabled, etc.).
        # Only agent-relevant keys are forwarded; unknown keys (e.g. thread_id) are ignored.
        merge_run_context_overrides(config, getattr(body, "context", None), internal=is_internal_caller)
        if not is_internal_caller:
            # ``body.config`` is free-form and copied verbatim by
            # ``build_run_config``; scrub internal-only keys smuggled there.
            strip_internal_context_keys(config)
        internal_owner_user = await resolve_trusted_internal_owner_for_attribution(request, owner_user_id)
        inject_authenticated_user_context(
            config,
            request,
            internal_owner_user=internal_owner_user,
            request_context=getattr(body, "context", None),
        )

        stream_modes = normalize_stream_modes(body.stream_mode)

        task = asyncio.create_task(
            run_agent(
                bridge,
                run_mgr,
                record,
                ctx=run_ctx,
                agent_factory=agent_factory,
                graph_input=graph_input,
                config=config,
                stream_modes=stream_modes,
                stream_subgraphs=body.stream_subgraphs,
                interrupt_before=body.interrupt_before,
                interrupt_after=body.interrupt_after,
            )
        )
        record.task = task

        # Title sync is handled by worker.py's finally block which reads the
        # title from the checkpoint and calls thread_store.update_display_name
        # after the run completes.

        return record
    finally:
        if owner_context_token is not None:
            reset_current_user(owner_context_token)


async def launch_scheduled_thread_run(
    *,
    thread_id: str,
    assistant_id: str | None,
    prompt: str,
    request: Request | None = None,
    app: Any | None = None,
    owner_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if request is None:
        if app is None:
            raise ValueError("launch_scheduled_thread_run requires request or app")
        request = SimpleNamespace(
            app=app,
            headers=({INTERNAL_OWNER_USER_ID_HEADER_NAME: owner_user_id} if owner_user_id else {}),
            state=SimpleNamespace(
                user=get_internal_user(),
                auth_source=AUTH_SOURCE_INTERNAL,
            ),
            cookies={},
        )
    # SimpleNamespace stands in for the Pydantic run-request body that the
    # HTTP path parses. If start_run gains a new body.* attribute that it reads
    # directly, add the matching field here so the scheduler path stays in sync.
    body = SimpleNamespace(
        assistant_id=assistant_id,
        input={"messages": [{"role": "user", "content": prompt}]},
        command=None,
        metadata=metadata or {},
        config=None,
        # ``user_id`` mirrors what IM channels put in ``body.context`` so
        # runtime-context consumers without a ContextVar fallback (e.g.
        # user-scoped GuardrailMiddleware providers) see the owning user;
        # ``inject_authenticated_user_context`` skips the internal user.
        context=({"non_interactive": True, "user_id": owner_user_id} if owner_user_id else {"non_interactive": True}),
        webhook=None,
        checkpoint_id=None,
        checkpoint=None,
        interrupt_before=None,
        interrupt_after=None,
        stream_mode=None,
        stream_subgraphs=False,
        stream_resumable=None,
        on_disconnect="continue",
        on_completion="keep",
        multitask_strategy="reject",
        after_seconds=None,
        if_not_exists="reject",
        feedback_keys=None,
    )
    record = await start_run(body, thread_id, request)
    return {"run_id": record.run_id, "thread_id": record.thread_id}


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """Async generator that yields SSE frames from the bridge.

    The ``finally`` block implements ``on_disconnect`` semantics:
    - ``cancel``: abort the background task on client disconnect.
    - ``continue``: let the task run; events are discarded.
    """
    last_event_id = request.headers.get("Last-Event-ID")
    if await _terminal_record_stream_missing(bridge, record):
        yield format_sse("end", None)
        return

    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                if await _terminal_record_stream_missing(bridge, record):
                    yield format_sse("end", None)
                    return
                yield ": heartbeat\n\n"
                continue

            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        # store_only records are cross-worker runs hydrated from the RunStore; this
        # worker holds no in-memory task/abort state for them, so run_mgr.cancel()
        # cannot stop the task (it would 409). Skip on_disconnect cancellation for
        # those and only act on runs this worker actually owns.
        if not record.store_only and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)


async def wait_for_run_completion(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
) -> bool:
    """Block until the run publishes ``END_SENTINEL``, honouring on_disconnect.

    The non-streaming ``/wait`` endpoints used to ``await record.task``
    directly with no disconnect handling.  When the client (or an
    intermediate HTTP proxy) timed out during a long tool call such as
    ``pip install``, the handler would swallow ``CancelledError`` and
    serialize whatever checkpoint happened to exist — masking a half-finished
    run as a normal completion (issue #3265).

    This helper consumes the same bridge that ``sse_consumer`` does so the
    wait path shares its disconnect semantics: each wake-up polls
    ``request.is_disconnected()``; on a real disconnect it cancels the
    background run when ``record.on_disconnect`` is ``cancel``.  The bridge's
    heartbeat sentinels guarantee at least one wake-up per
    ``heartbeat_interval`` even when the agent emits no events for a while.

    Returns:
        ``True`` when ``END_SENTINEL`` was observed (run reached a terminal
        state), ``False`` when the loop exited because the client
        disconnected.  Callers must skip checkpoint serialization on
        ``False`` so a partial checkpoint is not returned as a normal
        response.
    """
    completed = False
    if await _terminal_record_stream_missing(bridge, record):
        return True

    try:
        async for entry in bridge.subscribe(record.run_id):
            # END_SENTINEL means the run reached a terminal state; honour it
            # even if the client just disconnected so the caller still serializes
            # the real final checkpoint.
            if entry is END_SENTINEL:
                completed = True
                return True
            if entry is HEARTBEAT_SENTINEL and await _terminal_record_stream_missing(bridge, record):
                completed = True
                return True
            if await request.is_disconnected():
                break
            # Heartbeats and regular events: keep waiting for END_SENTINEL.
        return completed
    finally:
        if not completed and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)
