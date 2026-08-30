"""Task tool for delegating work to subagents."""

import asyncio
import logging
import uuid
from contextvars import ContextVar
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated, Any, cast

from langchain.tools import InjectedToolCallId, tool
from langchain_core.callbacks import BaseCallbackManager
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command

from deerflow.agents.middlewares.receipt_verification import verify_receipt_citations
from deerflow.authz.principal import normalize_authz_attributes
from deerflow.config import get_app_config
from deerflow.extensions import resolve_run_extensions
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.security import LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE, is_host_bash_allowed
from deerflow.subagents import SubagentExecutor, get_available_subagent_names, get_subagent_config
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.config import resolve_subagent_model_name
from deerflow.subagents.executor import (
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
    request_cancel_background_task,
)
from deerflow.subagents.status_contract import (
    SubagentStatusValue,
    SubagentStopReasonValue,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)
from deerflow.tools.types import Runtime
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id
from deerflow.utils.custom_events import aemit_custom_event

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_explicit_execution_capacity: ContextVar[SubagentExecutionCapacity | None] = ContextVar(
    "deerflow_explicit_subagent_execution_capacity",
    default=None,
)
_explicit_app_config: ContextVar[Any | None] = ContextVar(
    "deerflow_explicit_subagent_app_config",
    default=None,
)


def _is_subagent_terminal(result: Any) -> bool:
    """Return whether a background subagent result is safe to clean up."""
    return result.status in {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT} or getattr(result, "completed_at", None) is not None


async def _await_subagent_terminal(execution_id: str, max_polls: int) -> Any | None:
    """Poll until the background subagent reaches a terminal status or we run out of polls."""
    for _ in range(max_polls):
        result = get_background_task_result(execution_id)
        if result is None:
            return None
        if _is_subagent_terminal(result):
            return result
        await asyncio.sleep(5)
    return None


async def _deferred_cleanup_subagent_task(execution_id: str, trace_id: str, max_polls: int) -> None:
    """Keep polling a cancelled subagent until it can be safely removed."""
    cleanup_poll_count = 0
    while True:
        result = get_background_task_result(execution_id)
        if result is None:
            return
        if _is_subagent_terminal(result):
            cleanup_background_task(execution_id)
            return
        if cleanup_poll_count >= max_polls:
            logger.warning(f"[trace={trace_id}] Deferred cleanup for execution {execution_id} timed out after {cleanup_poll_count} polls")
            return
        await asyncio.sleep(5)
        cleanup_poll_count += 1


def _log_cleanup_failure(cleanup_task: asyncio.Task[None], *, trace_id: str, execution_id: str) -> None:
    if cleanup_task.cancelled():
        return

    exc = cleanup_task.exception()
    if exc is not None:
        logger.error(f"[trace={trace_id}] Deferred cleanup failed for execution {execution_id}: {exc}")


_deferred_cleanup_tasks: set[asyncio.Task[None]] = set()


def bind_task_tool(
    execution_capacity: SubagentExecutionCapacity,
    *,
    app_config: "AppConfig | None" = None,
):
    """Return a task tool bound to one explicit SDK runtime capacity.

    The copied tool keeps the original name, description, and argument schema;
    only its coroutine is wrapped. ``ContextVar`` keeps concurrent direct
    factories isolated while the resolved capacity is passed into the executor
    before work crosses to the persistent subagent event loop.
    """

    original_coroutine = task_tool.coroutine
    if original_coroutine is None:  # pragma: no cover - task_tool is async by contract
        raise RuntimeError("task tool has no async implementation")

    async def bound_coroutine(**kwargs):
        capacity_token = _explicit_execution_capacity.set(execution_capacity)
        config_token = _explicit_app_config.set(app_config)
        try:
            return await original_coroutine(**kwargs)
        finally:
            _explicit_app_config.reset(config_token)
            _explicit_execution_capacity.reset(capacity_token)

    return task_tool.model_copy(update={"coroutine": bound_coroutine})


def _schedule_deferred_subagent_cleanup(execution_id: str, trace_id: str, max_polls: int) -> asyncio.Task[None]:
    logger.debug(f"[trace={trace_id}] Scheduling deferred cleanup for cancelled execution {execution_id}")
    cleanup_task = asyncio.create_task(_deferred_cleanup_subagent_task(execution_id, trace_id, max_polls))
    _deferred_cleanup_tasks.add(cleanup_task)
    cleanup_task.add_done_callback(_deferred_cleanup_tasks.discard)
    cleanup_task.add_done_callback(lambda task: _log_cleanup_failure(task, trace_id=trace_id, execution_id=execution_id))
    return cleanup_task


def _find_usage_recorder(runtime: Any) -> Any | None:
    """Find a callback handler with ``record_external_llm_usage_records`` in the runtime config.

    LangChain may pass ``config["callbacks"]`` in three different shapes:

    - ``None`` (no callbacks registered): no recorder.
    - A plain ``list[BaseCallbackHandler]``: iterate it directly.
    - A ``BaseCallbackManager`` instance (e.g. ``AsyncCallbackManager`` on async
      tool runs): managers are not iterable, so we unwrap ``.handlers`` first.

    Any other shape (e.g. a single handler object accidentally passed without a
    list wrapper) cannot be iterated safely; treat it as "no recorder" rather
    than raise.
    """
    if runtime is None:
        return None
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return None
    callbacks = config.get("callbacks")
    if isinstance(callbacks, BaseCallbackManager):
        callbacks = callbacks.handlers
    if not callbacks:
        return None
    if not isinstance(callbacks, list):
        return None
    for cb in callbacks:
        if hasattr(cb, "record_external_llm_usage_records"):
            return cb
    return None


def _summarize_usage(records: list[dict] | None) -> dict | None:
    """Summarize token usage records into a compact dict for SSE events."""
    if not records:
        return None
    return {
        "input_tokens": sum(r.get("input_tokens", 0) or 0 for r in records),
        "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in records),
        "total_tokens": sum(r.get("total_tokens", 0) or 0 for r in records),
    }


def _report_subagent_usage(runtime: Any, result: Any) -> None:
    """Report subagent token usage to the parent RunJournal, if available.

    Each subagent task must be reported only once (guarded by usage_reported).
    """
    if getattr(result, "usage_reported", True):
        return
    records = getattr(result, "token_usage_records", None) or []
    if not records:
        return
    journal = _find_usage_recorder(runtime)
    if journal is None:
        logger.debug("No usage recorder found in runtime callbacks — subagent token usage not recorded")
        return
    try:
        journal.record_external_llm_usage_records(records)
        result.usage_reported = True
    except Exception:
        logger.warning("Failed to report subagent token usage", exc_info=True)


def _get_runtime_app_config(runtime: Any) -> "AppConfig | None":
    explicit = _explicit_app_config.get()
    if explicit is not None:
        return cast("AppConfig", explicit)
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        app_config = context.get("app_config")
        if app_config is not None:
            return cast("AppConfig", app_config)
    return None


def _merge_skill_allowlists(parent: list[str] | None, child: list[str] | None) -> list[str] | None:
    """Return the effective subagent skill allowlist under the parent policy."""
    if parent is None:
        return child
    if child is None:
        return list(parent)

    parent_set = set(parent)
    return [skill for skill in child if skill in parent_set]


def _task_result_command(
    *,
    tool_call_id: str,
    status: SubagentStatusValue,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
    model_name: str | None = None,
    usage: dict[str, int] | None = None,
    tool_receipts: list[dict] | None = None,
    receipt_verdict: dict | None = None,
) -> Command:
    content, metadata_error = format_subagent_result_message(status, result=result, error=error, stop_reason=stop_reason)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name="task",
                    additional_kwargs=make_subagent_additional_kwargs(
                        status,
                        result=result,
                        error=metadata_error,
                        stop_reason=stop_reason,
                        model_name=model_name,
                        token_usage=usage,
                        tool_receipts=tool_receipts,
                        receipt_verdict=receipt_verdict,
                    ),
                )
            ]
        }
    )


@tool("task", parse_docstring=True)
async def task_tool(
    runtime: Runtime,
    description: str,
    prompt: str,
    subagent_type: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    *,
    acceptance_criteria: list[str] | None = None,
) -> str | Command:
    """Delegate a bounded task to a specialized subagent in its own context.

    Delegate only when expected benefit clearly exceeds delegation overhead.
    Useful benefits are:
    - Material wall-clock savings from independent parallel work
    - Specialist tools, skills, models, or domain instructions
    - Context isolation for a bounded, unusually context-heavy investigation

    Built-in subagent types:
    - **general-purpose**: A capable agent for bounded exploration and action. Use
      when the assignment has clear specialist or context-isolation benefit, or is
      one of several independent, non-overlapping tasks that can actually run in
      parallel.
    - **bash**: Command execution specialist for running bash commands. This is only
      available when host bash is explicitly allowed or when using an isolated shell
      sandbox such as `AioSandboxProvider`. Use it only for a bounded shell workflow
      with clear context-isolation or independent-parallel benefit.
      Routine git, build, test, or deploy operations are not sufficient reason to delegate.

    Additional custom subagent types may be defined in config.yaml under
    `subagents.custom_agents`. Each custom type can have its own system prompt,
    tools, skills, model, and timeout configuration. If an unknown subagent_type
    is provided, the error message will list all available types.

    When to use this tool:
    - Independent tasks that materially reduce wall-clock time when run in parallel
    - A specialist subagent provides capability unavailable on the direct path
    - Bounded exploration that would otherwise displace important parent context

    When NOT to use this tool:
    - Merely because a task is complex, multi-step, verbose, or touches a large repo
    - Splitting dependent steps across parallel subagents; keep the chain together
      and delegate it as one bounded task only when specialist or context-isolation
      benefit clearly wins
    - Parallel work with overlapping files, shared mutable state, or external side effects
    - Tasks requiring user interaction or clarification

    Costs to include in the delegation decision:
    - Repeating the same repository discovery in multiple contexts
    - Coordination, verification, and synthesis of returned results
    - Any task the parent can complete more cheaply with direct tools

    Reading the result (subagent reports are SELF-REPORTS, not verified facts):
    - While receipt verification is enabled (the default; `verification.receipts_enabled`
      in config), the subagent is instructed to cite receipt ids `[rN]` from its
      execution record for every action claim and to attach a verifiable handle
      (absolute path, URL, ID, HTTP status) to every deliverable. In that
      configuration the delegation ledger cross-checks those citations; a
      completed report whose action claims carry no citation is flagged UNVERIFIED.
      When receipt verification is disabled, reports carry no receipt citations
      and no citation verdict — judge them by their verifiable handles alone.
    - A resolved citation means the cited call happened with the recorded status
      — it does not validate that the adjacent claim is correct. Before relying
      on a load-bearing claim, spot-check its verifiable handle yourself.

    Args:
        description: A short (3-5 word) description of the task for logging/display. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent. Be specific and clear about what needs to be done. ALWAYS PROVIDE THIS PARAMETER SECOND.
        subagent_type: The type of subagent to use. ALWAYS PROVIDE THIS PARAMETER THIRD.
        acceptance_criteria: Optional list of completion requirements, handed to
            the subagent as untrusted data appended to its task input (never as
            system-prompt authority) and addressed one by one in its final
            report. Attach them when
            the outcome is objectively checkable; prefer the canonical forms
            `file:<path> exists`, `file:<path> non-empty`, `file_written:<path>`,
            and `tests_passed:<command>` so each criterion stays objectively
            decidable. Example for a report-writing delegation:
            ["file:../outputs/report.md non-empty"]. Omit for open-ended
            exploration where no crisp acceptance condition exists.
    """
    runtime_app_config = _get_runtime_app_config(runtime)
    metadata: dict = runtime.config.get("metadata", {}) if runtime is not None else {}
    allowed_subagents = metadata.get("allowed_subagents")
    if allowed_subagents is None:
        available_subagent_names = get_available_subagent_names(app_config=runtime_app_config) if runtime_app_config is not None else get_available_subagent_names()
    else:
        available_subagent_names = get_available_subagent_names(app_config=runtime_app_config, allowed_subagents=allowed_subagents) if runtime_app_config is not None else get_available_subagent_names(allowed_subagents=allowed_subagents)

    # Preserve the dedicated sandbox-policy guidance before the generic
    # registry/policy membership gate filters bash from the visible catalog.
    if subagent_type == "bash":
        host_bash_allowed = is_host_bash_allowed(runtime_app_config) if runtime_app_config is not None else is_host_bash_allowed()
        if not host_bash_allowed:
            return _task_result_command(
                tool_call_id=tool_call_id,
                status="failed",
                error=LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE,
            )

    # Get subagent configuration
    config = get_subagent_config(subagent_type, app_config=runtime_app_config) if runtime_app_config is not None else get_subagent_config(subagent_type)
    if config is None or subagent_type not in available_subagent_names:
        if available_subagent_names:
            available = ", ".join(available_subagent_names)
        elif allowed_subagents is not None:
            available = "none permitted by caller policy"
        else:
            available = "none"
        error = f"Unknown subagent type '{subagent_type}'. Available: {available}"
        return _task_result_command(
            tool_call_id=tool_call_id,
            status="failed",
            error=error,
        )
    # Build config overrides
    overrides: dict = {}

    # Skills are loaded by SubagentExecutor per-session (aligned with Codex's pattern:
    # each subagent loads its own skills based on config, injected as conversation items).
    # No longer appended to system_prompt here.

    # Extract parent context from runtime
    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    trace_id = None
    user_id = None
    deerflow_trace_id = None
    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            thread_id = runtime.config.get("configurable", {}).get("thread_id")

        # Try to get parent model from configurable
        parent_model = metadata.get("model_name")

        # Get or generate trace_id for distributed tracing
        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    # Get user_id for tracing (uses standard resolution order)
    user_id = resolve_runtime_user_id(runtime)

    # Propagate the authenticated runtime context so delegated tool calls are
    # evaluated by GuardrailMiddleware with the same identity/attribution as
    # the lead agent. Sourced from the server-side context written by
    # inject_authenticated_user_context (and run_id by the run worker); stays
    # None when absent (e.g. internal-auth runs) so guardrail behavior is
    # unchanged. Without this, role-aware policy silently mis-attributes any
    # tool call delegated to a subagent (user_role=None).
    parent_context = runtime.context if runtime is not None else None
    parent_context = parent_context if isinstance(parent_context, dict) else {}
    user_role = parent_context.get("user_role")
    oauth_provider = parent_context.get("oauth_provider")
    oauth_id = parent_context.get("oauth_id")
    run_id = parent_context.get("run_id")
    # IM-channel sender identity: group chats share one thread across senders,
    # so delegated bash commands need the dispatching turn's channel_user_id.
    channel_user_id = parent_context.get("channel_user_id")
    # Propagate authorization identity: is_internal (strict bool) and
    # authz_attributes (validated Mapping, copied). These follow the same
    # server-side provenance as user_role/oauth — see inject_authenticated_user_context.
    is_internal = parent_context.get("is_internal") is True
    authz_attributes = normalize_authz_attributes(parent_context.get("authz_attributes"))
    # The run's immutable extension snapshot, published by the run worker. Stays
    # None outside that path (embedded client, standalone LangGraph Server), where
    # the executor keeps its process-singleton fallback.
    run_extensions = resolve_run_extensions(parent_context)
    deerflow_trace_id = normalize_trace_id(parent_context.get(DEERFLOW_TRACE_METADATA_KEY)) or normalize_trace_id(metadata.get(DEERFLOW_TRACE_METADATA_KEY)) or get_current_trace_id()

    parent_available_skills = metadata.get("available_skills")
    if parent_available_skills is not None:
        overrides["skills"] = _merge_skill_allowlists(list(parent_available_skills), config.skills)

    if overrides:
        config = replace(config, **overrides)

    # Get available tools (excluding task tool to prevent nesting)
    # Lazy import to avoid circular dependency
    from deerflow.tools import get_available_tools

    # Inherit parent agent's tool_groups so subagents respect the same restrictions
    parent_tool_groups = metadata.get("tool_groups")
    resolved_app_config = runtime_app_config
    if config.model == "inherit" and parent_model is None and resolved_app_config is None:
        resolved_app_config = get_app_config()
    effective_model = resolve_subagent_model_name(config, parent_model, app_config=resolved_app_config)

    # Subagents should not have subagent tools enabled (prevent recursive nesting).
    # Subagents also must not get list_uploaded_files — they have an independent
    # ThreadState where runtime.state["uploaded_files"] is absent, so the
    # current-run file exclusion would not work.
    available_tools_kwargs = {
        "model_name": effective_model,
        "groups": parent_tool_groups,
        "subagent_enabled": False,
        "include_upload_tool": False,
    }
    if resolved_app_config is not None:
        available_tools_kwargs["app_config"] = resolved_app_config
    tools = get_available_tools(**available_tools_kwargs)

    # Create executor
    executor_kwargs = {
        "config": config,
        "tools": tools,
        "parent_model": parent_model,
        "sandbox_state": sandbox_state,
        "thread_data": thread_data,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "user_id": user_id,
        "user_role": user_role,
        "oauth_provider": oauth_provider,
        "oauth_id": oauth_id,
        "run_id": run_id,
        "channel_user_id": channel_user_id,
        "is_internal": is_internal,
        "authz_attributes": authz_attributes,
        "deerflow_trace_id": deerflow_trace_id,
        # RFC #4651 PR3: lead-supplied acceptance criteria are handed to the
        # executor, which appends them to the subagent's task HumanMessage as
        # untrusted data (sanitized and boundary-framed by
        # InputSanitizationMiddleware). The subagent's SystemMessage carries
        # only a framework-owned pointer note, so criterion text can never gain
        # system-channel authority over framework instructions.
        "acceptance_criteria": acceptance_criteria,
    }
    if resolved_app_config is not None:
        executor_kwargs["app_config"] = resolved_app_config
    if run_extensions is not None:
        executor_kwargs["extensions"] = run_extensions
    explicit_capacity = _explicit_execution_capacity.get()
    if explicit_capacity is not None:
        executor_kwargs["execution_capacity"] = explicit_capacity
    executor = SubagentExecutor(**executor_kwargs)

    # Keep the provider tool-call ID for stream/message correlation, but use a
    # server-generated execution ID for process-wide background task control.
    execution_id = executor.execute_async(prompt, task_id=tool_call_id)

    # Poll for task completion in backend (removes need for LLM to poll)
    poll_count = 0
    last_status = None
    last_message_count = 0  # Track how many AI messages we've already sent
    # Polling timeout: execution timeout + 60s buffer, checked every 5s
    max_poll_count = (config.timeout_seconds + 60) // 5

    logger.info(f"[trace={trace_id}] Started background task {tool_call_id} (execution_id={execution_id}, subagent={subagent_type}, timeout={config.timeout_seconds}s, polling_limit={max_poll_count} polls)")

    writer = get_stream_writer()
    # Send Task Started message'
    await aemit_custom_event(
        {
            "type": "task_started",
            "task_id": tool_call_id,
            "description": description,
            "model_name": effective_model,
        },
        writer=writer,
    )

    try:
        while True:
            result = get_background_task_result(execution_id)

            if result is None:
                logger.error(f"[trace={trace_id}] Task {tool_call_id} execution {execution_id} not found in background tasks")
                await aemit_custom_event(
                    {"type": "task_failed", "task_id": tool_call_id, "error": "Task disappeared from background tasks"},
                    writer=writer,
                )
                cleanup_background_task(execution_id)
                error = f"Task {tool_call_id} disappeared from background tasks"
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=error,
                )

            # Log status changes for debugging
            if result.status != last_status:
                logger.info(f"[trace={trace_id}] Task {tool_call_id} execution {execution_id} status: {result.status.value}")
                last_status = result.status

            # The collector publishes cumulative records. Reuse one snapshot for
            # both live progress and the terminal event so the frontend can
            # replace, rather than add, its per-task total.
            usage = _summarize_usage(getattr(result, "token_usage_records", None))

            # Check for new AI messages and send task_running events
            ai_messages = result.ai_messages or []
            current_message_count = len(ai_messages)
            if current_message_count > last_message_count:
                # Send task_running event for each new message
                for i in range(last_message_count, current_message_count):
                    message = ai_messages[i]
                    await aemit_custom_event(
                        {
                            "type": "task_running",
                            "task_id": tool_call_id,
                            "message": message,
                            "message_index": i + 1,  # 1-based index for display
                            "total_messages": current_message_count,
                            "usage": usage,
                            "model_name": effective_model,
                        },
                        writer=writer,
                    )
                    logger.info(f"[trace={trace_id}] Task {tool_call_id} sent message #{i + 1}/{current_message_count}")
                last_message_count = current_message_count

            # Check if task completed, failed, or timed out
            if result.status == SubagentStatus.COMPLETED:
                _report_subagent_usage(runtime, result)
                await aemit_custom_event(
                    {
                        "type": "task_completed",
                        "task_id": tool_call_id,
                        "result": result.result,
                        "usage": usage,
                        "model_name": effective_model,
                    },
                    writer=writer,
                )
                logger.info(f"[trace={trace_id}] Task {tool_call_id} completed after {poll_count} polls")
                cleanup_background_task(execution_id)
                # stop_reason carries a guardrail cap (token_capped / turn_capped)
                # when the run was ended early but still produced a final answer
                # — the work survives on result_brief like a clean success.
                # RFC #4651 PR2: cross-check the report's [rN] citations
                # against the harvested receipts once, here — the only point
                # holding the full (untruncated) report text. receipts=None
                # means no harvest happened (receipts_enabled=false, or the
                # run ended before streaming): skip, keeping disabled
                # deployments exactly pre-PR2. An empty list is a real
                # harvest (zero stamped calls) and still gets a verdict.
                receipts = getattr(result, "tool_receipts", None)
                receipt_verdict = verify_receipt_citations(result.result or "", receipts) if receipts is not None else None
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="completed",
                    result=result.result,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                    tool_receipts=receipts,
                    receipt_verdict=receipt_verdict,
                )
            elif result.status == SubagentStatus.FAILED:
                _report_subagent_usage(runtime, result)
                await aemit_custom_event(
                    {
                        "type": "task_failed",
                        "task_id": tool_call_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    },
                    writer=writer,
                )
                logger.error(f"[trace={trace_id}] Task {tool_call_id} failed: {result.error}")
                cleanup_background_task(execution_id)
                # A turn-capped run with no usable output surfaces as failed +
                # stop_reason=turn_capped; the cap note lets the lead tell "out
                # of budget" from "broken subagent".
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=result.error,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                    tool_receipts=getattr(result, "tool_receipts", None),
                )
            elif result.status == SubagentStatus.CANCELLED:
                _report_subagent_usage(runtime, result)
                await aemit_custom_event(
                    {
                        "type": "task_cancelled",
                        "task_id": tool_call_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    },
                    writer=writer,
                )
                logger.info(f"[trace={trace_id}] Task {tool_call_id} cancelled: {result.error}")
                cleanup_background_task(execution_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="cancelled",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                    tool_receipts=getattr(result, "tool_receipts", None),
                )
            elif result.status == SubagentStatus.TIMED_OUT:
                _report_subagent_usage(runtime, result)
                await aemit_custom_event(
                    {
                        "type": "task_timed_out",
                        "task_id": tool_call_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    },
                    writer=writer,
                )
                logger.warning(f"[trace={trace_id}] Task {tool_call_id} timed out: {result.error}")
                cleanup_background_task(execution_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="timed_out",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                    tool_receipts=getattr(result, "tool_receipts", None),
                )

            # Still running, wait before next poll
            await asyncio.sleep(5)
            poll_count += 1

            # Polling timeout as a safety net (in case thread pool timeout doesn't work)
            # Set to execution timeout + 60s buffer, in 5s poll intervals
            # This catches edge cases where the background task gets stuck
            if poll_count > max_poll_count:
                timeout_minutes = config.timeout_seconds // 60
                logger.error(f"[trace={trace_id}] Task {tool_call_id} polling timed out after {poll_count} polls (should have been caught by thread pool timeout)")
                _report_subagent_usage(runtime, result)
                usage = _summarize_usage(getattr(result, "token_usage_records", None))
                await aemit_custom_event(
                    {
                        "type": "task_timed_out",
                        "task_id": tool_call_id,
                        "usage": usage,
                        "model_name": effective_model,
                    },
                    writer=writer,
                )
                # The task may still be running in the background. Signal cooperative
                # cancellation and schedule deferred cleanup to remove the entry from
                # _background_tasks once the background thread reaches a terminal state.
                request_cancel_background_task(execution_id)
                _schedule_deferred_subagent_cleanup(execution_id, trace_id, max_poll_count)
                message = f"Task polling timed out after {timeout_minutes} minutes. This may indicate the background task is stuck. Status: {result.status.value}"
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="polling_timed_out",
                    error=message,
                    model_name=effective_model,
                    usage=usage,
                    tool_receipts=getattr(result, "tool_receipts", None),
                )
    except asyncio.CancelledError:
        # Signal the background subagent thread to stop cooperatively.
        request_cancel_background_task(execution_id)

        # Wait (shielded) for the subagent to reach a terminal state so the
        # final token usage snapshot is reported to the parent RunJournal
        # before the parent worker persists get_completion_data().
        terminal_result = None
        try:
            terminal_result = await asyncio.shield(_await_subagent_terminal(execution_id, max_poll_count))
        except asyncio.CancelledError:
            pass

        # Report whatever the subagent collected (even if we timed out).
        final_result = terminal_result or get_background_task_result(execution_id)
        if final_result is not None:
            _report_subagent_usage(runtime, final_result)
        if final_result is not None and _is_subagent_terminal(final_result):
            cleanup_background_task(execution_id)
        else:
            _schedule_deferred_subagent_cleanup(execution_id, trace_id, max_poll_count)
        raise
