"""Middleware to inject dynamic context (memory, current date) as a system-reminder.

The system prompt is kept fully static for maximum prefix-cache reuse across users
and sessions.  The current date is always injected.  Per-user memory is also injected
when ``memory.injection_enabled`` is True in the app config.  Both are delivered once
per conversation as a dedicated <system-reminder> SystemMessage inserted before the
first user message (frozen-snapshot pattern).

When a conversation spans midnight the middleware detects the date change and injects
a lightweight date-update reminder as a separate SystemMessage before the current turn.
This correction is persisted so subsequent turns on the new day see a consistent history
and do not re-inject.

Reminder format:

    <system-reminder>
    <memory>...</memory>

    <current_date>2026-05-08, Friday</current_date>
    </system-reminder>

Date-update format:

    <system-reminder>
    <current_date>2026-05-09, Saturday</current_date>
    </system-reminder>

By default the injected date follows the server's local timezone. Set the
``DEER_FLOW_DATE_TIMEZONE`` environment variable to an IANA timezone name (for
example ``Asia/Shanghai``) when the host clock runs UTC but the conversation
date should follow another zone. Invalid values log a warning and fall back to
the server-local timezone.

The knob is deliberately an environment variable rather than a config field:
it is read directly by both date-context middlewares at injection time, so an
operator can point a container at another zone without mounting a config.yaml,
and the lead and built-in-subagent paths can never drift apart on which zone
they render.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import posixpath
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING, override
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.runtime import Runtime

from deerflow.projects.context import build_project_context_message, is_project_context_message, pinned_project_snapshot, project_context_insertion_index, render_documents_block, render_project_block
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.utils.messages import INJECTED_USER_MESSAGE_ID_SUFFIX, strip_injected_user_message_id_suffix

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

# Upper bound (seconds) for a single _inject() offload.  If the warm-up at
# gateway startup failed silently, the first request may still hit a cold
# tiktoken BPE download that blocks until the OS TCP timeout (~26 min).
# This cap ensures the request degrades gracefully instead of hanging.
_INJECT_TIMEOUT_SECONDS = 5.0

_DATE_RE = re.compile(r"<current_date>([^<]+)</current_date>")
_DYNAMIC_CONTEXT_REMINDER_KEY = "dynamic_context_reminder"
# Authoritative injected date, carried in additional_kwargs of the date
# SystemMessage. Detection reads this instead of regex-parsing message content,
# so it is never exposed to user-influenceable memory content.
_REMINDER_DATE_KEY = "reminder_date"
_SUMMARY_MESSAGE_NAME = "summary"

# ``INJECTED_USER_MESSAGE_ID_SUFFIX`` / ``strip_injected_user_message_id_suffix``
# are defined in ``deerflow.utils.messages`` and re-exported here, where the
# ID-swap they describe actually happens. Existing importers keep working.
__all__ = [
    "INJECTED_USER_MESSAGE_ID_SUFFIX",
    "DynamicContextMiddleware",
    "SubagentDateContextMiddleware",
    "is_dynamic_context_reminder",
    "strip_injected_user_message_id_suffix",
]


_DATE_TIMEZONE_ENV = "DEER_FLOW_DATE_TIMEZONE"


def _date_timezone() -> tzinfo | None:
    """Resolve the configured IANA timezone for injected dates, or None for server-local."""
    raw = os.environ.get(_DATE_TIMEZONE_ENV, "").strip()
    if not raw:
        return None
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # Only configuration-shaped failures degrade to server-local. A
        # BlockingError-style guard (blocking-I/O regression suite) or any
        # unrelated exception must propagate instead of being misread as an
        # invalid timezone name.
        logger.warning("Invalid %s=%r; falling back to the server-local timezone", _DATE_TIMEZONE_ENV, raw)
        return None


def _server_local_timezone_name() -> str | None:
    """IANA key of the server's local zone, or ``None`` when not resolvable.

    ``datetime.now().astimezone().tzinfo`` is always a plain fixed-offset
    ``datetime.timezone`` (an abbreviation such as ``CST`` is ambiguous and
    DST-churns), never a ``zoneinfo.ZoneInfo`` carrying an IANA key. The key is
    instead read from the platform: the ``TZ`` environment variable when it
    names a real zone, or the ``/etc/localtime`` symlink target on
    Linux/macOS. Only the symlink's *direct* target is read (``os.readlink``),
    not a fully resolved path: on macOS ``/etc/localtime`` points into
    ``/var/db/timezone/zoneinfo/`` whose own directory symlink resolves to a
    versioned path (``.../tz/<version>/zoneinfo/...``) that would defeat any
    fixed prefix list. The zone key is whatever follows the last ``/zoneinfo/``
    segment. Hosts with no symlink (Windows, stripped containers) return
    ``None``.
    """
    tz_env = os.environ.get("TZ", "").strip()
    if tz_env:
        try:
            return ZoneInfo(tz_env).key
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    if not target.startswith("/"):
        target = posixpath.normpath(posixpath.join("/etc", target))
    zoneinfo_marker = "/zoneinfo/"
    marker_index = target.rfind(zoneinfo_marker)
    if marker_index == -1:
        return None
    key = target[marker_index + len(zoneinfo_marker) :]
    if not key or key.startswith("/") or ".." in key:
        return None
    return key


def _server_local_utc_offset_minutes() -> int:
    """Current UTC offset of the server's local zone, in minutes."""
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def _effective_date_timezone_name() -> str:
    """Stable label of the timezone the injected date actually follows.

    A configured, valid ``DEER_FLOW_DATE_TIMEZONE`` is reported by its IANA
    key; without one, the server-local zone is reported by its resolved IANA
    key when the platform exposes it. When no IANA key is recoverable the
    declaration falls back to a ``server-local(±HH:MM)`` sentinel carrying the
    current UTC offset - never a bare abbreviation, which would be ambiguous
    (``CST`` is shared by China, US Central, and Cuba) and would churn across
    DST. Declaring the effective zone (never a bare ``probed``) lets the
    assembly descriptor tell deployments that anchor the injected date
    differently apart.
    """
    tz = _date_timezone()
    if tz is not None:
        key = getattr(tz, "key", None)
        if isinstance(key, str) and key:
            return key
        return "UTC"
    local_key = _server_local_timezone_name()
    if local_key is not None:
        return local_key
    offset_minutes = _server_local_utc_offset_minutes()
    sign = "+" if offset_minutes >= 0 else "-"
    offset_minutes = abs(offset_minutes)
    return f"server-local({sign}{offset_minutes // 60:02d}:{offset_minutes % 60:02d})"


def _format_current_date() -> str:
    tz = _date_timezone()
    now = datetime.now(tz) if tz is not None else datetime.now()
    return now.strftime("%Y-%m-%d, %A")


def _format_current_date_reminder(current_date: str) -> str:
    return "\n".join(
        [
            "<system-reminder>",
            f"<current_date>{current_date}</current_date>",
            "</system-reminder>",
        ]
    )


def _extract_date(content: str) -> str | None:
    """Return the first <current_date> value found in *content*, or None."""
    m = _DATE_RE.search(content)
    return m.group(1) if m else None


def is_dynamic_context_reminder(message: object) -> bool:
    """Return whether *message* is a hidden dynamic-context reminder."""
    # DEPRECATED: HumanMessage reminders only exist in pre-PR checkpoints.
    # Once all active checkpoints are migrated, the HumanMessage branch can be
    # removed and this function can check SystemMessage exclusively.
    return isinstance(message, (HumanMessage, SystemMessage)) and bool(message.additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY))


def _last_injected_date(messages: list) -> str | None:
    """Scan messages in reverse and return the most recently injected date.

    Detection uses the ``dynamic_context_reminder`` additional_kwargs flag rather
    than content substring matching, so user messages containing ``<system-reminder>``
    are not mistakenly treated as injected reminders.

    The authoritative date is the ``reminder_date`` value in additional_kwargs of
    the date SystemMessage. Reminders without it (the separate ``<memory>``
    HumanMessage, or any future dateless reminder) carry no date and are skipped,
    so they cannot shadow the real date reminder.
    """
    for msg in reversed(messages):
        if not is_dynamic_context_reminder(msg):
            continue
        structured = msg.additional_kwargs.get(_REMINDER_DATE_KEY)
        if isinstance(structured, str) and structured:
            return structured
        # Backward-compat for checkpoints written before reminder_date existed:
        # the date lived in content. Scope the regex to SystemMessage so it never
        # runs on the user-influenceable memory HumanMessage (preserves the OWASP
        # role separation from #3630 and closes the memory date-spoofing hole).
        if isinstance(msg, SystemMessage):
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            date = _extract_date(content_str)
            if date is not None:
                return date
    return None


def _is_user_injection_target(message: object) -> bool:
    """Return whether *message* can receive a dynamic-context reminder."""
    if not isinstance(message, HumanMessage):
        return False
    if is_dynamic_context_reminder(message):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    # Prevent recursive ID-swap: a message whose ID ends with "__user" was
    # produced by a prior _make_reminder_and_user_messages call and must not
    # be processed again — doing so causes unbounded suffix growth
    # (id__user__user__user...) and ghost-message re-execution.
    # Using endswith (not substring "in") avoids false positives on IDs that
    # happen to contain "__user" in the middle.
    if message.id and str(message.id).endswith(INJECTED_USER_MESSAGE_ID_SUFFIX):
        return False
    return True


class SubagentDateContextMiddleware(AgentMiddleware):
    """Inject hidden current-date context once per built-in subagent execution.

    Built-in subagents need the same temporal anchor as the lead agent, but not
    its user-memory lookup, frozen-conversation ID swap, or midnight refresh
    lifecycle. Each subagent graph is one-shot and starts from fresh state, so a
    single ``before_agent`` update makes the date available before its first
    model call without coupling the two runtime paths.
    """

    def release_policy_parameters(self) -> dict[str, object]:
        """The injected date's effective timezone is this middleware's behaviour identity."""
        return {"current_date_timezone": _effective_date_timezone_name()}

    @staticmethod
    def _inject() -> dict:
        current_date = _format_current_date()
        reminder = _format_current_date_reminder(current_date)
        return {
            "messages": [
                SystemMessage(
                    content=reminder,
                    additional_kwargs={
                        "hide_from_ui": True,
                        _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        _REMINDER_DATE_KEY: current_date,
                    },
                )
            ]
        }

    @override
    def before_agent(self, state, runtime: Runtime) -> dict:
        return self._inject()

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
        # _inject() can resolve DEER_FLOW_DATE_TIMEZONE through ZoneInfo,
        # which reads the OS zone database (or the tzdata wheel) on a cold
        # cache. SubagentDateContextMiddleware runs on the async subagent path,
        # where no assembly observer necessarily warmed that resolution first,
        # so the injection is offloaded like DynamicContextMiddleware does (see
        # #3402) to keep filesystem work off the event loop.
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._inject),
                timeout=_INJECT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "SubagentDateContextMiddleware: date injection timed out (%.1fs); skipping for this run",
                _INJECT_TIMEOUT_SECONDS,
            )
            return None


class DynamicContextMiddleware(AgentMiddleware):
    """Inject memory and current date as a SystemMessage <system-reminder>.

    First turn
    ----------
    Prepends a full system-reminder (memory + date) to the first HumanMessage and
    persists it (same message ID).  The first message is then frozen for the whole
    session — its content never changes again, so the prefix cache can hit on every
    subsequent turn.

    Fallback (missed earlier injection)
    -----------------------------------
    If an earlier turn ended without any reminder (e.g. the async ``abefore_agent``
    degraded path skipped injection on a timeout), the first-injection branch runs
    on a history that already holds several turns.  The reminder then attaches to
    the **last** user message instead: the ID-swap's ``{id}__user`` copy is
    appended by ``add_messages``, so attaching to an earlier message would move
    that stale prompt ahead of the current question and the model would answer
    the old prompt as the current turn.

    Midnight crossing
    -----------------
    If the conversation spans midnight, the current date differs from the date that
    was injected earlier.  In that case a lightweight date-update reminder is prepended
    to the **current** (last) HumanMessage and persisted.  Subsequent turns on the new
    day see the corrected date in history and skip re-injection.
    """

    def __init__(
        self,
        agent_name: str | None = None,
        *,
        app_config: AppConfig | None = None,
        memory_enabled: bool = True,
    ):
        super().__init__()
        self._agent_name = agent_name
        self._app_config = app_config
        self._memory_enabled = memory_enabled
        # Message ID of the ``__memory`` block this instance injected during
        # the current run's ``before_agent`` (assembly is per run). The
        # request-time journal selection trusts a non-checkpointed ``__memory``
        # message only when it carries this ID — a flagged memory message that
        # is neither checkpoint-proven nor self-produced cannot forge the
        # run's recorded memory identity.
        self._injected_memory_message_id: str | None = None

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare memory/date behavior and the shelf index's rendering caps.

        ``memory_enabled`` gates the memory half of the injected context;
        ``shelf_index_max_entries`` / ``shelf_index_max_bytes`` change the
        model-visible ``<documents>`` block this middleware renders. All three
        are model-visible policy, so the effective (post-config-resolution)
        values are part of the assembly identity — runs under different
        policies must not share a fingerprint.
        """
        max_entries, max_bytes = self._shelf_index_limits()
        return {
            "current_date_timezone": _effective_date_timezone_name(),
            "memory_enabled": self._memory_enabled,
            "shelf_index_max_entries": max_entries,
            "shelf_index_max_bytes": max_bytes,
        }

    def _build_full_reminder(self, runtime: Runtime | None = None) -> tuple[str, str | None]:
        """Return (date_reminder, memory_block | None).

        Framework-owned data (date) is separated from user-owned data (memory)
        so the downstream SystemMessage carries only framework authority and
        memory stays at role:user — preventing untrusted content from gaining
        system privilege (OWASP LLM01).
        """
        from deerflow.agents.lead_agent.prompt import _get_memory_context

        injection_enabled = self._memory_enabled and (self._app_config.memory.injection_enabled if self._app_config else True)
        memory_context = (
            _get_memory_context(
                self._agent_name,
                app_config=self._app_config,
                user_id=resolve_runtime_user_id(runtime),
            )
            if injection_enabled
            else ""
        )
        current_date = _format_current_date()
        date_reminder = _format_current_date_reminder(current_date)

        memory_block = memory_context.strip() if memory_context else None

        return date_reminder, memory_block

    def _build_date_update_reminder(self) -> str:
        return _format_current_date_reminder(_format_current_date())

    def _disabled_memory_removals(self, messages: list) -> list[RemoveMessage]:
        """Remove only frozen memory messages owned by this middleware."""
        if self._memory_enabled:
            return []

        removals: list[RemoveMessage] = []
        for message in messages:
            message_id = str(message.id or "")
            if isinstance(message, HumanMessage) and message_id.endswith("__memory") and is_dynamic_context_reminder(message):
                removals.append(RemoveMessage(id=message_id))
        return removals

    def _read_failures_are_fatal(self, *, allow_io: bool = True) -> bool | None:
        from deerflow.agents.memory import memory_read_failures_are_fatal
        from deerflow.config.memory_config import get_memory_config

        if not self._memory_enabled:
            return False
        if self._app_config is None and not allow_io:
            return None  # get_memory_config() may reload config.yaml from disk.
        try:
            memory_config = self._app_config.memory if self._app_config else get_memory_config()
            if not memory_config.enabled or not memory_config.injection_enabled:
                return False
            return memory_read_failures_are_fatal(
                memory_config.manager_class,
                memory_config.backend_config,
                resolved_only=not allow_io,
            )
        except Exception:
            logger.exception("DynamicContextMiddleware: could not resolve memory read failure policy; treating the injection timeout as fatal")
            return True

    @staticmethod
    def _make_reminder_and_user_messages(
        original: HumanMessage,
        reminder_content: str,
        memory_content: str | None = None,
        *,
        reminder_date: str | None = None,
    ) -> list[SystemMessage | HumanMessage]:
        """Return messages using the ID-swap technique.

        SystemMessage carries framework-owned data (date, metadata) — takes
        the original ID so add_messages replaces it in-place.  *reminder_date*
        is recorded in its additional_kwargs as the authoritative injected date
        (``_last_injected_date`` reads it instead of parsing content).  Optional
        HumanMessage carries user-owned memory content with ``{id}__memory``.
        The actual user message gets ``{id}__user``.

        SystemMessage is used — system context must not masquerade as user
        input (#3630).  Memory is deliberately kept as HumanMessage so
        user-influenceable content does not gain system authority (OWASP LLM01)
        — and it deliberately never carries ``reminder_date``.
        """
        stable_id = original.id or str(uuid.uuid4())
        messages: list[SystemMessage | HumanMessage] = []

        reminder_kwargs = {
            "hide_from_ui": True,
            _DYNAMIC_CONTEXT_REMINDER_KEY: True,
            **provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, "dynamic_context"),
        }
        if reminder_date is not None:
            reminder_kwargs[_REMINDER_DATE_KEY] = reminder_date
        messages.append(
            SystemMessage(
                content=reminder_content,
                id=stable_id,
                additional_kwargs=reminder_kwargs,
            )
        )

        if memory_content:
            messages.append(
                HumanMessage(
                    content=memory_content,
                    id=f"{stable_id}__memory",
                    additional_kwargs={
                        "hide_from_ui": True,
                        _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        **provenance_kwargs(ContentKind.MEMORY, "dynamic_context_memory"),
                    },
                )
            )

        messages.append(
            HumanMessage(
                content=original.content,
                id=f"{stable_id}{INJECTED_USER_MESSAGE_ID_SUFFIX}",
                name=original.name,
                additional_kwargs=original.additional_kwargs,
            )
        )
        return messages

    def _inject(self, state, runtime: Runtime | None = None) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None
        memory_removals = self._disabled_memory_removals(messages)

        current_date = _format_current_date()
        last_date = _last_injected_date(messages)
        logger.debug(
            "DynamicContextMiddleware._inject: msg_count=%d last_date=%r current_date=%r",
            len(messages),
            last_date,
            current_date,
        )

        if last_date is None:
            # ── First turn: inject full reminder as a SystemMessage ─────
            #
            # Scan from the end so the reminder attaches to the LAST user
            # injection target.  Normally that is also the only message.  But
            # when an earlier turn ended without any reminder — e.g. the async
            # ``abefore_agent`` degraded path skipped injection on a timeout —
            # history already holds multiple turns and the ID-swap's
            # ``{id}__user`` copy is APPENDED by ``add_messages``; choosing an
            # earlier message here would move the old first user prompt to the
            # tail, ahead of the latest question, and the model would answer
            # the stale first message as if it were the current turn.
            target_idx = next((i for i in reversed(range(len(messages))) if _is_user_injection_target(messages[i])), None)
            if target_idx is None:
                return {"messages": memory_removals} if memory_removals else None
            date_reminder, memory_block = self._build_full_reminder(runtime)
            logger.info(
                "DynamicContextMiddleware: injecting full reminder (has_memory=%s) into last HumanMessage id=%r",
                memory_block is not None,
                messages[target_idx].id,
            )
            result_msgs = self._make_reminder_and_user_messages(messages[target_idx], date_reminder, memory_block, reminder_date=current_date)
            return {"messages": [*memory_removals, *result_msgs]}

        if last_date == current_date:
            # ── Same day: nothing to do ──────────────────────────────────────────
            return {"messages": memory_removals} if memory_removals else None

        # ── Midnight crossed: inject date-update reminder as a SystemMessage ──
        last_human_idx = next((i for i in reversed(range(len(messages))) if _is_user_injection_target(messages[i])), None)
        if last_human_idx is None:
            return {"messages": memory_removals} if memory_removals else None

        result_msgs = self._make_reminder_and_user_messages(messages[last_human_idx], self._build_date_update_reminder(), reminder_date=current_date)
        logger.info("DynamicContextMiddleware: midnight crossing detected — injected date update before current turn")
        return {"messages": [*memory_removals, *result_msgs]}

    @override
    def before_agent(self, state, runtime: Runtime) -> dict | None:
        result = self._inject(state, runtime)
        self._track_injected_memory_message(result)
        return result

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
        # The opt-out cleanup is an in-memory ownership check and must not be
        # coupled to the time-boxed date/memory injection worker. Even if that
        # worker times out, stale recalled memory must be gone before the next
        # model call.
        memory_removals = self._disabled_memory_removals(list(state.get("messages", [])))
        # The warm path uses only this call's config and already-loaded class.
        # Cold discovery/config reload shares the injection's bounded worker,
        # never a second executor job after the timeout. Keep this value local:
        # a late worker must not overwrite another run's timeout policy.
        read_failures_are_fatal = self._read_failures_are_fatal(allow_io=False)

        def inject_with_policy():
            nonlocal read_failures_are_fatal
            if read_failures_are_fatal is None:
                read_failures_are_fatal = self._read_failures_are_fatal()
            return self._inject(state, runtime)

        # _inject() performs synchronous file I/O (memory JSON loading) and
        # potentially blocking network calls (tiktoken encoding download on
        # first use).  Offload to a thread so the event loop is never blocked
        # — a blocking call here starves all concurrent HTTP handlers (auth,
        # SSE heartbeats, etc.).  See issue #3402.
        #
        # Bounded timeout: if startup warm-up failed silently (e.g. network
        # blip during deploy), the first request's cold tiktoken download can
        # block for tens of minutes (OS TCP timeout).  Time-box injection so
        # the request degrades gracefully (no new dynamic-context update)
        # rather than hanging. Frozen context already in state remains active.
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(inject_with_policy),
                timeout=_INJECT_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            from deerflow.agents.memory import MemoryReadError

            # A worker that never started (or is still resolving policy) leaves
            # the policy unknown. Fail closed without waiting for that worker.
            if read_failures_are_fatal is not False:
                raise MemoryReadError("Required memory context retrieval timed out") from exc
            logger.warning(
                "DynamicContextMiddleware: injection timed out (%.1fs); skipping new memory/date injection for this turn",
                _INJECT_TIMEOUT_SECONDS,
            )
            return {"messages": memory_removals} if memory_removals else None
        self._track_injected_memory_message(result)
        return result

    def _track_injected_memory_message(self, update: dict | None) -> None:
        """Remember the ``__memory`` message ID this run's injection produced.

        The journal event is emitted at model-request assembly time, where the
        injection's update dict is no longer available; the ID is the proof
        that a non-checkpointed ``__memory`` message in the request came from
        this middleware rather than from untrusted input.
        """
        if not isinstance(update, dict):
            return
        update_messages = update.get("messages")
        if not isinstance(update_messages, list):
            return
        for message in update_messages:
            if not isinstance(message, HumanMessage):
                continue
            message_id = str(message.id or "")
            if message_id.endswith("__memory") and is_dynamic_context_reminder(message):
                self._injected_memory_message_id = message_id
                return

    def _effective_memory_message_for_request(self, messages: list, runtime: Runtime | None) -> HumanMessage | None:
        """Find server-created memory that is effective for this run.

        A first-run block must carry the ID this middleware injected during
        ``before_agent``. A reused block must have existed in the checkpoint
        before the run; the Gateway strips the reminder marker from untrusted
        input so a caller cannot replace a known checkpoint ID with forged
        provenance. With memory disabled (``memory_enabled=False``) no block
        is ever effective: the opt-out removes this middleware's frozen
        memory messages, and the run must not record a memory identity for
        one (upstream's ``_record_effective_memory`` gate, preserved here).
        """
        if not self._memory_enabled:
            return None
        context = getattr(runtime, "context", None)
        raw_pre_existing_ids = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY) if isinstance(context, dict) else None
        pre_existing_ids = {str(message_id) for message_id in raw_pre_existing_ids if message_id} if isinstance(raw_pre_existing_ids, (frozenset, set, list, tuple)) else set()
        for message in messages:
            if not isinstance(message, HumanMessage):
                continue
            message_id = str(message.id or "")
            if not message_id.endswith("__memory") or not is_dynamic_context_reminder(message) or not isinstance(message.content, str):
                continue
            if message_id in pre_existing_ids or message_id == self._injected_memory_message_id:
                return message
        return None

    def _shelf_index_limits(self) -> tuple[int, int]:
        """Shelf index caps without I/O: the assembly config, else defaults."""
        if self._app_config is not None:
            projects = self._app_config.projects
            return projects.shelf_index_max_entries, projects.shelf_index_max_bytes
        from deerflow.config.projects_config import ProjectsConfig

        defaults = ProjectsConfig()
        return defaults.shelf_index_max_entries, defaults.shelf_index_max_bytes

    def _assemble_project_request(self, request: ModelRequest) -> tuple[ModelRequest, str | None, str | None]:
        """Insert at most one transient ``<project>`` message into the request.

        Pure rendering over the admission-pinned snapshot (no I/O): this
        injector's own recognized transient messages are removed from the
        request copy first, so re-assembling an already decorated request
        stays idempotent and instructions never accumulate across calls. The
        message carries the ``<project>`` block plus, for a nonempty shelf,
        the bounded ``<documents>`` index appended after ``</project>`` — both
        rendered fresh from the pinned snapshot on every model call (§7.2).
        The message is placed immediately before the genuine current-run user
        message and is never returned as a state update, so checkpoints and
        ``state["messages"]`` never contain it. Returns the rendered block
        texts (``None`` when absent) for the audit fingerprints.
        """
        runtime = getattr(request, "runtime", None)
        original = list(getattr(request, "messages", None) or [])
        messages = [message for message in original if not is_project_context_message(message)]
        snapshot = pinned_project_snapshot(runtime)
        project_block = render_project_block(snapshot)
        if project_block is None:
            if len(messages) == len(original):
                return request, None, None
            return request.override(messages=messages), None, None
        max_entries, max_bytes = self._shelf_index_limits()
        documents_block = render_documents_block(snapshot, max_entries=max_entries, max_bytes=max_bytes)
        block = project_block if documents_block is None else f"{project_block}\n{documents_block}"
        index = project_context_insertion_index(messages, runtime)
        run_id = None
        context = getattr(runtime, "context", None)
        if isinstance(context, dict) and isinstance(context.get("run_id"), str):
            run_id = context["run_id"]
        message = build_project_context_message(block, run_id)
        return request.override(messages=[*messages[:index], message, *messages[index:]]), project_block, documents_block

    def _record_context_event(self, messages: list, runtime: Runtime | None, project_block: str | None, documents_block: str | None) -> None:
        """Emit the run's single ``context:memory`` audit event, when due.

        Fires once per run (the journal dedupes) at the first successful
        model-request assembly, whenever a memory block, the project block or
        the shelf index was actually supplied. ``content_sha256`` covers only
        the selected persisted ``__memory`` message (``None`` when none exists
        — e.g. a project-only run); ``project_context_revision`` /
        ``project_shelf_revision`` are the sha256 fingerprints of the rendered
        ``<project>`` / ``<documents>`` text (``None`` when no such block was
        delivered). All are audit fingerprints: never compared, never stored
        in additional_kwargs, and unable to reconstruct the underlying text.
        Runs supplying no such context keep the historical no-event behavior.
        """
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return

        message = self._effective_memory_message_for_request(messages, runtime)
        content_sha256 = hashlib.sha256(message.content.encode("utf-8")).hexdigest() if message is not None else None
        project_context_revision = hashlib.sha256(project_block.encode("utf-8")).hexdigest() if project_block is not None else None
        project_shelf_revision = hashlib.sha256(documents_block.encode("utf-8")).hexdigest() if documents_block is not None else None
        if content_sha256 is None and project_context_revision is None and project_shelf_revision is None:
            return

        try:
            journal.record_memory_context(
                content_sha256=content_sha256,
                project_context_revision=project_context_revision,
                project_shelf_revision=project_shelf_revision,
            )
        except Exception:
            logger.debug("Failed to record effective memory context", exc_info=True)

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        request, project_block, documents_block = self._assemble_project_request(request)
        response = handler(request)
        # Record only after the call succeeded: a failed assembly must not
        # claim the context was delivered.
        self._record_context_event(request.messages, getattr(request, "runtime", None), project_block, documents_block)
        return response

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        # Pure in-memory rendering: no I/O, so it stays on the event loop.
        request, project_block, documents_block = self._assemble_project_request(request)
        response = await handler(request)
        self._record_context_event(request.messages, getattr(request, "runtime", None), project_block, documents_block)
        return response
