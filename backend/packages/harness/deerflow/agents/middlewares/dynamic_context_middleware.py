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
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, override

from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id

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
# Suffix the ID-swap gives the real user message; the reminder SystemMessage
# takes the original id so ``add_messages`` can replace it in place.
INJECTED_USER_MESSAGE_ID_SUFFIX = "__user"


def _format_current_date() -> str:
    return datetime.now().strftime("%Y-%m-%d, %A")


def _format_current_date_reminder(current_date: str) -> str:
    return "\n".join(
        [
            "<system-reminder>",
            f"<current_date>{current_date}</current_date>",
            "</system-reminder>",
        ]
    )


def strip_injected_user_message_id_suffix(message_id: str | None) -> str | None:
    """Return the id *message_id* had before the reminder ID-swap.

    Replaying a persisted user turn must feed the graph the id the client
    originally sent: a ``{id}__user`` message is skipped as an injection target,
    so replaying one into a state that has no reminder yet silently drops the
    date and memory block for that turn.
    """

    if isinstance(message_id, str) and message_id.endswith(INJECTED_USER_MESSAGE_ID_SUFFIX):
        return message_id[: -len(INJECTED_USER_MESSAGE_ID_SUFFIX)] or message_id
    return message_id


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
    async def abefore_agent(self, state, runtime: Runtime) -> dict:
        return self._inject()


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

    def __init__(self, agent_name: str | None = None, *, app_config: AppConfig | None = None):
        super().__init__()
        self._agent_name = agent_name
        self._app_config = app_config

    def _build_full_reminder(self, runtime: Runtime | None = None) -> tuple[str, str | None]:
        """Return (date_reminder, memory_block | None).

        Framework-owned data (date) is separated from user-owned data (memory)
        so the downstream SystemMessage carries only framework authority and
        memory stays at role:user — preventing untrusted content from gaining
        system privilege (OWASP LLM01).
        """
        from deerflow.agents.lead_agent.prompt import _get_memory_context

        injection_enabled = self._app_config.memory.injection_enabled if self._app_config else True
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
                return None
            date_reminder, memory_block = self._build_full_reminder(runtime)
            logger.info(
                "DynamicContextMiddleware: injecting full reminder (has_memory=%s) into last HumanMessage id=%r",
                memory_block is not None,
                messages[target_idx].id,
            )
            result_msgs = self._make_reminder_and_user_messages(messages[target_idx], date_reminder, memory_block, reminder_date=current_date)
            return {"messages": result_msgs}

        if last_date == current_date:
            # ── Same day: nothing to do ──────────────────────────────────────────
            return None

        # ── Midnight crossed: inject date-update reminder as a SystemMessage ──
        last_human_idx = next((i for i in reversed(range(len(messages))) if _is_user_injection_target(messages[i])), None)
        if last_human_idx is None:
            return None

        result_msgs = self._make_reminder_and_user_messages(messages[last_human_idx], self._build_date_update_reminder(), reminder_date=current_date)
        logger.info("DynamicContextMiddleware: midnight crossing detected — injected date update before current turn")
        return {"messages": result_msgs}

    @override
    def before_agent(self, state, runtime: Runtime) -> dict | None:
        result = self._inject(state, runtime)
        self._record_effective_memory(state, result, runtime)
        return result

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
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
                asyncio.to_thread(self._inject, state, runtime),
                timeout=_INJECT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "DynamicContextMiddleware: injection timed out (%.1fs); skipping new memory/date injection for this turn",
                _INJECT_TIMEOUT_SECONDS,
            )
            self._record_effective_memory(state, None, runtime)
            return None
        self._record_effective_memory(state, result, runtime)
        return result

    @staticmethod
    def _effective_memory_message(state, update: dict | None, runtime: Runtime) -> HumanMessage | None:
        """Find server-created memory that is effective for this run.

        A first-run block must come from this middleware's update. A reused
        block must have existed in the checkpoint before the run; the Gateway
        strips the reminder marker from untrusted input so a caller cannot
        replace a known checkpoint ID with forged provenance.
        """
        if isinstance(update, dict):
            update_messages = update.get("messages")
            if isinstance(update_messages, list):
                for message in update_messages:
                    if not isinstance(message, HumanMessage):
                        continue
                    message_id = str(message.id or "")
                    if message_id.endswith("__memory") and is_dynamic_context_reminder(message) and isinstance(message.content, str):
                        return message

        context = getattr(runtime, "context", None)
        raw_pre_existing_ids = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY) if isinstance(context, dict) else None
        if not isinstance(raw_pre_existing_ids, (frozenset, set, list, tuple)):
            return None
        pre_existing_ids = {str(message_id) for message_id in raw_pre_existing_ids if message_id}
        for message in state.get("messages", []):
            if not isinstance(message, HumanMessage):
                continue
            message_id = str(message.id or "")
            if message_id in pre_existing_ids and message_id.endswith("__memory") and is_dynamic_context_reminder(message) and isinstance(message.content, str):
                return message
        return None

    def _record_effective_memory(self, state, update: dict | None, runtime: Runtime) -> None:
        """Attach the effective hidden memory block to the current run ledger."""
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return

        message = self._effective_memory_message(state, update, runtime)
        if message is None:
            return

        try:
            journal.record_memory_context(
                content_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
            )
        except Exception:
            logger.debug("Failed to record effective memory context", exc_info=True)
