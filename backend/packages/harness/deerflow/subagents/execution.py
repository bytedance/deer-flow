"""Host-owned execution identity, capacity, deadlines and cleanup for all workers."""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
import time
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import Context, copy_context
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from langchain_core.callbacks.base import BaseCallbackManager
from langchain_core.runnables.config import var_child_runnable_config

from deerflow.subagents.capacity import SubagentCapacityError, get_subagent_execution_capacity
from deerflow.subagents.worker_backends import WorkerOutcome
from deerflow.trace_context import ensure_trace_context
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)
_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS = 3.0
_BASH_EVIDENCE_MAX_ENTRIES = 20


def _utcnow() -> datetime:
    # SubagentResult timestamp writers must stamp UTC-aware datetimes so
    # lifecycle metadata never depends on the host wall clock (see deerflow.utils.time).
    return datetime.now(UTC)


_previous_shutdown_isolated_subagent_loop = globals().get("_shutdown_isolated_subagent_loop")
if callable(_previous_shutdown_isolated_subagent_loop):
    atexit.unregister(_previous_shutdown_isolated_subagent_loop)
    _previous_shutdown_isolated_subagent_loop()


class SubagentStatus(Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in {
            type(self).COMPLETED,
            type(self).FAILED,
            type(self).CANCELLED,
            type(self).TIMED_OUT,
        }


@dataclass(frozen=True)
class _SubagentSnapshot:
    """One isolated read of published data, without execution lifecycle state."""

    revision: int
    status: SubagentStatus
    result: str | None
    error: str | None
    stop_reason: str | None
    ai_messages: list[dict[str, Any]]
    message_start_index: int
    message_count: int
    token_usage_records: list[dict[str, int | str | None]]
    tool_receipts: list[dict[str, Any]] | None
    bash_executions: list[dict[str, Any]] | None
    knowledge_sources: list[dict[str, Any]]
    execution_id: str
    executor: str
    error_code: str | None
    backend_stop_reason: str | None
    external_usage: dict[str, Any] | None
    workspace_ref: str | None


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Server-generated identifier that owns this execution.
        external_task_id: Optional provider correlation ID. This stays separate
            because provider tool-call IDs can repeat across parent runs.
        trace_id: Trace ID for distributed tracing (links parent and subagent logs).
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed).
        stop_reason: Why a guardrail cap ended the run early
            (``token_capped`` / ``turn_capped`` / ``loop_capped``), or ``None``
            for a clean run. A capped run keeps a normal status — ``completed``
            when it produced usable output (the partial work survives on
            ``result``), ``failed`` when it did not — and carries the cap here
            so the lead can tell "finished" from "capped" (#3875 Phase 2).
        started_at: When execution started.
        completed_at: When execution completed.
        ai_messages: List of complete AI messages (as dicts) generated during execution.
        admission_failure: Whether capacity rejected/timed out before execution started.
        tool_receipts: The child's tool receipts harvested from its terminal
            message stream (RFC #4651 PR2). ``None`` when the run ended before
            streaming produced a state (e.g. pre-stream cancellation), when
            receipts are disabled, or when harvesting failed; an empty list
            means the stream carried no stamped receipts (zero tool calls).
        bash_executions: Bounded bash command/output evidence accumulated from
            every streamed chunk (RFC #4651 PR4), letting the parent anchor a
            ``tests_passed:<command>`` acceptance leaf to a specific recorded
            execution. Each entry also carries ``status_marker`` — the exit
            marker text the recorded status was derived from, when one was
            seen — so the leaf detail can report what was actually observed
            — and ``shell_persistent``, the producing sandbox's
            ``persistent_shell_sessions`` flag resolved from the state that
            carried the evidence (``None`` when unidentifiable — the matcher
            fails closed on it).
            Accumulated per chunk (merged by result message id, ``tool_call_id``
            only for entries without one) so
            summarization compacting earlier messages cannot erase a recorded
            execution. ``None`` when the delegation carried no acceptance
            criteria, the run ended before streaming, or harvesting failed;
            an empty list means the stream carried no bash-family tool calls.
        execution_done_event: Internal lifecycle fence set only after stream,
            sandbox, extension, and capacity cleanup has settled. A configured
            timeout may publish ``TIMED_OUT`` before this fence opens.
    """

    task_id: str
    trace_id: str
    status: SubagentStatus
    external_task_id: str | None = field(default=None, kw_only=True)
    result: str | None = None
    error: str | None = None
    stop_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    token_usage_records: list[dict[str, int | str | None]] = field(default_factory=list)
    usage_reported: bool = False
    admission_failure: bool = False
    tool_receipts: list[dict[str, Any]] | None = field(default=None, kw_only=True)
    bash_executions: list[dict[str, Any]] | None = field(default=None, kw_only=True)
    knowledge_sources: list[dict[str, Any]] = field(default_factory=list, kw_only=True)
    executor: str = field(default="native", kw_only=True)
    error_code: str | None = field(default=None, kw_only=True)
    backend_stop_reason: str | None = field(default=None, kw_only=True)
    external_usage: dict[str, Any] | None = field(default=None, kw_only=True)
    workspace_ref: str | None = field(default=None, kw_only=True)
    task_store: Any | None = field(default=None, repr=False, kw_only=True)
    loaded_extensions: Any | None = field(default=None, repr=False, kw_only=True)
    backend_cleanup: Any | None = field(default=None, repr=False, kw_only=True)
    deadline: float | None = field(default=None, repr=False, kw_only=True)
    _knowledge_messages: list[Any] = field(default_factory=list, init=False, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    execution_done_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _revision: int = field(default=0, init=False, repr=False)
    _change_waiters: dict[asyncio.Future, asyncio.AbstractEventLoop] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []
        if self.status.is_terminal or self.completed_at is not None:
            self.execution_done_event.set()

    def snapshot(self, after_message_index: int = 0) -> _SubagentSnapshot:
        """Copy only unread steps while running; terminal delivery needs all steps."""
        with self._state_lock:
            messages = self.ai_messages or []
            start = 0 if self.status.is_terminal else after_message_index
            return _SubagentSnapshot(
                revision=self._revision,
                status=self.status,
                result=self.result,
                error=self.error,
                stop_reason=self.stop_reason,
                ai_messages=deepcopy(messages[start:]),
                message_start_index=start,
                message_count=len(messages),
                token_usage_records=deepcopy(self.token_usage_records),
                tool_receipts=deepcopy(self.tool_receipts),
                bash_executions=deepcopy(self.bash_executions),
                knowledge_sources=deepcopy(self.knowledge_sources),
                execution_id=self.task_id,
                executor=self.executor,
                error_code=self.error_code,
                backend_stop_reason=self.backend_stop_reason,
                external_usage=deepcopy(self.external_usage),
                workspace_ref=self.workspace_ref,
            )

    async def wait_for_change(self, revision: int, *, timeout: float) -> None:
        """Subscribe atomically with a version recheck on the consumer's loop."""
        loop = asyncio.get_running_loop()
        with self._state_lock:
            if self._revision != revision:
                return
            future = loop.create_future()
            self._change_waiters[future] = loop
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            pass
        finally:
            with self._state_lock:
                self._change_waiters.pop(future, None)

    def _take_change_waiters_locked(self) -> dict[asyncio.Future, asyncio.AbstractEventLoop]:
        self._revision += 1
        waiters, self._change_waiters = self._change_waiters, {}
        return waiters

    @staticmethod
    def _wake_change_waiters(waiters: dict[asyncio.Future, asyncio.AbstractEventLoop]) -> None:
        def complete(future: asyncio.Future) -> None:
            if not future.done():
                future.set_result(None)

        for future, loop in waiters.items():
            try:
                loop.call_soon_threadsafe(complete, future)
            except RuntimeError:
                # A consumer may have closed its loop after subscription.
                # Notification failure must never change the published result.
                pass

    def try_set_running(self) -> bool:
        with self._state_lock:
            if self.status.is_terminal:
                return False
            self.started_at = _utcnow()
            if self.status is SubagentStatus.RUNNING:
                return True
            self.status = SubagentStatus.RUNNING
            waiters = self._take_change_waiters_locked()
        self._wake_change_waiters(waiters)
        return True

    def publish_steps(self, messages: list[dict[str, Any]], records: list[dict[str, int | str | None]]) -> None:
        """Publish a captured suffix and its usage together before notifying."""
        with self._state_lock:
            if self.status.is_terminal:
                return
            self.ai_messages.extend(deepcopy(messages))
            self.token_usage_records = deepcopy(records)
            waiters = self._take_change_waiters_locked() if messages else {}
        self._wake_change_waiters(waiters)

    def update_token_usage_records(self, records: list[dict[str, int | str | None]]) -> None:
        """Publish cumulative usage, including timeout/cancel cleanup tails."""
        with self._state_lock:
            if not self.status.is_terminal or self.status in {
                SubagentStatus.CANCELLED,
                SubagentStatus.TIMED_OUT,
            }:
                self.token_usage_records = deepcopy(records)

    def update_tool_receipts(self, receipts: list[dict[str, Any]] | None) -> None:
        """Publish receipts from the latest yielded state while still running."""
        if receipts is None:
            return
        with self._state_lock:
            if not self.status.is_terminal:
                self.tool_receipts = [dict(receipt) for receipt in receipts]

    def update_bash_executions(self, executions: list[dict[str, Any]] | None) -> None:
        """Merge bash evidence from the latest yielded state while still running.

        Entries merge by their result message (``tool_call_id`` when it has no
        id, since providers can reuse call ids across responses) in first-seen
        order and are capped to the newest ``_BASH_EVIDENCE_MAX_ENTRIES`` — unlike a terminal
        ``final_state`` scan, accumulation survives summarization compacting
        earlier AI/ToolMessages out of the streamed history. ``None`` leaves
        the field untouched (no evidence this chunk); an empty list still
        publishes, keeping "the stream carried no bash-family tool calls"
        distinguishable from "no evidence was collected" (mirrors
        ``update_tool_receipts``).
        """
        if executions is None:
            return
        with self._state_lock:
            if self.status.is_terminal:
                return
            merged = {_bash_evidence_key(entry): entry for entry in (self.bash_executions or [])}
            for execution in executions:
                merged[_bash_evidence_key(execution)] = dict(execution)
            self.bash_executions = list(merged.values())[-_BASH_EVIDENCE_MAX_ENTRIES:]

    def snapshot_tool_receipts(self) -> list[dict[str, Any]] | None:
        """Copy the latest published receipts for a racing terminal writer."""
        with self._state_lock:
            if self.tool_receipts is None:
                return None
            return [dict(receipt) for receipt in self.tool_receipts]

    def update_knowledge_sources(self, messages: list[Any] | None) -> None:
        """Accumulate validated retrieval evidence before terminal publication."""
        from deerflow.knowledge import sources_from_messages

        with self._state_lock:
            if self.status.is_terminal:
                return
            if messages is None:
                return
            # Values histories grow cumulatively, but compaction/replacements
            # can change the prefix. Rescan from the first changed message.
            start = 0
            for previous, current in zip(self._knowledge_messages, messages):
                if previous != current:
                    break
                start += 1
            sources = sources_from_messages(messages[start:]) if start < len(messages) else []
            self._knowledge_messages = list(messages)
            merged = {source["id"]: source for source in self.knowledge_sources}
            for source in sources:
                merged[source.id] = source.model_dump(mode="json", exclude_none=True)
            self.knowledge_sources = list(merged.values())[-100:]

    def try_set_terminal(
        self,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        error_code: str | None = None,
        backend_stop_reason: str | None = None,
        external_usage: dict[str, Any] | None = None,
        workspace_ref: str | None = None,
        completed_at: datetime | None = None,
        ai_messages: list[dict[str, Any]] | None = None,
        token_usage_records: list[dict[str, int | str | None]] | None = None,
        admission_failure: bool = False,
        tool_receipts: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Set a terminal status exactly once.

        Background timeout/cancellation and the execution worker can race on the
        same result holder.  The first terminal transition wins; late terminal
        writes must not change status or payload fields.
        """
        if not status.is_terminal:
            raise ValueError(f"Status {status} is not terminal")

        with self._state_lock:
            if self.status.is_terminal:
                return False

            if result is not None:
                self.result = result
            if error is not None:
                self.error = error
            if stop_reason is not None:
                self.stop_reason = stop_reason
            if ai_messages is not None:
                self.ai_messages = deepcopy(ai_messages)
            if token_usage_records is not None:
                self.token_usage_records = deepcopy(token_usage_records)
            if tool_receipts is not None:
                self.tool_receipts = [dict(receipt) for receipt in tool_receipts]
            self.error_code = error_code
            self.backend_stop_reason = backend_stop_reason
            self.external_usage = deepcopy(external_usage)
            self.workspace_ref = workspace_ref
            self.admission_failure = admission_failure
            self.completed_at = completed_at or _utcnow()
            self.status = status
            waiters = self._take_change_waiters_locked()
        self._wake_change_waiters(waiters)
        return True


_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

_background_futures: dict[str, Future[SubagentResult]] = {}
_background_cleanup_requested: set[str] = set()
# A timed-out public result can precede stream/resource cleanup. Keep the
# execution task alive and observed until that cleanup settles on its owner loop.
_background_execution_tasks: set[asyncio.Task[SubagentResult]] = set()


def _bash_evidence_key(execution: dict[str, Any]) -> tuple[str, str]:
    """Identify one recorded execution across values chunks.

    A provider may reuse a call id in a later response, so the result message
    id names the execution; entries without one keep the call-id identity.
    """
    result_id = execution.get("result_id")
    if isinstance(result_id, str) and result_id:
        return ("result", result_id)
    return ("call", str(execution.get("tool_call_id")))


# Persistent event loop for isolated subagent executions triggered from an
# already-running parent loop. Reusing one long-lived loop avoids creating a
# fresh loop per execution and then closing async resources bound to it.
_isolated_subagent_loop: asyncio.AbstractEventLoop | None = None
_isolated_subagent_loop_thread: threading.Thread | None = None
_isolated_subagent_loop_started: threading.Event | None = None
_isolated_subagent_loop_shutdown_pending = False
_isolated_subagent_loop_lock = threading.Lock()
_isolated_subagent_loop_shutdown_lock = threading.Lock()


def _run_isolated_subagent_loop(
    loop: asyncio.AbstractEventLoop,
    started_event: threading.Event,
) -> None:
    """Run the persistent isolated subagent loop in a dedicated daemon thread."""
    asyncio.set_event_loop(loop)
    loop.call_soon(started_event.set)
    try:
        loop.run_forever()
    finally:
        started_event.clear()


def _shutdown_isolated_subagent_loop(*, only_if_pending: bool = False) -> None:
    """Stop and close the persistent isolated subagent loop."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started, _isolated_subagent_loop_shutdown_pending

    with _isolated_subagent_loop_shutdown_lock:
        with _isolated_subagent_loop_lock:
            # Dispatch recovery can become stale while waiting for this lock.
            # Recheck the fence before touching the current loop generation.
            if only_if_pending and not _isolated_subagent_loop_shutdown_pending:
                return
            loop = _isolated_subagent_loop
            thread = _isolated_subagent_loop_thread
            if loop is None:
                _isolated_subagent_loop_shutdown_pending = False
                return
            _isolated_subagent_loop_shutdown_pending = True

            # A previous bounded shutdown/startup attempt already requested
            # loop.stop. Dispatch-side recovery should only probe whether the
            # retained worker has exited; repeatedly joining here would stall
            # every caller for up to one second while the worker remains live.
            if only_if_pending and thread is not None and thread.is_alive():
                return

        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1)

        thread_stopped = thread is None or not thread.is_alive()
        loop_stopped = not loop.is_running()

        if not thread_stopped or not loop_stopped:
            logger.warning(
                "Retaining isolated subagent loop ownership because shutdown did not complete within timeout (thread_alive=%s, loop_running=%s)",
                thread is not None and thread.is_alive(),
                loop.is_running(),
            )
            return

        if not loop.is_closed():
            loop.close()

        with _isolated_subagent_loop_lock:
            if _isolated_subagent_loop is loop and _isolated_subagent_loop_thread is thread:
                _isolated_subagent_loop = None
                _isolated_subagent_loop_thread = None
                _isolated_subagent_loop_started = None
                _isolated_subagent_loop_shutdown_pending = False


atexit.register(_shutdown_isolated_subagent_loop)


def _get_isolated_subagent_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent event loop used by isolated subagent executions."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started, _isolated_subagent_loop_shutdown_pending

    # A startup/shutdown timeout retains ownership while the worker is alive.
    # Ordinary dispatch is also the retry path once that worker has actually
    # exited: reap the retained loop under the shutdown lifecycle lock before
    # deciding whether replacement is still fenced.
    if _isolated_subagent_loop_shutdown_pending:
        _shutdown_isolated_subagent_loop(only_if_pending=True)

    with _isolated_subagent_loop_lock:
        if _isolated_subagent_loop_shutdown_pending:
            raise RuntimeError("Isolated subagent event loop shutdown is still pending; retained worker is still exiting")

        thread_is_alive = _isolated_subagent_loop_thread is not None and _isolated_subagent_loop_thread.is_alive()
        loop_is_usable = _isolated_subagent_loop is not None and not _isolated_subagent_loop.is_closed() and _isolated_subagent_loop.is_running() and thread_is_alive

        if not loop_is_usable:
            loop = asyncio.new_event_loop()
            started_event = threading.Event()
            thread = threading.Thread(
                target=_run_isolated_subagent_loop,
                args=(loop, started_event),
                name="subagent-persistent-loop",
                daemon=True,
            )
            thread.start()
            if not started_event.wait(timeout=5):
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
                if thread.is_alive() or loop.is_running():
                    _isolated_subagent_loop = loop
                    _isolated_subagent_loop_thread = thread
                    _isolated_subagent_loop_started = started_event
                    _isolated_subagent_loop_shutdown_pending = True
                    logger.warning(
                        "Retaining isolated subagent loop ownership after startup timeout (thread_alive=%s, loop_running=%s)",
                        thread.is_alive(),
                        loop.is_running(),
                    )
                elif not loop.is_closed():
                    loop.close()
                raise RuntimeError("Timed out starting isolated subagent event loop")
            _isolated_subagent_loop = loop
            _isolated_subagent_loop_thread = thread
            _isolated_subagent_loop_started = started_event

        if _isolated_subagent_loop is None:
            raise RuntimeError("Isolated subagent event loop is not initialized")
        return _isolated_subagent_loop


def _run_on_isolated_loop_if_live(callback: Callable[[], None]) -> None:
    """Run ``callback`` on the isolated loop, or inline when it cannot run.

    Used to re-order a decision against a coroutine that was already submitted
    to the loop: only the loop itself is serialized with that coroutine's first
    step, so a caller thread cannot tell which of the two landed first.

    A loop that is missing, stopped, or closed can no longer start the
    coroutine, so running inline is then equivalent to running on it.
    """
    loop = _isolated_subagent_loop
    if loop is None or loop.is_closed() or not loop.is_running():
        callback()
        return
    try:
        loop.call_soon_threadsafe(callback)
    except RuntimeError:
        # Closed between the lookup and the hand-off; nothing can start on it.
        callback()


def _submit_to_isolated_loop_in_context(
    context: Context,
    coro_factory: Callable[[], Coroutine[Any, Any, SubagentResult]],
) -> Future[SubagentResult]:
    """Submit a coroutine to the isolated loop while preserving ContextVar state.

    The loop must be resolved before the coroutine is created: as direct
    ``run_coroutine_threadsafe(coro_factory(), ...)`` arguments, Python
    evaluates the coroutine first, so a loop-startup failure would strand a
    created-but-never-scheduled coroutine (``RuntimeWarning: coroutine ...
    was never awaited``) holding its captures until collection.

    Scheduling itself can still reject an already-created coroutine — e.g.
    the loop closes between the lookup above and the ``call_soon_threadsafe``
    inside ``run_coroutine_threadsafe`` — so a rejected coroutine is closed
    before the error propagates.
    """

    def _submit() -> Future[SubagentResult]:
        loop = _get_isolated_subagent_loop()
        coroutine = coro_factory()
        try:
            return asyncio.run_coroutine_threadsafe(coroutine, loop)
        except BaseException:
            # run_coroutine_threadsafe has no cleanup path for this window.
            # The coroutine has not started (CORO_CREATED), so close() cannot
            # run any of its body — it only releases the object and its
            # captures instead of leaving them until collection.
            coroutine.close()
            raise

    return context.run(_submit)


def run_on_isolated_subagent_loop[T](coro: Coroutine[Any, Any, T]) -> Future[T]:
    """Schedule a coroutine on the process-owned persistent subagent loop.

    Unlike ``asyncio.create_task`` on the caller's loop, work submitted here
    survives teardown of a short-lived caller loop — e.g. the ``asyncio.run()``
    used by the synchronous tool wrapper cancels caller-loop tasks on exit —
    so registry cleanup scheduled from a failing poller still runs after the
    caller loop is gone.
    """
    return asyncio.run_coroutine_threadsafe(coro, _get_isolated_subagent_loop())


def _copy_isolated_subagent_context() -> Context:
    """Copy ambient context without loop-bound parent graph callbacks.

    LangGraph keeps the current runnable config in a ``ContextVar``. Crossing
    into the persistent subagent loop must retain checkpoint lineage, runtime
    metadata, user identity, and tracing context. LangGraph merges inherited
    and explicit callbacks, so merely supplying the subagent collector is
    insufficient: loop-bound application callbacks such as the parent
    ``RunJournal`` would still run on the isolated loop. Framework streaming
    callbacks are intentionally preserved so namespaced child token frames
    continue to reach the parent stream.
    """
    context = copy_context()
    inherited_config = context.get(var_child_runnable_config)
    if inherited_config is None or "callbacks" not in inherited_config:
        return context

    callbacks = inherited_config.get("callbacks")
    if isinstance(callbacks, BaseCallbackManager):
        isolated_callbacks = callbacks.copy()
        isolated_callbacks.handlers = [handler for handler in callbacks.handlers if not getattr(handler, "deerflow_loop_bound", False)]
        isolated_callbacks.inheritable_handlers = [handler for handler in callbacks.inheritable_handlers if not getattr(handler, "deerflow_loop_bound", False)]
    elif isinstance(callbacks, (list, tuple)):
        isolated_callbacks = [handler for handler in callbacks if not getattr(handler, "deerflow_loop_bound", False)]
    elif getattr(callbacks, "deerflow_loop_bound", False):
        isolated_callbacks = None
    else:
        isolated_callbacks = callbacks

    isolated_config = inherited_config.copy()
    if isolated_callbacks:
        isolated_config["callbacks"] = isolated_callbacks
    else:
        isolated_config.pop("callbacks", None)
    context.run(var_child_runnable_config.set, isolated_config)
    return context


class DelegatedTaskExecutor:
    """The host owns public state; admitted backends return a proposed outcome."""

    backend_name = "native"

    @staticmethod
    def _deadline_expired(result):
        if result.deadline is None or time.monotonic() < result.deadline:
            return False
        result.cancel_event.set()
        result.try_set_terminal(
            SubagentStatus.TIMED_OUT, error="Execution deadline expired", error_code="admission_deadline" if result.status is SubagentStatus.PENDING else "execution_deadline", admission_failure=result.status is SubagentStatus.PENDING
        )
        return True

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        result = result_holder or SubagentResult(task_id=str(uuid.uuid4()), trace_id=self.trace_id, status=SubagentStatus.PENDING)
        with ensure_trace_context(self.deerflow_trace_id):
            try:
                if self._deadline_expired(result):
                    return result
                capacity = self.execution_capacity or get_subagent_execution_capacity()
                slot = capacity.slot(wait=False) if self.input_gate is not None and not self.input_gate.can_queue else capacity.slot()
                async with slot:
                    if self._deadline_expired(result):
                        return result
                    if (result.cancel_event.is_set() and result.status is SubagentStatus.PENDING) or not result.try_set_running():
                        result.try_set_terminal(SubagentStatus.CANCELLED, error="Cancelled by user")
                        return result
                    await self._run_admitted(task, result)
            except SubagentCapacityError as exc:
                result.try_set_terminal(SubagentStatus.FAILED, error=str(exc), admission_failure=True, error_code="capacity_unavailable")
            except asyncio.CancelledError:
                result.try_set_terminal(SubagentStatus.CANCELLED, error="Cancelled by user")
                raise
            except Exception as exc:
                result.try_set_terminal(SubagentStatus.FAILED, error=str(exc), error_code="backend_failed")
            finally:
                if self.input_gate is not None:
                    self.input_gate.close()
                result.execution_done_event.set()
        return result

    async def _run_admitted(self, task: str, result: SubagentResult) -> None:
        from deerflow_extension_api import ExtensionData, TaskInfo

        from deerflow.extensions import get_loaded_extensions
        from deerflow.extensions.notify import lead_task_id, notify_task_start, notify_task_stop, subagent_task_outcome

        extensions = self.extensions if self.extensions is not None else get_loaded_extensions()
        result.loaded_extensions = extensions
        info = None
        if extensions.needs_task_store:
            result.task_store = ExtensionData(result.external_task_id or result.task_id)
            if self.run_id:
                info = TaskInfo(task_id=result.task_id, run_id=self.run_id, thread_id=self.thread_id or "", kind="subagent", parent_task_id=lead_task_id(self.run_id), agent_name=self.config.name)
                result.task_store.set(info)
        try:
            if info is not None and extensions.has_task_lifecycle:
                await notify_task_start(extensions, result.task_store, info, timeout=_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS)
            if self._deadline_expired(result):
                return
            outcome = await self._aexecute_admitted(task, result)
            if self._deadline_expired(result):
                return
            if not isinstance(outcome, WorkerOutcome) and (outcome is not result or not result.status.is_terminal):
                raise TypeError("Worker backend must return WorkerOutcome")
            if isinstance(outcome, WorkerOutcome):
                result.try_set_terminal(
                    SubagentStatus(outcome.status),
                    result=outcome.result,
                    error=outcome.error,
                    stop_reason=outcome.stop_reason,
                    error_code=outcome.error_code,
                    backend_stop_reason=outcome.backend_stop_reason,
                    external_usage=outcome.external_usage,
                    workspace_ref=outcome.workspace_ref,
                    token_usage_records=outcome.token_usage_records,
                    tool_receipts=outcome.tool_receipts,
                )
        except asyncio.CancelledError:
            result.try_set_terminal(SubagentStatus.CANCELLED, error="Cancelled by user")
            raise
        except Exception as exc:
            result.try_set_terminal(SubagentStatus.FAILED, error=str(exc), error_code="backend_failed")
        finally:

            async def cleanup():
                try:
                    if result.backend_cleanup is not None:
                        await result.backend_cleanup()
                finally:
                    if info is not None and extensions.has_task_lifecycle:
                        await notify_task_stop(
                            extensions, result.task_store, info, subagent_task_outcome(cancelled=result.status is SubagentStatus.CANCELLED, succeeded=result.status is SubagentStatus.COMPLETED), timeout=_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS
                        )

            await await_drained(cleanup())

    def _execute_in_isolated_loop(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute the subagent on the persistent isolated event loop.

        This method is used by the sync ``execute()`` path when the caller is
        already running inside an event loop. Because ``execute()`` is a sync
        API, this path blocks the caller while the actual coroutine runs on the
        long-lived isolated loop. Reusing that loop keeps shared async clients
        from being tied to a short-lived loop that gets closed per execution.
        """
        if result_holder is None:
            result_holder = SubagentResult(task_id=str(uuid.uuid4())[:8], trace_id=self.trace_id, status=SubagentStatus.PENDING)
        future: Future[SubagentResult] | None = None
        parent_context = _copy_isolated_subagent_context()
        try:
            future = _submit_to_isolated_loop_in_context(
                parent_context,
                lambda: self._aexecute(task, result_holder),
            )
            return future.result(timeout=self.config.timeout_seconds)
        except FuturesTimeoutError as exc:
            # Publish the synchronous API's failure before cancellation can
            # reach task-stop observers or win the terminal-state race.
            result_holder.try_set_terminal(SubagentStatus.FAILED, error=str(exc))
            result_holder.cancel_event.set()
            if future is not None:
                future.cancel()
            raise
        except Exception:
            if future is None:
                logger.debug(
                    f"[trace={self.trace_id}] Failed to submit subagent {self.config.name} to the isolated event loop",
                    exc_info=True,
                )
            else:
                logger.debug(
                    f"[trace={self.trace_id}] Subagent {self.config.name} failed while executing on the isolated event loop",
                    exc_info=True,
                )
            raise

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously (wrapper around async execution).

        All sync executions use the persistent isolated event loop. This keeps
        shared async clients and the process-wide admission controller bound to
        one long-lived loop instead of creating a short-lived loop per call.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """
        # Share one holder with the worker even when the caller did not supply
        # one, so a timeout and its cleanup report the same terminal outcome.
        result = result_holder
        if result is None:
            result = SubagentResult(
                task_id=str(uuid.uuid4())[:8],
                trace_id=self.trace_id,
                status=SubagentStatus.PENDING,
            )
        try:
            return self._execute_in_isolated_loop(task, result)
        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            result.try_set_terminal(SubagentStatus.FAILED, error=str(e))
            return result

    def execute_async(self, task: str, task_id: str | None = None) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description for the subagent.
            task_id: Optional external correlation ID for logs. It is never used
                as the process-wide background registry key because provider
                tool-call IDs can repeat across concurrent parent runs.

        Returns:
            Unique execution ID that can be used to check status later.
        """
        deadline = time.monotonic() + self.config.timeout_seconds
        execution_id = str(uuid.uuid4())

        # Create initial pending result
        result = SubagentResult(
            task_id=execution_id,
            external_task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
            executor=self.backend_name,
            deadline=deadline,
        )

        logger.info(
            "[trace=%s] Subagent %s starting async execution, execution_id=%s, external_task_id=%s, timeout=%ss",
            self.trace_id,
            self.config.name,
            execution_id,
            task_id,
            self.config.timeout_seconds,
        )

        # Copy the parent context before registering: context copying can
        # itself fail (callback-manager copy or loop-bound handler filtering),
        # and a failure after registration would strand a PENDING entry —
        # the caller never receives an execution_id to poll, and
        # cleanup_background_task() refuses non-terminal entries.
        parent_context = _copy_isolated_subagent_context()

        with _background_tasks_lock:
            _background_tasks[execution_id] = result

        # Set once the coroutine body actually runs. A ``concurrent.futures``
        # future reports ``cancelled()`` both when the cancel beat the loop and
        # when a running coroutine was cancelled, and only the first case leaves
        # the result without an owner able to publish a terminal status.
        execution_started = threading.Event()

        async def run_with_timeout() -> SubagentResult:
            execution_started.set()
            # Startup half of the pre-start cancellation handshake. The
            # canceller sets ``cancel_event`` before it decides anything, so a
            # body that starts after that cancel must decline to create the
            # execution task: a cancel published from the caller thread may
            # already have opened the cleanup fence, and creating the task here
            # would then take a capacity slot the fence promised was gone.
            # Reading the event first makes "fence opened before this body
            # started" safe instead of a race.
            if result.cancel_event.is_set():
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled before the execution started",
                    tool_receipts=result.snapshot_tool_receipts(),
                )
                _mark_background_execution_done(execution_id, result)
                return result
            if self._deadline_expired(result):
                _mark_background_execution_done(execution_id, result)
                return result
            execution_task = asyncio.create_task(
                self._aexecute(task, result),
                name=f"subagent-{self.config.name}-execution",
            )
            try:
                done, _ = await asyncio.wait(
                    {execution_task},
                    timeout=max(0, deadline - time.monotonic()),
                )
                if execution_task in done:
                    return execution_task.result()

                # Publish the configured hard timeout without waiting for
                # cancellation-resistant stream cleanup. The detached execution
                # still owns its capacity slot and sandbox lease until its
                # supervisor observes full teardown.
                result.cancel_event.set()
                result.try_set_terminal(
                    SubagentStatus.TIMED_OUT,
                    error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                    error_code="admission_deadline" if result.status is SubagentStatus.PENDING else "execution_deadline",
                    admission_failure=result.status is SubagentStatus.PENDING,
                    tool_receipts=result.snapshot_tool_receipts(),
                )
                execution_task.cancel()
                _supervise_background_execution(
                    execution_id,
                    result,
                    execution_task,
                )
                execution_task = None
                return result
            except asyncio.CancelledError:
                result.cancel_event.set()
                if not execution_task.done():
                    execution_task.cancel()
                try:
                    await execution_task
                except (asyncio.CancelledError, Exception):
                    # The child can fail before cancellation reaches it. Keep
                    # its terminal write, or publish cancellation below.
                    pass
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    tool_receipts=result.snapshot_tool_receipts(),
                )
                return result
            except Exception as exc:
                logger.exception("[trace=%s] Subagent %s async execution failed", self.trace_id, self.config.name)
                if not execution_task.done():
                    execution_task.cancel()
                    _supervise_background_execution(
                        execution_id,
                        result,
                        execution_task,
                    )
                    execution_task = None
                result.try_set_terminal(SubagentStatus.FAILED, error=str(exc))
                return result
            finally:
                if execution_task is not None:
                    _mark_background_execution_done(execution_id, result)

        try:
            execution_future = _submit_to_isolated_loop_in_context(parent_context, run_with_timeout)
        except Exception:
            # Submitting can fail before any coroutine starts (e.g. the
            # persistent loop failed to spin up). The caller then sees the
            # exception and never polls this execution_id, and
            # cleanup_background_task() refuses non-terminal entries — so the
            # just-registered entry must be dropped here, not left as a
            # PENDING zombie nothing will ever remove.
            with _background_tasks_lock:
                _background_tasks.pop(execution_id, None)
            raise
        with _background_tasks_lock:
            _background_futures[execution_id] = execution_future

        def publish_pre_start_cancel() -> None:
            # The chained future reports ``cancelled()`` for two different
            # outcomes: the cancel beat the loop, or it reached a started
            # coroutine that is still winding down. Only the first leaves the
            # result without an owner able to publish a terminal status, and a
            # task that exists but has not taken its first step still runs its
            # body. Deciding on the loop, after that step, keeps the cleanup
            # fence closed while the worker can still hold its capacity slot.
            #
            # A body that starts after this point cannot take a slot either:
            # ``result.cancel_event`` is always set before this callback runs,
            # and ``run_with_timeout`` declines to create the execution task
            # once it observes it. So "fence opened" here means "no worker will
            # acquire capacity", not merely "no worker has yet".
            if execution_started.is_set():
                return
            result.try_set_terminal(
                SubagentStatus.CANCELLED,
                error="Cancelled before the execution started",
                tool_receipts=result.snapshot_tool_receipts(),
            )
            _mark_background_execution_done(execution_id, result)

        def forget_future(completed_future: Future[SubagentResult]) -> None:
            if completed_future.cancelled():
                # ``Future.cancel()`` only wins while the loop has not picked the
                # coroutine up yet. In that window ``run_with_timeout`` never runs,
                # so nothing writes a terminal status and nothing opens the cleanup
                # fence: the entry stayed PENDING and ``cleanup_background_task``
                # refused to remove it, while the poller waited out its full budget
                # for a result that could never arrive. Publish the cancellation
                # here; a cancellation that reached a running coroutine is handled
                # by its own ``CancelledError`` branch, which owns the terminal write.
                _run_on_isolated_loop_if_live(publish_pre_start_cancel)
            else:
                completed_future.exception()
            with _background_tasks_lock:
                _background_futures.pop(execution_id, None)

        execution_future.add_done_callback(forget_future)
        return execution_id


MAX_CONCURRENT_SUBAGENTS = 3


def request_cancel_background_task(execution_id: str) -> None:
    """Signal a running background task to stop.

    Sets the cancel_event on the task, which is checked cooperatively
    by ``_aexecute`` during ``agent.astream()`` iteration.  This allows
    subagent threads — which cannot be force-killed via ``Future.cancel()``
    — to stop at the next iteration boundary.

    Args:
        execution_id: The execution ID returned by execute_async.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(execution_id)
        future = _background_futures.get(execution_id) if result is not None else None
    if result is not None:
        result.cancel_event.set()
        # Future.cancel() may invoke forget_future synchronously; keep it out of
        # _background_tasks_lock because that callback acquires the same lock.
        if future is not None:
            future.cancel()
        logger.info("Requested cancellation for background execution %s", execution_id)


def get_background_task_result(execution_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        execution_id: The execution ID returned by execute_async.

    Returns:
        SubagentResult if found, None otherwise.
    """
    with _background_tasks_lock:
        return _background_tasks.get(execution_id)


def list_background_tasks() -> list[SubagentResult]:
    """List all background tasks.

    Returns:
        List of all SubagentResult instances.
    """
    with _background_tasks_lock:
        return list(_background_tasks.values())


def _remove_background_task_locked(execution_id: str) -> None:
    _background_tasks.pop(execution_id, None)
    _background_futures.pop(execution_id, None)
    _background_cleanup_requested.discard(execution_id)


def _mark_background_execution_done(
    execution_id: str,
    result: SubagentResult,
) -> None:
    result.execution_done_event.set()
    with _background_tasks_lock:
        if execution_id in _background_cleanup_requested and _background_tasks.get(execution_id) is result:
            _remove_background_task_locked(execution_id)


def _supervise_background_execution(
    execution_id: str,
    result: SubagentResult,
    task: asyncio.Task[SubagentResult],
) -> None:
    """Own a timed-out/cancelled execution until resource teardown settles."""
    _background_execution_tasks.add(task)

    def settled(completed: asyncio.Task[SubagentResult]) -> None:
        _background_execution_tasks.discard(completed)
        if not completed.cancelled():
            try:
                completed.result()
            except BaseException as exc:
                logger.error(
                    "Detached cleanup for background execution %s failed",
                    execution_id,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
        _mark_background_execution_done(execution_id, result)

    task.add_done_callback(settled)


def cleanup_background_task(execution_id: str) -> None:
    """Remove a completed task from background tasks.

    Should be called by task_tool after it finishes polling and returns the result.
    This prevents memory leaks from accumulated completed tasks.

    Only removes a terminal task after its execution-cleanup fence opens. A hard
    timeout may publish its business outcome first; cleanup requested in that
    window is completed by the detached execution supervisor.

    Args:
        execution_id: The execution ID to remove.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(execution_id)
        if result is None:
            # Nothing to clean up; may have been removed already.
            _background_cleanup_requested.discard(execution_id)
            logger.debug("Requested cleanup for unknown background execution %s", execution_id)
            return

        terminal = result.status.is_terminal or result.completed_at is not None
        if terminal and result.execution_done_event.is_set():
            _remove_background_task_locked(execution_id)
            logger.debug("Cleaned up background execution: %s", execution_id)
        elif terminal:
            _background_cleanup_requested.add(execution_id)
            logger.debug(
                "Deferred cleanup for background execution %s until teardown completes",
                execution_id,
            )
        else:
            logger.debug(
                "Skipping cleanup for non-terminal background execution %s (status=%s)",
                execution_id,
                result.status.value if hasattr(result.status, "value") else result.status,
            )


def force_cleanup_background_task(execution_id: str) -> None:
    """Remove a background task entry unconditionally.

    Last resort for interrupted unwind paths where the registry entry exists
    but its result object can no longer be read (persistent status-lookup /
    status-object failure), so :func:`cleanup_background_task` — which reads
    the entry to check terminality — cannot succeed. Cooperative cancellation
    has already been requested by then; leaking the entry forever is worse
    than dropping it. The subagent thread keeps its own reference to the
    result object, so a later ``try_set_terminal`` on the removed object is
    harmless.

    Args:
        execution_id: The execution ID to remove.
    """
    with _background_tasks_lock:
        _remove_background_task_locked(execution_id)
    logger.warning("Force-cleaned background execution %s after unreadable status", execution_id)


class WorkerExecutor(DelegatedTaskExecutor):
    """An extension worker uses exactly the native execution lifecycle."""

    def __init__(self, plan, provider, *, execution_capacity=None, extensions=None, workspace_resolver=None, thread_id=None, user_id=None, run_id=None, trace_id="", deerflow_trace_id=None, input_gate=None):
        self.config = plan
        self.provider = provider
        self.backend_name = plan.backend
        self.execution_capacity = execution_capacity
        self.extensions = extensions
        self.workspace_resolver = workspace_resolver
        self.thread_id = thread_id
        self.user_id = user_id
        self.run_id = run_id
        self.trace_id = trace_id
        self.deerflow_trace_id = deerflow_trace_id
        self.input_gate = input_gate

    async def _aexecute_admitted(self, prompt, result):
        from pathlib import Path

        from deerflow.subagents.worker_backends import WorkerExecution

        def workspace():
            if self.workspace_resolver is not None:
                directory = Path(self.workspace_resolver(self.thread_id, self.user_id, result.task_id))
            else:
                from deerflow.config.paths import get_paths

                if not self.thread_id:
                    raise ValueError("External workers require a thread_id or an explicit workspace resolver")
                directory = get_paths().acp_workspace_dir(self.thread_id, user_id=self.user_id) / "executions" / result.task_id
            directory.mkdir(parents=True, exist_ok=True)
            return str(directory.resolve())

        if self.input_gate is not None and self.input_gate.steered.is_set():
            return WorkerOutcome(status="cancelled", error="The task was superseded by a delivered steer.")
        directory = await await_drained(asyncio.to_thread(workspace))
        if self._deadline_expired(result):
            return result
        if result.cancel_event.is_set() or (self.input_gate is not None and self.input_gate.steered.is_set()):
            return WorkerOutcome(status="cancelled", error="The task was cancelled before the backend started.")
        messages = []

        def publish(text):
            messages.append({"id": f"{result.task_id}:{len(messages)}", "type": "ai", "content": text, "execution_id": result.task_id, "executor": self.backend_name})
            result.publish_steps([messages[-1]], [])

        return await self.provider.execute(self.config, WorkerExecution(result.task_id, prompt, directory, publish))
