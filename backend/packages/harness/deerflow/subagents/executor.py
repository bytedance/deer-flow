"""Subagent execution engine."""

import asyncio
import atexit
import logging
import os
import threading
import uuid
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import Context, copy_context
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.callbacks.base import BaseCallbackManager
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.errors import GraphRecursionError

from deerflow.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from deerflow.authz.principal import normalize_authz_attributes
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.runtime.user_context import DEFAULT_USER_ID
from deerflow.skills.types import Skill
from deerflow.subagents.capacity import (
    SubagentCapacityError,
    SubagentExecutionCapacity,
    get_subagent_execution_capacity,
)
from deerflow.subagents.config import SubagentConfig, resolve_subagent_model_name
from deerflow.subagents.step_events import capture_new_step_messages
from deerflow.subagents.token_collector import SubagentTokenCollector
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY
from deerflow.tracing import build_tracing_callbacks, inject_langfuse_metadata
from deerflow.utils.messages import message_content_to_text

if TYPE_CHECKING:
    # Imported lazily at runtime inside _build_initial_state: importing
    # tool_search eagerly would run tools/builtins/__init__ -> task_tool ->
    # `from deerflow.subagents import SubagentExecutor`, which re-enters this
    # still-initializing package. Type-only here keeps the annotation precise.
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS = 3.0


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
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []

    def update_token_usage_records(self, records: list[dict[str, int | str | None]]) -> None:
        """Publish the latest cumulative collector snapshot while still running."""
        with self._state_lock:
            if not self.status.is_terminal:
                self.token_usage_records = list(records)

    def update_tool_receipts(self, receipts: list[dict[str, Any]] | None) -> None:
        """Publish receipts from the latest yielded state while still running."""
        if receipts is None:
            return
        with self._state_lock:
            if not self.status.is_terminal:
                self.tool_receipts = [dict(receipt) for receipt in receipts]

    def snapshot_tool_receipts(self) -> list[dict[str, Any]] | None:
        """Copy the latest published receipts for a racing terminal writer."""
        with self._state_lock:
            if self.tool_receipts is None:
                return None
            return [dict(receipt) for receipt in self.tool_receipts]

    def try_set_terminal(
        self,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
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
                self.ai_messages = ai_messages
            if token_usage_records is not None:
                self.token_usage_records = token_usage_records
            if tool_receipts is not None:
                self.tool_receipts = [dict(receipt) for receipt in tool_receipts]
            self.admission_failure = admission_failure
            self.completed_at = completed_at or datetime.now()
            self.status = status
            return True


def _extract_final_result(final_state: Any, *, trace_id: str, name: str) -> str:
    """Extract a human-readable result string from the streamed subagent state.

    Finds the last ``AIMessage`` in the conversation and stringifies its
    content via the shared :func:`message_content_to_text` helper; falls back
    to the last message of any type when no AIMessage is present. Returns a
    sentinel string (``"No response generated"``) when there is nothing to
    extract — including when the shared helper yields an empty string — so
    callers never confuse a missing result with a legitimately empty one.

    Used on both the normal-completion path and the max-turns path
    (#3875 Phase 2): when ``recursion_limit`` aborts the run mid-flight,
    ``final_state`` holds the last chunk streamed before the limit fired, so
    this recovers the partial work instead of dropping it.
    """
    if final_state is None:
        logger.warning(f"[trace={trace_id}] Subagent {name} no final state")
        return "No response generated"

    messages = final_state.get("messages", [])
    logger.info(f"[trace={trace_id}] Subagent {name} final messages count: {len(messages)}")

    last_ai_message = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_message = msg
            break

    if last_ai_message is not None:
        text = message_content_to_text(last_ai_message.content)
        return text if text else "No response generated"

    if messages:
        last_message = messages[-1]
        logger.warning(f"[trace={trace_id}] Subagent {name} no AIMessage found, using last message: {type(last_message)}")
        raw_content = last_message.content if hasattr(last_message, "content") else str(last_message)
        text = message_content_to_text(raw_content)
        return text if text else "No response generated"

    logger.warning(f"[trace={trace_id}] Subagent {name} no messages in final state")
    return "No response generated"


def _extract_llm_error_fallback(final_state: Any) -> str | None:
    """Return the user-facing error for a terminal LLM fallback message.

    ``LLMErrorHandlingMiddleware`` converts provider exceptions into marked
    ``AIMessage`` objects so the graph can terminate cleanly. Clean graph
    termination is not task success, however: subagent callers need the
    structured marker translated into the existing failed terminal state.

    Only the last assistant message is authoritative, and scanning just the
    tail (rather than all messages) is deliberate. Subagents share the
    parent's ``thread_id`` (see ``_aexecute``'s ``run_config``), and LangGraph
    replays the full parent message history through ``stream_mode="values"``,
    so ``final_state`` can contain a *stale* fallback marker left by an earlier
    parent-history turn. The lead-agent run path scans every message and must
    mask those stale markers via ``pre_existing_message_ids``
    (``runtime/runs/worker.py::_extract_llm_error_fallback_message``). Here no
    masking is needed: a fallback ``AIMessage`` carries no ``tool_calls``, so it
    always terminates the run, and a subagent always appends at least its own
    terminal assistant message — the last ``AIMessage`` is therefore never a
    stale parent-history marker. Do not "fix" this by scanning all messages;
    that reintroduces the stale-marker false positive worker.py guards against.

    Error-looking message text without the marker remains ordinary output.
    """
    if final_state is None:
        return None

    for message in reversed(final_state.get("messages", [])):
        if not isinstance(message, AIMessage):
            continue

        metadata = message.additional_kwargs
        if metadata.get("deerflow_error_fallback") is not True:
            return None

        content = message_content_to_text(message.content).strip()
        if content:
            return content

        # Defensive: ``_build_error_fallback_message`` always sets a non-empty
        # user-facing ``content`` (and ``error_detail`` via ``_extract_error_detail``,
        # which falls back to the exception class name). These branches only
        # guard against a future middleware that emits an empty fallback.
        detail = metadata.get("error_detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return "LLM request failed"

    return None


# Global storage for background task results
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

_background_futures: dict[str, Future[SubagentResult]] = {}


def _harvest_tool_receipts(
    final_state: Any,
    *,
    prefer_citing_turn: bool = False,
) -> list[dict[str, Any]] | None:
    """Harvest the child's tool receipts from its terminal message stream.

    Lazy import: the executor package is imported in cycles with
    ``deerflow.agents``; resolving ``tool_receipt`` at call time keeps module
    init order-independent. Failure-isolated: a harvest error can never
    change the run's outcome — the parent simply gets no receipts.
    """
    if not final_state:
        return None
    messages = final_state.get("messages") if isinstance(final_state, dict) else None
    if not messages:
        return None
    try:
        from deerflow.agents.middlewares.tool_receipt import extract_citing_turn_receipts, extract_tool_receipts

        message_list = list(messages)
        # Completed result text comes from the latest assistant turn even when
        # a max-turn chunk ends in a ToolMessage. Its bounded ledger remains
        # authoritative for citation verification. Tool-ended running,
        # cancelled, or failed evidence instead prefers the latest tool scan so
        # newly executed calls are not lost merely because no later assistant
        # turn was produced.
        citing_messages = message_list if prefer_citing_turn else [message_list[-1]]
        citing_turn_receipts = extract_citing_turn_receipts(citing_messages) if prefer_citing_turn or isinstance(message_list[-1], AIMessage) else None
        if prefer_citing_turn:
            # Missing/malformed completed-turn snapshots fail closed. Falling
            # back to the current ToolMessage scan can renumber compacted
            # receipts or reintroduce entries omitted from the model's budget.
            receipts = citing_turn_receipts
        else:
            receipts = citing_turn_receipts if citing_turn_receipts is not None else extract_tool_receipts(message_list)
        if receipts is None:
            return None
        return [dict(receipt) for receipt in receipts]
    except Exception:
        logger.warning("Failed to harvest subagent tool receipts", exc_info=True)
        return None


# Persistent event loop for isolated subagent executions triggered from an
# already-running parent loop. Reusing one long-lived loop avoids creating a
# fresh loop per execution and then closing async resources bound to it.
_isolated_subagent_loop: asyncio.AbstractEventLoop | None = None
_isolated_subagent_loop_thread: threading.Thread | None = None
_isolated_subagent_loop_started: threading.Event | None = None
_isolated_subagent_loop_lock = threading.Lock()


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


def _shutdown_isolated_subagent_loop() -> None:
    """Stop and close the persistent isolated subagent loop."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started

    with _isolated_subagent_loop_lock:
        loop = _isolated_subagent_loop
        thread = _isolated_subagent_loop_thread
        _isolated_subagent_loop = None
        _isolated_subagent_loop_thread = None
        _isolated_subagent_loop_started = None

    if loop is None:
        return

    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)

    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1)

    thread_stopped = thread is None or not thread.is_alive()
    loop_stopped = not loop.is_running()

    if not loop.is_closed():
        if thread_stopped and loop_stopped:
            loop.close()
        else:
            logger.warning(
                "Skipping close of isolated subagent loop because shutdown did not complete within timeout (thread_alive=%s, loop_running=%s)",
                thread is not None and thread.is_alive(),
                loop.is_running(),
            )


atexit.register(_shutdown_isolated_subagent_loop)


def _get_isolated_subagent_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent event loop used by isolated subagent executions."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started
    with _isolated_subagent_loop_lock:
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
                loop.close()
                raise RuntimeError("Timed out starting isolated subagent event loop")
            _isolated_subagent_loop = loop
            _isolated_subagent_loop_thread = thread
            _isolated_subagent_loop_started = started_event

        if _isolated_subagent_loop is None:
            raise RuntimeError("Isolated subagent event loop is not initialized")
        return _isolated_subagent_loop


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


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    """Filter tools based on subagent configuration.

    Args:
        all_tools: List of all available tools.
        allowed: Optional allowlist of tool names. If provided, only these tools are included.
        disallowed: Optional denylist of tool names. These tools are always excluded.

    Returns:
        Filtered list of tools.
    """
    filtered = all_tools

    # Apply allowlist if specified
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # Apply denylist
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        app_config: AppConfig | None = None,
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        oauth_provider: str | None = None,
        oauth_id: str | None = None,
        run_id: str | None = None,
        channel_user_id: str | None = None,
        is_internal: bool = False,
        authz_attributes: Mapping[str, Any] | None = None,
        deerflow_trace_id: str | None = None,
        extensions: Any | None = None,
        execution_capacity: SubagentExecutionCapacity | None = None,
    ):
        """Initialize the executor.

        Args:
            config: Subagent configuration.
            tools: List of all available tools (will be filtered).
            app_config: Resolved AppConfig. When None, ``_create_agent`` falls
                back to ``get_app_config()`` (matches the lead-agent factory's
                pattern).
            parent_model: The parent agent's model name for inheritance.
            sandbox_state: Sandbox state from parent agent.
            thread_data: Thread data from parent agent.
            thread_id: Thread ID for sandbox operations.
            trace_id: Trace ID from parent for distributed tracing.
            user_id: User ID captured from the parent tool's runtime context.
                When None, the tracing layer falls back to DEFAULT_USER_ID.
            user_role: Authenticated user's role, propagated so GuardrailMiddleware
                on the subagent can apply role-aware policy to delegated calls.
            oauth_provider: External identity provider, when authenticated via SSO.
            oauth_id: Subject id at the external identity provider.
            run_id: Parent run id, so delegated guardrail decisions attribute to
                the same run as the lead agent.
            deerflow_trace_id: DeerFlow request-level correlation id propagated
                from the parent run for Langfuse metadata correlation.
            extensions: The parent run's immutable ``LoadedExtensions`` snapshot,
                captured at ``task_tool`` dispatch. When None (embedded client,
                standalone LangGraph Server), ``_aexecute`` falls back to the
                process-wide singleton.
            execution_capacity: Optional explicitly shared admission controller.
                Direct ``create_deerflow_agent`` callers pass one through their
                ``SubagentRuntime``; application factories fall back to the
                startup-configured process singleton.
        """
        self.config = config
        self.app_config = app_config
        self._resolved_app_config = app_config
        self.parent_model = parent_model
        # Resolve eagerly only when it does not require loading config.yaml; otherwise defer
        # to _create_agent (which already loads app_config) so unit tests can construct
        # executors without a config file present.
        if config.model != "inherit" or parent_model is not None or app_config is not None:
            self.model_name: str | None = resolve_subagent_model_name(config, parent_model, app_config=app_config)
        else:
            self.model_name = None
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # Generate trace_id if not provided (for top-level calls)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.user_id = user_id
        # Guardrail attribution propagated from the parent runtime context.
        self.user_role = user_role
        self.oauth_provider = oauth_provider
        self.oauth_id = oauth_id
        self.run_id = run_id
        # IM-channel sender identity captured at task_tool dispatch: group
        # chats share one thread across senders, so delegated bash commands
        # must export the dispatching turn's id, not none at all.
        self.channel_user_id = channel_user_id
        # Authorization identity propagated from the parent runtime context.
        # is_internal is written unconditionally (including False) so the
        # subagent's GuardrailMiddleware sees the same provenance as the lead.
        self.is_internal = is_internal
        self.authz_attributes = normalize_authz_attributes(authz_attributes)
        self.deerflow_trace_id = deerflow_trace_id
        # Parent run's extension snapshot. Binding it here (rather than reading
        # the singleton at execution time) is what keeps one run on a single
        # extension generation: a concurrent ``set_loaded_extensions()`` between
        # the lead run's start and this subagent's execution must not swap the
        # generation underneath the delegated work.
        self.extensions = extensions
        self.execution_capacity = execution_capacity

        self._base_tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )
        self.tools = self._base_tools
        # Populated from the same per-user, config-filtered registry used to
        # build the prompt. Runtime skill activation/policy middleware receives
        # this exact set so a subagent cannot activate an undisclosed skill.
        self._available_skill_names: set[str] = set()
        # Guard middlewares that expose ``consume_stop_reason`` (currently
        # ``TokenBudgetMiddleware`` and ``LoopDetectionMiddleware``), captured in
        # ``_create_agent`` so ``_aexecute`` can read each after the run and
        # surface whichever cap fired (token_capped / loop_capped) to the lead
        # (#3875 Phase 2). Collected as a list — every guard must be checked,
        # not just the first — because the v2 contract advertises more than one
        # cap reason.
        self._stop_reason_middlewares: list[Any] = []
        # What this subagent was assembled from, published to extension
        # observers at the end of ``_create_agent``. The prompt and skill set
        # are captured while ``_build_initial_state`` renders them because
        # neither is recoverable from the compiled graph afterwards.
        self.assembly_descriptor: Any | None = None
        self._assembled_system_prompt = self.config.system_prompt or ""
        self._assembled_skills: list[Any] = []

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _get_resolved_app_config(self) -> AppConfig:
        """Return the one AppConfig snapshot used throughout this execution."""
        if self._resolved_app_config is None:
            self._resolved_app_config = get_app_config()
        return self._resolved_app_config

    def _create_agent(
        self,
        tools: list[BaseTool] | None = None,
        *,
        deferred_setup: "DeferredToolSetup | None" = None,
        extensions=None,
    ):
        """Create the agent instance.

        ``deferred_setup`` (assembled in ``_build_initial_state``) carries the
        deferred MCP tool names + catalog hash so the subagent gets the same
        DeferredToolFilterMiddleware the lead agent has. ``None`` is a no-op.
        """
        app_config = self._get_resolved_app_config()
        if self.model_name is None:
            self.model_name = resolve_subagent_model_name(self.config, self.parent_model, app_config=app_config)
        model = create_chat_model(name=self.model_name, thinking_enabled=False, app_config=app_config, attach_tracing=False)

        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        # Reuse shared middleware composition with lead agent. ``agent_name``
        # lets the builder resolve the per-agent token_budget override.
        mcp_routing_middleware = None
        if deferred_setup is not None and deferred_setup.deferred_names:
            from deerflow.tools.builtins.tool_search import build_mcp_routing_middleware

            mcp_routing_middleware = build_mcp_routing_middleware(
                tools if tools is not None else self.tools,
                deferred_setup,
                top_k=app_config.tool_search.auto_promote_top_k,
            )
        middleware_kwargs = {
            "app_config": app_config,
            "model_name": self.model_name,
            "lazy_init": True,
            "deferred_setup": deferred_setup,
            "agent_name": self.config.name,
            "available_skills": self._available_skill_names,
            "user_id": self.user_id or DEFAULT_USER_ID,
        }
        if extensions is not None:
            middleware_kwargs["extensions"] = extensions
        authz_provider = getattr(self, "_authz_provider", None)
        if authz_provider is not None:
            middleware_kwargs["authorization_provider"] = authz_provider
        if mcp_routing_middleware is not None:
            middleware_kwargs["mcp_routing_middleware"] = mcp_routing_middleware
        middlewares = build_subagent_runtime_middlewares(**middleware_kwargs)
        # Collect every guard middleware that exposes ``consume_stop_reason``
        # (TokenBudgetMiddleware, LoopDetectionMiddleware) so _aexecute can read
        # each after the run and surface whichever cap fired. Duck-typed
        # (``hasattr``) so this file needs no import of the middleware classes;
        # a list (not ``next(...)``) so every guard is checked and a later one
        # is picked up automatically.
        self._stop_reason_middlewares = [m for m in middlewares if hasattr(m, "consume_stop_reason")]

        # system_prompt is included in initial state messages (see _build_initial_state)
        # to avoid multiple SystemMessages which some LLM APIs don't support.
        bound_tools = list(tools if tools is not None else self.tools)
        agent = create_agent(
            model=model,
            tools=bound_tools,
            middleware=middlewares,
            system_prompt=None,
            state_schema=ThreadState,
            checkpointer=False,
        )
        self._describe_assembly(
            app_config=app_config,
            tools=bound_tools,
            middlewares=middlewares,
            deferred_setup=deferred_setup,
            extensions=extensions if extensions is not None else self.extensions,
        )
        return agent

    def _describe_assembly(
        self,
        *,
        app_config: Any,
        tools: list[Any],
        middlewares: list[Any],
        deferred_setup: "DeferredToolSetup | None",
        extensions: Any | None,
    ) -> None:
        """Record and publish what this subagent was assembled from.

        Fail-open: a subagent that cannot describe itself must still run.
        Building the descriptor hashes every tool's description and JSON
        schema and probes every middleware, so it is skipped entirely when no
        observer is registered to receive it.
        """
        if not getattr(extensions, "has_agent_assembly_observers", False):
            return

        from types import SimpleNamespace

        from deerflow.agents.assembly_descriptor import build_assembly_descriptor
        from deerflow.extensions.notify import notify_agent_assembled

        try:
            get_model_config = getattr(app_config, "get_model_config", None)
            model_config = get_model_config(self.model_name) if callable(get_model_config) else None
            if model_config is None:
                # A name the profile table does not know still has an identity;
                # a missing profile must not blank out the whole descriptor.
                model_config = SimpleNamespace(
                    model=self.model_name,
                    use="unknown",
                    supports_thinking=False,
                    supports_reasoning_effort=False,
                    supports_vision=False,
                )
            deferred_names = deferred_setup.deferred_names if deferred_setup is not None else frozenset()
            descriptor = build_assembly_descriptor(
                namespace="deerflow",
                agent_name=self.config.name,
                requested_model=(self.config.model if self.config.model != "inherit" else self.parent_model),
                effective_model=self.model_name,
                model_config=model_config,
                thinking_enabled=False,
                reasoning_effort=None,
                rendered_base_prompt=self._assembled_system_prompt,
                prompt_template_id="deerflow-subagent-v1",
                tools=tools,
                middlewares=middlewares,
                deferred_names=deferred_names,
                enabled_skills=self._assembled_skills,
                effective_policies={
                    "max_turns": self.config.max_turns,
                    "timeout_seconds": self.config.timeout_seconds,
                    "tool_allowlist": self.config.tools,
                    "tool_denylist": self.config.disallowed_tools,
                    "deferred_tools": {
                        "enabled": bool(deferred_names),
                        "catalog_hash": (deferred_setup.catalog_hash if deferred_setup is not None else None),
                    },
                },
            )
        except Exception:
            logger.warning(
                "[trace=%s] Could not describe subagent %s assembly",
                self.trace_id,
                self.config.name,
                exc_info=True,
            )
            return
        self.assembly_descriptor = descriptor
        notify_agent_assembled(descriptor, extensions)

    def _consume_guard_stop_reason(self) -> str | None:
        """Pop and return the guard-cap stop reason set during the last run.

        Checks every guard middleware that exposes ``consume_stop_reason``
        (collected in :meth:`_create_agent`) and returns the first non-``None``
        reason — ``"token_capped"`` when the token-budget hard stop fired,
        ``"loop_capped"`` when loop detection forced a stop, otherwise ``None``.
        Each guard's cap does not raise (the run still completes with a final
        answer), so this is how the executor learns a completion was actually
        capped. Typically at most one guard fires per run, but checking all of
        them keeps the contract's full cap vocabulary reachable.
        """
        for mw in self._stop_reason_middlewares:
            reason = mw.consume_stop_reason(self.run_id)
            if reason is not None:
                return reason
        return None

    async def _load_skills(self) -> list[Skill]:
        """Load enabled skill metadata based on config.skills."""
        if self.config.skills is not None and len(self.config.skills) == 0:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} skills=[] — skipping skill loading")
            return []

        try:
            from deerflow.skills.storage import get_or_new_user_skill_storage

            storage_kwargs = {"app_config": self.app_config} if self.app_config is not None else {}
            storage = await asyncio.to_thread(
                get_or_new_user_skill_storage,
                self.user_id or DEFAULT_USER_ID,
                **storage_kwargs,
            )
            # Use asyncio.to_thread to avoid blocking the event loop (LangGraph ASGI requirement)
            all_skills = await asyncio.to_thread(storage.load_skills, enabled_only=True)
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} loaded {len(all_skills)} enabled skills from disk")
        except Exception:
            logger.exception(f"[trace={self.trace_id}] Failed to load skills for subagent {self.config.name}")
            raise

        if not all_skills:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} no enabled skills found")
            return []

        # Filter by config.skills whitelist
        if self.config.skills is not None:
            allowed = set(self.config.skills)
            return [s for s in all_skills if s.name in allowed]
        return all_skills

    async def _build_initial_state(self, task: str) -> tuple[dict[str, Any], list[BaseTool], "DeferredToolSetup"]:
        """Build the initial state for agent execution.

        Args:
            task: The task description.

        Returns:
            ``(state, final_tools, deferred_setup)``. ``final_tools`` is the
            authorized tool list with discovery helpers appended when their
            deferral modes apply; ``deferred_setup`` is consumed by ``_create_agent``
            so the agent build and the injected ``<available-deferred-tools>``
            section share one catalog/hash.
        """
        # Lazy import: see the TYPE_CHECKING note at the top of this module -
        # importing tool_search runs tools/builtins/__init__, which would
        # re-enter this package during its own initialization.
        from deerflow.tools.builtins.tool_search import assemble_deferred_tools, get_deferred_tools_prompt_section, get_mcp_routing_hints_prompt_section

        # Skills are discoverable metadata until explicitly slash-activated or
        # loaded through read_file. Their allowed-tools declarations are applied
        # dynamically by SkillToolPolicyMiddleware, not eagerly here.
        skills = await self._load_skills()
        self._assembled_skills = list(skills)
        self._available_skill_names = {skill.name for skill in skills}

        resolved_app_config = self._get_resolved_app_config()

        from deerflow.skills.describe import build_skill_search_setup, get_skill_index_prompt_section

        skill_setup = build_skill_search_setup(
            skills,
            enabled=resolved_app_config.skills.deferred_discovery,
            container_base_path=resolved_app_config.skills.container_path,
        )

        # Apply authorization Layer 1: filter tools before deferred assembly
        # so denied tools can never enter the DeferredToolCatalog.
        from deerflow.authz.tool_filter import apply_tool_authorization

        authz_context = {
            "user_id": self.user_id,
            "user_role": self.user_role,
            "oauth_provider": self.oauth_provider,
            "oauth_id": self.oauth_id,
            "channel_user_id": self.channel_user_id,
            "is_internal": self.is_internal,
            "authz_attributes": self.authz_attributes,
        }
        authorization_candidates = [*self._base_tools]
        if skill_setup.describe_skill_tool is not None:
            authorization_candidates.append(skill_setup.describe_skill_tool)
        configured_tool_ids = {id(tool) for tool in self._base_tools}
        authorized_tools, self._authz_provider = apply_tool_authorization(
            authorization_candidates,
            context=authz_context,
            app_config=resolved_app_config,
        )
        configured_tools = [tool for tool in authorized_tools if id(tool) in configured_tool_ids]
        late_tools = [tool for tool in authorized_tools if id(tool) not in configured_tool_ids]

        # Assemble deferred tool_search after the subagent's name allow/deny and
        # authorization filters, mirroring the lead path so subagents stop
        # binding full MCP schemas.
        # The generated tool_search helper is intentionally not subject to the
        # subagent's name-level allow/deny (config.tools / disallowed_tools):
        # its catalog is built from that already-filtered list. Active skill
        # policy is applied later by middleware to both schema visibility and
        # execution, so promotion cannot widen an active skill's authority.
        final_tools, deferred_setup = assemble_deferred_tools(
            configured_tools,
            enabled=resolved_app_config.tool_search.enabled,
        )
        final_tools.extend(late_tools)

        # Combine the system prompt and skill discovery metadata into a single
        # SystemMessage. Full SKILL.md bodies are loaded only when activated.
        # Some LLM APIs reject multiple SystemMessages with
        # "System message must be at the beginning."
        system_parts: list[str] = []
        if self.config.system_prompt:
            system_parts.append(self.config.system_prompt)
        if skills:
            if skill_setup.skill_names:
                skills_section = get_skill_index_prompt_section(
                    skill_names=skill_setup.skill_names,
                    container_base_path=resolved_app_config.skills.container_path,
                )
            else:
                # Reuse the lead agent's metadata renderer in legacy discovery
                # mode so both agent types describe the same skill catalog.
                from deerflow.agents.lead_agent.prompt import get_skills_prompt_section

                skills_section = await asyncio.to_thread(
                    get_skills_prompt_section,
                    self._available_skill_names,
                    app_config=resolved_app_config,
                    user_id=self.user_id or DEFAULT_USER_ID,
                )
            if skills_section:
                system_parts.append(skills_section)
        # Name the deferred MCP tools in the prompt; their schemas stay withheld
        # until tool_search promotes them. Empty set -> "" -> appends nothing.
        deferred_section = get_deferred_tools_prompt_section(deferred_names=deferred_setup.deferred_names)
        if deferred_section:
            system_parts.append(deferred_section)
        mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(authorized_tools, deferred_names=deferred_setup.deferred_names)
        if mcp_routing_hints_section:
            system_parts.append(mcp_routing_hints_section)

        messages: list[Any] = []
        if system_parts:
            self._assembled_system_prompt = "\n\n".join(system_parts)
            messages.append(SystemMessage(content=self._assembled_system_prompt))

        # Then the actual task
        messages.append(HumanMessage(content=task))

        state: dict[str, Any] = {
            "messages": messages,
        }

        # Pass through sandbox and thread data from parent
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state, final_tools, deferred_setup

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute after acquiring the process-wide native-subagent slot."""
        result = result_holder
        if result is None:
            result = SubagentResult(
                task_id=str(uuid.uuid4())[:8],
                trace_id=self.trace_id,
                status=SubagentStatus.PENDING,
            )
        try:
            capacity = self.execution_capacity or get_subagent_execution_capacity()
            async with capacity.slot():
                with result._state_lock:
                    if not result.status.is_terminal:
                        result.status = SubagentStatus.RUNNING
                        result.started_at = datetime.now()
                return await self._aexecute_admitted(task, result)
        except SubagentCapacityError as exc:
            result.try_set_terminal(
                SubagentStatus.FAILED,
                error=str(exc),
                admission_failure=True,
            )
            return result

    async def _aexecute_admitted(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task asynchronously.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """
        if result_holder is not None:
            # Use the provided result holder (for async execution with real-time updates)
            result = result_holder
        else:
            # Create a new result for synchronous execution
            task_id = str(uuid.uuid4())[:8]
            result = SubagentResult(
                task_id=task_id,
                trace_id=self.trace_id,
                status=SubagentStatus.RUNNING,
                started_at=datetime.now(),
            )
        from deerflow_extension_api import ExtensionData, TaskInfo

        from deerflow.extensions import get_loaded_extensions
        from deerflow.extensions.notify import (
            lead_task_id,
            notify_task_start,
            notify_task_stop,
            subagent_task_outcome,
        )

        loaded_extensions = self.extensions if self.extensions is not None else get_loaded_extensions()
        task_store: ExtensionData | None = None
        task_info: TaskInfo | None = None
        if loaded_extensions.needs_task_store:
            task_store = ExtensionData(result.external_task_id or result.task_id)
        if loaded_extensions.has_task_lifecycle and self.run_id:
            task_info = TaskInfo(
                task_id=result.task_id,
                run_id=self.run_id,
                thread_id=self.thread_id or "",
                kind="subagent",
                parent_task_id=lead_task_id(self.run_id),
                agent_name=self.config.name,
            )
            assert task_store is not None
        elif loaded_extensions.has_task_lifecycle:
            logger.debug(
                "[trace=%s] Subagent %s has no run_id; skipping extension task lifecycle",
                self.trace_id,
                self.config.name,
            )
        ai_messages = result.ai_messages
        if ai_messages is None:
            ai_messages = []
            result.ai_messages = ai_messages
        # O(1) duplicate detection for streamed AI messages. ``stream_mode="values"``
        # re-yields the full state every super-step, so the same trailing message is
        # re-examined on each chunk; an id-keyed set keeps that check O(1) instead of
        # rescanning the append-only ``ai_messages`` list (O(n) per chunk -> O(n^2)
        # over a run, which reaches max_turns=150 for deep-research subagents).
        seen_message_ids: set[str] = {mid for msg in ai_messages if (mid := msg.get("id"))}
        # Cursor into the append-only message history so each ``values``-mode
        # chunk only re-scans the newly-appended tail (see capture_new_step_messages).
        processed_message_count = 0

        collector: SubagentTokenCollector | None = None
        final_state = None
        verification_cfg = getattr(self._get_resolved_app_config(), "verification", None)

        def terminal_receipts(*, prefer_citing_turn: bool = False) -> list[dict[str, Any]] | None:
            if not getattr(verification_cfg, "receipts_enabled", True):
                return None
            return _harvest_tool_receipts(final_state, prefer_citing_turn=prefer_citing_turn)

        try:
            if task_info is not None and task_store is not None:
                await notify_task_start(
                    loaded_extensions,
                    task_store,
                    task_info,
                    timeout=_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS,
                )
            if result.cancel_event.is_set():
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    tool_receipts=terminal_receipts(),
                )
                return result

            state, final_tools, deferred_setup = await self._build_initial_state(task)
            agent = self._create_agent(
                final_tools,
                deferred_setup=deferred_setup,
                extensions=loaded_extensions,
            )

            # Token collector for subagent LLM calls
            collector_caller = f"subagent:{self.config.name}"
            collector = SubagentTokenCollector(caller=collector_caller)

            # Do not put checkpoint coordinates (thread_id/checkpoint_ns/etc.)
            # in the child config. LangGraph inherits those coordinates from
            # the ambient parent run so this execution keeps its subgraph
            # namespace. Business consumers receive thread_id via ``context``
            # below instead.
            run_config: RunnableConfig = {
                "recursion_limit": self.config.max_turns,
                "callbacks": [collector],
                "tags": [collector_caller],
            }

            # Inject tracing callbacks at the graph level so a single subagent run
            # produces one trace with all node / LLM / tool calls as child spans.
            # This mirrors the lead agent pattern: graph-level tracing paired with
            # attach_tracing=False on the model avoids double-counted traces.
            tracing_callbacks = build_tracing_callbacks()
            if tracing_callbacks:
                existing_callbacks = list(run_config.get("callbacks") or [])
                run_config["callbacks"] = [*existing_callbacks, *tracing_callbacks]

            # Normalize subagent name for tracing so it matches the lead-agent
            # naming shape (lowercase, hyphens only). Inline because there is no
            # shared helper — runtime/runs/naming.py only handles lead-agent runs.
            if self.config.name:
                normalized_name = self.config.name.strip().lower().replace("_", "-")
                assistant_id = f"subagent:{normalized_name}"
            else:
                assistant_id = "subagent"

            # Inject Langfuse trace-attribute metadata so the subagent trace
            # links to the parent thread and carries the correct session/user IDs.
            inject_langfuse_metadata(
                run_config,
                thread_id=self.thread_id,
                user_id=self.user_id,
                assistant_id=assistant_id,
                model_name=self.model_name,
                environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
                deerflow_trace_id=self.deerflow_trace_id,
            )

            context: dict[str, Any] = {}
            if self.thread_id:
                context["thread_id"] = self.thread_id
            if self.app_config is not None:
                context["app_config"] = self.app_config
            # Propagate guardrail attribution so delegated tool calls are
            # evaluated with the parent run's identity (role-aware policy,
            # audit). user_id reuses the resolved tracing id; on every
            # authenticated/IM path this equals the parent context value.
            context["user_id"] = self.user_id
            context["user_role"] = self.user_role
            context["oauth_provider"] = self.oauth_provider
            context["oauth_id"] = self.oauth_id
            context["run_id"] = self.run_id
            if task_store is not None:
                from deerflow_extension_api import EXTENSION_TASK_STORE_KEY

                context[EXTENSION_TASK_STORE_KEY] = task_store
            if self.channel_user_id:
                context["channel_user_id"] = self.channel_user_id
            # Authorization identity: is_internal written unconditionally
            # (including False); attributes copied again on write-back.
            context["is_internal"] = self.is_internal
            context["authz_attributes"] = dict(self.authz_attributes)
            if self.deerflow_trace_id:
                context[DEERFLOW_TRACE_METADATA_KEY] = self.deerflow_trace_id
            context["is_subagent"] = True

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution with max_turns={self.config.max_turns}")

            # Use stream instead of invoke to get real-time updates
            # This allows us to collect AI messages as they are generated

            # Pre-check: bail out immediately if already cancelled before streaming starts
            if result.cancel_event.is_set():
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled before streaming")
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    token_usage_records=collector.snapshot_records(),
                    tool_receipts=terminal_receipts(),
                )
                return result

            async for chunk in agent.astream(state, config=run_config, context=context, stream_mode="values"):  # type: ignore[arg-type]
                # A yielded values chunk is already executed state.  Retain it
                # before observing cooperative cancellation so terminal receipt
                # harvesting includes a tool result that completed while the
                # cancellation request was in flight.
                final_state = chunk
                result.update_tool_receipts(terminal_receipts())

                # Cooperative cancellation: check if parent requested stop.
                # Note: cancellation is only detected at astream iteration boundaries,
                # so long-running tool calls within a single iteration will not be
                # interrupted until the next chunk is yielded.
                if result.cancel_event.is_set():
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled by parent")
                    result.try_set_terminal(
                        SubagentStatus.CANCELLED,
                        error="Cancelled by user",
                        token_usage_records=collector.snapshot_records(),
                        tool_receipts=terminal_receipts(),
                    )
                    return result

                result.update_token_usage_records(collector.snapshot_records())

                # Capture every step message (assistant turns AND tool outputs)
                # appended since the last chunk. A single super-step can append
                # several ToolMessages when the model emits multiple tool calls in
                # one turn, so capturing only messages[-1] would drop all but the
                # last output (#3779). Dedup/serialization live in capture_step_message.
                messages = chunk.get("messages", [])
                previous_count = len(ai_messages)
                processed_message_count = capture_new_step_messages(messages, ai_messages, seen_message_ids, processed_message_count)
                if len(ai_messages) > previous_count:
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured {len(ai_messages) - previous_count} step message(s); total #{len(ai_messages)}")

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")
            token_usage_records = collector.snapshot_records()
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    token_usage_records=token_usage_records,
                    tool_receipts=terminal_receipts(),
                )
            else:
                final_result = _extract_final_result(final_state, trace_id=self.trace_id, name=self.config.name)
                # A guard hard-stop (token budget or loop detection) does not raise
                # — it strips tool_calls so the run completes with a final answer.
                # ``consume_stop_reason`` on each guard tells us whether that
                # happened so we can mark the completed result with the cap reason
                # (token_capped / loop_capped) for the lead (#3875 Phase 2). It
                # pops the reason, so keep it on the branch that consumes it — a
                # fallback carries no tool_calls, so no guard hard-stop can have
                # co-occurred on the FAILED branch anyway.
                stop_reason = self._consume_guard_stop_reason()
                result.try_set_terminal(
                    SubagentStatus.COMPLETED,
                    result=final_result,
                    stop_reason=stop_reason,
                    token_usage_records=token_usage_records,
                    tool_receipts=terminal_receipts(prefer_citing_turn=True),
                )

        except GraphRecursionError:
            # ``recursion_limit`` on run_config == ``self.config.max_turns``
            # (set above). Hitting it means the subagent exhausted its turn
            # budget. Route into the additive ``stop_reason`` channel (#3875
            # Phase 2) rather than a dedicated status enum (which would break v1
            # contract consumers). If the run streamed usable partial work,
            # surface it as ``completed``; otherwise ``failed``. Either way the
            # lead can tell "out of budget" from "broken subagent" without
            # parsing result text.
            #
            # Prefer a guard's stop reason if one already fired this run: a
            # token-budget / loop hard-stop strips tool_calls to force a final
            # answer, and if ``recursion_limit`` then trips on the next
            # super-step before that answer lands, the guard was the binding
            # constraint — not the turn budget. Consulting the guards here (same
            # lookup as the normal-completion path above) keeps the two paths
            # consistent and pops the reason so it is not orphaned in the dict.
            max_turns = self.config.max_turns
            logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} reached max_turns={max_turns} (GraphRecursionError); recovering partial result")
            records = collector.snapshot_records() if collector is not None else None
            stop_reason = self._consume_guard_stop_reason() or "turn_capped"

            # A handled LLM provider failure (#4042) carries non-empty
            # user-facing text on its terminal ``AIMessage`` just like genuine
            # partial output, so it must be checked here too or it is
            # indistinguishable from the raw-text scan below and gets
            # misclassified as a completed task. Consult the same marker the
            # normal-completion path above uses, before falling back to that scan.
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    stop_reason=stop_reason,
                    token_usage_records=records,
                    tool_receipts=terminal_receipts(),
                )
            else:
                messages = (final_state or {}).get("messages", [])
                usable_partial: str | None = None
                for m in reversed(messages):
                    if isinstance(m, AIMessage):
                        text = message_content_to_text(m.content).strip()
                        if text:
                            usable_partial = text
                        break
                if usable_partial is not None:
                    result.try_set_terminal(
                        SubagentStatus.COMPLETED,
                        result=usable_partial,
                        stop_reason=stop_reason,
                        token_usage_records=records,
                        tool_receipts=terminal_receipts(prefer_citing_turn=True),
                    )
                else:
                    result.try_set_terminal(
                        SubagentStatus.FAILED,
                        error=f"Reached max_turns={max_turns}",
                        stop_reason=stop_reason,
                        token_usage_records=records,
                        tool_receipts=terminal_receipts(),
                    )

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
            result.try_set_terminal(
                SubagentStatus.FAILED,
                error=str(e),
                token_usage_records=collector.snapshot_records() if collector is not None else None,
                tool_receipts=terminal_receipts(),
            )

        finally:
            if task_info is not None and task_store is not None:
                try:
                    await notify_task_stop(
                        loaded_extensions,
                        task_store,
                        task_info,
                        subagent_task_outcome(
                            cancelled=result.status is SubagentStatus.CANCELLED,
                            succeeded=result.status is SubagentStatus.COMPLETED,
                        ),
                        timeout=_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS,
                    )
                except Exception:
                    logger.warning(
                        "[trace=%s] Extension task-stop notification failed for subagent %s (non-fatal)",
                        self.trace_id,
                        self.config.name,
                        exc_info=True,
                    )

        return result

    def _execute_in_isolated_loop(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute the subagent on the persistent isolated event loop.

        This method is used by the sync ``execute()`` path when the caller is
        already running inside an event loop. Because ``execute()`` is a sync
        API, this path blocks the caller while the actual coroutine runs on the
        long-lived isolated loop. Reusing that loop keeps shared async clients
        from being tied to a short-lived loop that gets closed per execution.
        """
        future: Future[SubagentResult] | None = None
        parent_context = _copy_isolated_subagent_context()
        try:
            future = _submit_to_isolated_loop_in_context(
                parent_context,
                lambda: self._aexecute(task, result_holder),
            )
            return future.result(timeout=self.config.timeout_seconds)
        except FuturesTimeoutError:
            if result_holder is not None:
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
        try:
            return self._execute_in_isolated_loop(task, result_holder)
        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            # Create a result with error if we don't have one
            if result_holder is not None:
                result = result_holder
            else:
                result = SubagentResult(
                    task_id=str(uuid.uuid4())[:8],
                    trace_id=self.trace_id,
                    status=SubagentStatus.RUNNING,
                )
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
        execution_id = str(uuid.uuid4())

        # Create initial pending result
        result = SubagentResult(
            task_id=execution_id,
            external_task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
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

        async def run_with_timeout() -> SubagentResult:
            try:
                return await asyncio.wait_for(
                    self._aexecute(task, result),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError:
                result.cancel_event.set()
                result.try_set_terminal(
                    SubagentStatus.TIMED_OUT,
                    error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                    tool_receipts=result.snapshot_tool_receipts(),
                )
                return result
            except asyncio.CancelledError:
                result.cancel_event.set()
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    tool_receipts=result.snapshot_tool_receipts(),
                )
                return result
            except Exception as exc:
                logger.exception("[trace=%s] Subagent %s async execution failed", self.trace_id, self.config.name)
                result.try_set_terminal(SubagentStatus.FAILED, error=str(exc))
                return result

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

        def forget_future(_future: Future[SubagentResult]) -> None:
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


def cleanup_background_task(execution_id: str) -> None:
    """Remove a completed task from background tasks.

    Should be called by task_tool after it finishes polling and returns the result.
    This prevents memory leaks from accumulated completed tasks.

    Only removes tasks that are in a terminal state (COMPLETED/FAILED/TIMED_OUT)
    to avoid race conditions with the background executor still updating the task entry.

    Args:
        execution_id: The execution ID to remove.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(execution_id)
        if result is None:
            # Nothing to clean up; may have been removed already.
            logger.debug("Requested cleanup for unknown background execution %s", execution_id)
            return

        # Only clean up tasks that are in a terminal state to avoid races with
        # the background executor still updating the task entry.
        if result.status.is_terminal or result.completed_at is not None:
            del _background_tasks[execution_id]
            _background_futures.pop(execution_id, None)
            logger.debug("Cleaned up background execution: %s", execution_id)
        else:
            logger.debug(
                "Skipping cleanup for non-terminal background execution %s (status=%s)",
                execution_id,
                result.status.value if hasattr(result.status, "value") else result.status,
            )
