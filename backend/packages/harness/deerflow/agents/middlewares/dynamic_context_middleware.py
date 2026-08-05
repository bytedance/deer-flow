"""Middleware to inject dynamic context (memory, current date) as a system-reminder.

The system prompt is kept fully static for maximum prefix-cache reuse across users
and sessions. The current date is always injected. When ``memory.injection_enabled``
is true, session-refresh backends reuse one checkpointed memory reminder, while
turn-refresh backends retrieve against the latest real user request and add an
ephemeral reminder only to that model call. The latter is kept out of checkpoints
and capture input.

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
import threading
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import copy_context
from datetime import datetime
from typing import TYPE_CHECKING, Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.secret_context import DYNAMIC_MEMORY_CONTEXT_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.utils.messages import get_original_user_content_text, is_real_user_message

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
_TURN_MEMORY_MESSAGE_NAME = "dynamic_memory_context"
_TURN_MEMORY_MARKER_KEY = "dynamic_memory_context"
# Suffix the ID-swap gives the real user message; the reminder SystemMessage
# takes the original id so ``add_messages`` can replace it in place.
INJECTED_USER_MESSAGE_ID_SUFFIX = "__user"


def _run_sync_with_timeout(callback: Callable[[], str], timeout: float) -> str:
    """Run blocking context retrieval with the sync hook's wall-clock budget.

    Python cannot forcibly cancel a blocking HTTP call. This mirrors the async
    ``to_thread`` + ``wait_for`` contract: the model call continues after the
    budget while the daemon worker is allowed to finish in the background.
    OpenViking's own HTTP timeout still bounds that abandoned worker.
    """

    result: Future[str] = Future()
    context = copy_context()

    def invoke() -> None:
        try:
            result.set_result(context.run(callback))
        except BaseException as exc:
            result.set_exception(exc)

    threading.Thread(
        target=invoke,
        name="deerflow-memory-context-loader",
        daemon=True,
    ).start()
    try:
        return result.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise TimeoutError from exc


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


class DynamicContextMiddleware(AgentMiddleware):
    """Inject the current date and backend-selected memory context.

    First turn
    ----------
    Prepends the date and, for ``context_refresh_policy="session"`` backends, a
    memory snapshot to the first HumanMessage and persists that state. The first
    message is then frozen for the session so the prefix cache can hit.

    Query-aware memory
    ------------------
    A ``context_refresh_policy="turn"`` backend retrieves from the latest real
    user request in the model-call hook. Its hidden HumanMessage is added only to
    that request, cached in redacted run context for tool-loop calls, and never
    persisted into graph state.

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

    def _memory_config(self):
        if self._app_config is not None:
            return self._app_config.memory
        from deerflow.config.memory_config import get_memory_config

        return get_memory_config()

    def _read_failure_is_closed(self) -> bool:
        backend_config = getattr(self._memory_config(), "backend_config", {})
        if not isinstance(backend_config, dict):
            return False
        failure_policy = backend_config.get("failure_policy", {})
        return isinstance(failure_policy, dict) and str(failure_policy.get("read", "")).strip().lower() == "fail_closed"

    def _raise_on_closed_read_timeout(self, exc: TimeoutError) -> None:
        if not self._read_failure_is_closed():
            return
        from deerflow.agents.memory import MemoryManagerError

        raise MemoryManagerError(f"Query-aware memory retrieval exceeded the {_INJECT_TIMEOUT_SECONDS:.1f}s model-call budget") from exc

    def _memory_context_refresh_policy(self) -> str | None:
        """Resolve the active memory policy without turning optional recall into downtime."""

        memory_config = self._memory_config()
        if not memory_config.enabled or not memory_config.injection_enabled:
            return None

        from deerflow.agents.memory import (
            MemoryAuthorizationError,
            MemoryManagerError,
            get_memory_manager,
        )

        try:
            return get_memory_manager().context_refresh_policy
        except MemoryAuthorizationError:
            # Identity-boundary failures are never availability failures.
            raise
        except Exception as exc:
            logger.exception("Failed to initialize the memory manager for context injection")
            if self._read_failure_is_closed():
                if isinstance(exc, MemoryManagerError):
                    raise
                raise MemoryManagerError("Memory manager could not be initialized for context injection") from exc
            return None

    async def _amemory_context_refresh_policy(self) -> str | None:
        """Async counterpart that keeps backend construction off the event loop."""

        return await asyncio.to_thread(self._memory_context_refresh_policy)

    def _build_full_reminder(self, runtime: Runtime | None = None) -> tuple[str, str | None]:
        """Return (date_reminder, memory_block | None).

        Framework-owned data (date) is separated from user-owned data (memory)
        so the downstream SystemMessage carries only framework authority and
        memory stays at role:user — preventing untrusted content from gaining
        system privilege (OWASP LLM01).
        """
        from deerflow.agents.lead_agent.prompt import _get_memory_context

        uses_session_snapshot = self._memory_context_refresh_policy() == "session"
        memory_context = (
            _get_memory_context(
                self._agent_name,
                app_config=self._app_config,
                user_id=resolve_runtime_user_id(runtime),
            )
            if uses_session_snapshot
            else ""
        )
        current_date = datetime.now().strftime("%Y-%m-%d, %A")

        date_reminder = "\n".join(
            [
                "<system-reminder>",
                f"<current_date>{current_date}</current_date>",
                "</system-reminder>",
            ]
        )

        memory_block = memory_context.strip() if memory_context else None

        return date_reminder, memory_block

    def _build_date_update_reminder(self) -> str:
        current_date = datetime.now().strftime("%Y-%m-%d, %A")
        return "\n".join(
            [
                "<system-reminder>",
                f"<current_date>{current_date}</current_date>",
                "</system-reminder>",
            ]
        )

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

        reminder_kwargs: dict[str, Any] = {
            "hide_from_ui": True,
            _DYNAMIC_CONTEXT_REMINDER_KEY: True,
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
                    additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
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

        current_date = datetime.now().strftime("%Y-%m-%d, %A")
        last_date = _last_injected_date(messages)
        logger.debug(
            "DynamicContextMiddleware._inject: msg_count=%d last_date=%r current_date=%r",
            len(messages),
            last_date,
            current_date,
        )

        if last_date is None:
            # ── First turn: inject full reminder as a SystemMessage ─────
            first_idx = next((i for i, m in enumerate(messages) if _is_user_injection_target(m)), None)
            if first_idx is None:
                return None
            date_reminder, memory_block = self._build_full_reminder(runtime)
            logger.info(
                "DynamicContextMiddleware: injecting full reminder (has_memory=%s) into first HumanMessage id=%r",
                memory_block is not None,
                messages[first_idx].id,
            )
            result_msgs = self._make_reminder_and_user_messages(messages[first_idx], date_reminder, memory_block, reminder_date=current_date)
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
    def _latest_user_message(messages: list[Any]) -> HumanMessage | None:
        return next(
            (message for message in reversed(messages) if is_real_user_message(message)),
            None,
        )

    @staticmethod
    def _run_context(request: ModelRequest) -> dict[str, Any] | None:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        return context if isinstance(context, dict) else None

    @staticmethod
    def _thread_id(request: ModelRequest) -> str | None:
        context = DynamicContextMiddleware._run_context(request)
        if context is not None and context.get("thread_id"):
            return str(context["thread_id"])
        state = getattr(request, "state", None)
        if isinstance(state, dict) and state.get("thread_id"):
            return str(state["thread_id"])
        return None

    @staticmethod
    def _turn_cache_key(message: HumanMessage, query: str) -> str:
        query_digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        if message.id:
            return f"{message.id}:{query_digest}"
        return f"sha256:{query_digest}"

    def _turn_context_plan(
        self,
        request: ModelRequest,
    ) -> tuple[HumanMessage, str, str, dict[str, Any] | None] | None:
        config = self._memory_config()
        if not config.enabled or not config.injection_enabled:
            return None

        target = self._latest_user_message(list(request.messages))
        if target is None:
            return None
        query = get_original_user_content_text(target.content, target.additional_kwargs).strip()
        if not query:
            return None
        return target, query, self._turn_cache_key(target, query), self._run_context(request)

    @staticmethod
    def _cached_turn_context(
        run_context: dict[str, Any] | None,
        cache_key: str,
    ) -> tuple[bool, str]:
        if run_context is None:
            return False, ""
        cached = run_context.get(DYNAMIC_MEMORY_CONTEXT_KEY)
        if not isinstance(cached, dict) or cached.get("key") != cache_key:
            return False, ""
        content = cached.get("content")
        return True, content if isinstance(content, str) else ""

    @staticmethod
    def _store_turn_context(
        run_context: dict[str, Any] | None,
        cache_key: str,
        content: str,
    ) -> None:
        if run_context is not None:
            run_context[DYNAMIC_MEMORY_CONTEXT_KEY] = {
                "key": cache_key,
                "content": content,
                "recorded": False,
            }

    def _record_turn_context(
        self,
        run_context: dict[str, Any] | None,
        content: str,
    ) -> None:
        if not content or run_context is None:
            return
        cached = run_context.get(DYNAMIC_MEMORY_CONTEXT_KEY)
        if isinstance(cached, dict) and cached.get("recorded"):
            return
        journal = run_context.get("__run_journal")
        if journal is None:
            return
        try:
            journal.record_memory_context(
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            if isinstance(cached, dict):
                cached["recorded"] = True
        except Exception:
            logger.debug("Failed to record query-aware memory context", exc_info=True)

    @staticmethod
    def _request_with_turn_context(
        request: ModelRequest,
        target: HumanMessage,
        content: str,
    ) -> ModelRequest:
        if not content:
            return request
        reminder = HumanMessage(
            content=content,
            name=_TURN_MEMORY_MESSAGE_NAME,
            additional_kwargs={
                "hide_from_ui": True,
                _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                _TURN_MEMORY_MARKER_KEY: True,
            },
        )
        messages = list(request.messages)
        target_index = next(
            (index for index in range(len(messages) - 1, -1, -1) if messages[index] is target),
            len(messages),
        )
        messages.insert(target_index, reminder)
        return request.override(messages=messages)

    def _load_turn_context(self, request: ModelRequest, query: str) -> str:
        from deerflow.agents.lead_agent.prompt import _get_memory_context

        return _get_memory_context(
            self._agent_name,
            app_config=self._app_config,
            user_id=resolve_runtime_user_id(getattr(request, "runtime", None)),
            query=query,
            thread_id=self._thread_id(request),
        ).strip()

    async def _aload_turn_context(self, request: ModelRequest, query: str) -> str:
        from deerflow.agents.lead_agent.prompt import _aget_memory_context

        return (
            await _aget_memory_context(
                self._agent_name,
                app_config=self._app_config,
                user_id=resolve_runtime_user_id(getattr(request, "runtime", None)),
                query=query,
                thread_id=self._thread_id(request),
            )
        ).strip()

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        plan = self._turn_context_plan(request)
        if plan is None:
            return handler(request)
        if self._memory_context_refresh_policy() != "turn":
            return handler(request)
        target, query, cache_key, run_context = plan
        cached, content = self._cached_turn_context(run_context, cache_key)
        if not cached:
            try:
                content = _run_sync_with_timeout(
                    lambda: self._load_turn_context(request, query),
                    _INJECT_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                self._raise_on_closed_read_timeout(exc)
                logger.warning(
                    "DynamicContextMiddleware: query-aware memory retrieval timed out (%.1fs); continuing without memory for this turn",
                    _INJECT_TIMEOUT_SECONDS,
                )
                content = ""
            self._store_turn_context(run_context, cache_key, content)
        self._record_turn_context(run_context, content)
        return handler(self._request_with_turn_context(request, target, content))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        plan = self._turn_context_plan(request)
        if plan is None:
            return await handler(request)
        if await self._amemory_context_refresh_policy() != "turn":
            return await handler(request)
        target, query, cache_key, run_context = plan
        cached, content = self._cached_turn_context(run_context, cache_key)
        if not cached:
            try:
                content = await asyncio.wait_for(
                    self._aload_turn_context(request, query),
                    timeout=_INJECT_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                self._raise_on_closed_read_timeout(exc)
                logger.warning(
                    "DynamicContextMiddleware: query-aware memory retrieval timed out (%.1fs); continuing without memory for this turn",
                    _INJECT_TIMEOUT_SECONDS,
                )
                content = ""
            self._store_turn_context(run_context, cache_key, content)
        self._record_turn_context(run_context, content)
        return await handler(self._request_with_turn_context(request, target, content))

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
