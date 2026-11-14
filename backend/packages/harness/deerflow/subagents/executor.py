"""Subagent execution engine."""

import asyncio
import json
import logging
import os
import sys
import uuid
from collections.abc import Mapping
from contextvars import Context
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from deerflow.agents.middlewares.audit_context import (
    LOOP_DETECTION_RECORDER_CONTEXT_KEY,
    TOOL_PROGRESS_RECORDER_CONTEXT_KEY,
    TOOL_PROMOTION_RECORDER_CONTEXT_KEY,
)
from deerflow.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from deerflow.authz.principal import normalize_authz_attributes
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY, execution_scope
from deerflow.mcp_scope import THREAD_INCARNATION_CONTEXT_KEY
from deerflow.models import create_chat_model
from deerflow.runtime.runs.stream_cleanup import close_agent_stream
from deerflow.runtime.user_context import DEFAULT_USER_ID
from deerflow.skills.types import Skill
from deerflow.subagents.capacity import (
    SubagentExecutionCapacity,
)
from deerflow.subagents.config import SubagentConfig, resolve_subagent_model_name
from deerflow.subagents.context_snapshot import SNAPSHOT_SYSTEM_NOTE, ParentContextSnapshot
from deerflow.subagents.execution import (
    MAX_CONCURRENT_SUBAGENTS as MAX_CONCURRENT_SUBAGENTS,
)
from deerflow.subagents.execution import (
    DelegatedTaskExecutor,
    SubagentResult,
    SubagentStatus,
    _bash_evidence_key,
    _utcnow,
)
from deerflow.subagents.execution import (
    _shutdown_isolated_subagent_loop as _shutdown_isolated_subagent_loop,
)
from deerflow.subagents.execution import (
    cleanup_background_task as cleanup_background_task,
)
from deerflow.subagents.execution import (
    force_cleanup_background_task as force_cleanup_background_task,
)
from deerflow.subagents.execution import (
    get_background_task_result as get_background_task_result,
)
from deerflow.subagents.execution import (
    list_background_tasks as list_background_tasks,
)
from deerflow.subagents.execution import (
    request_cancel_background_task as request_cancel_background_task,
)
from deerflow.subagents.execution import (
    run_on_isolated_subagent_loop as run_on_isolated_subagent_loop,
)
from deerflow.subagents.report_contract import (
    build_acceptance_criteria_system_note,
    build_report_contract_section,
    render_acceptance_criteria_block,
)
from deerflow.subagents.step_events import capture_new_step_messages
from deerflow.subagents.token_collector import SubagentTokenCollector
from deerflow.subagents.turn_budget import find_jumping_hooks, resolve_recursion_limit
from deerflow.subagents.worker_backends import WorkerOutcome
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, resolve_trace_id
from deerflow.tracing import (
    build_tracing_callbacks,
    inject_langfuse_metadata,
)
from deerflow.utils.assembly_io import run_assembly
from deerflow.utils.bash_exit import BASH_TOOL_NAMES, bash_exit_status
from deerflow.utils.messages import message_content_to_text

if TYPE_CHECKING:
    from deerflow.models.reasoning import ResolvedReasoning

    # Imported lazily at runtime inside _build_initial_state: importing
    # tool_search eagerly would run tools/builtins/__init__ -> task_tool ->
    # `from deerflow.subagents import SubagentExecutor`, which re-enters this
    # still-initializing package. Type-only here keeps the annotation precise.
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_EXTENSION_TASK_NOTIFY_TIMEOUT_SECONDS = 3.0
_STREAM_CLOSE_SLOW_WARNING_SECONDS = 10.0
# Kept as wire keys here instead of importing ``deerflow.sandbox`` at module
# load: executor tests and extension embedders replace that package while
# breaking agent/tool import cycles.
_SANDBOX_LEASE_OWNER_CONTEXT_KEY = "sandbox_lease_owner_id"
_SANDBOX_COMMAND_SCOPE_CONTEXT_KEY = "sandbox_command_scope_id"


def _terminal_direct_results(final_state: Any, return_direct_tools: set[str]) -> list[ToolMessage] | None:
    """Match a complete terminal direct-tool batch in call order."""
    if not final_state or not return_direct_tools:
        return None
    messages = final_state.get("messages", [])
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage):
            continue
        calls = message.tool_calls
        if calls and all(call["name"] in return_direct_tools for call in calls):
            results = {item.tool_call_id: item for item in messages[index + 1 :] if isinstance(item, ToolMessage)}
            if all(call["id"] in results for call in calls):
                return [results[call["id"]] for call in calls]
        return None
    return None


def _extract_final_result(final_state: Any, *, trace_id: str, name: str, return_direct_tools: set[str] | None = None) -> str:
    """Extract a human-readable result string from the streamed subagent state.

    Uses the matched tool results when the last assistant turn consists only
    of direct-return tools. Otherwise finds the last ``AIMessage`` and stringifies its
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

    direct_results = _terminal_direct_results(final_state, return_direct_tools or set())
    if direct_results is not None:
        texts = [message_content_to_text(message.content) for message in direct_results]
        return "\n\n".join(text for text in texts if text) or "No response generated"

    last_ai_message = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
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


#: Bash-family tool names whose calls count as recorded command executions.
_BASH_EVIDENCE_TOOL_NAMES = BASH_TOOL_NAMES
#: Bounds for the harvested evidence: only the newest few executions travel,
#: with command/output text capped and full-output summary semantics preserved.
_BASH_EVIDENCE_MAX_ENTRIES = 20
_BASH_EVIDENCE_COMMAND_CHARS = 500
_BASH_EVIDENCE_OUTPUT_TAIL_CHARS = 1000


def _bash_evidence_status(content: str, meta_status: str) -> tuple[str, str | None]:
    """Derive the recorded status from the shell exit marker when present.

    Returns ``(status, marker)``: the marker text actually seen (e.g. ``Exit
    Code: 5``), so consumers can report it instead of asserting a failure the
    harness cannot distinguish from the command's own trailing text. The
    explicit marker takes precedence over generic metadata in old checkpoints
    or provider stamps that report ``success`` for a nonzero shell exit.
    """
    return bash_exit_status(content) or (meta_status, None)


def _harvest_shell_persistence(final_state: Any) -> bool | None:
    """Whether the sandbox that produced this state's bash evidence reuses one
    persistent shell session (``Sandbox.persistent_shell_sessions`` — AIO's
    legacy exec path).

    Read from the state that CARRIED the evidence — the subagent's own graph
    state, whose ``sandbox`` channel is seeded from the parent or written by
    the subagent's own lazy acquisition — so the producing sandbox is the one
    resolved. Resolving against the parent task runtime instead would
    mis-adjudicate the common path where the parent never touched a sandbox:
    its state has no ``sandbox`` key, the lookup would report "no persistent
    session", and persistent-session evidence would pass as trusted. ``None``
    when the producing sandbox cannot be identified — and also when it never
    declared its session semantics: a custom provider's silence is not
    fresh-shell proof. Consumers must fail closed (UNVERIFIED) on ``None``.
    """
    try:
        from deerflow.sandbox.overwrite import unwrap_sandbox
        from deerflow.sandbox.sandbox_provider import get_sandbox_provider

        sandbox_state, _ = unwrap_sandbox(final_state.get("sandbox")) if isinstance(final_state, dict) else (None, False)
        sandbox_id = sandbox_state.get("sandbox_id") if isinstance(sandbox_state, dict) else None
        if not isinstance(sandbox_id, str):
            return None
        sandbox = get_sandbox_provider().get(sandbox_id)
        if sandbox is None:
            return None
        # Tri-state: an implementation that never declared its session
        # semantics (custom provider loaded by class path) stays ``None`` —
        # unknown — and the matcher fails closed on it exactly as on True.
        declared = getattr(sandbox, "persistent_shell_sessions", None)
        return None if declared is None else bool(declared)
    except Exception:
        return None


def _harvest_bash_executions(
    final_state: Any,
    *,
    summary_cache: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> list[dict[str, Any]] | None:
    """Harvest bounded bash command/output evidence from one streamed state.

    RFC #4651 PR4: a ``tests_passed:<command>`` acceptance leaf must anchor to
    a specific recorded execution — the command text lets the parent match the
    criterion against the call that actually ran. A bounded summary stamp is
    computed from the full tool output before retaining the diagnostic tail.
    The recorded status is the **actual shell exit status**: a nonzero bash exit comes back as ordinary output text
    (local: a trailing ``Exit Code: N``; e2b/opensandbox with empty output:
    ``Command exited with code N``), which ``deerflow_tool_meta`` still reports
    as success — so an explicit exit marker wins, and the meta status is only
    the fallback when no marker exists. Every entry is stamped with
    ``shell_persistent`` — the producing sandbox's
    ``persistent_shell_sessions`` flag, resolved against the sandbox recorded
    in THIS state (the subagent's own graph state), so provenance survives
    even when the parent never touched a sandbox. Failure-isolated like the
    receipt harvest: an error returns ``None`` and the leaves degrade to
    UNVERIFIED.
    """
    if not final_state:
        if summary_cache is not None:
            summary_cache.clear()
        return None
    messages = final_state.get("messages") if isinstance(final_state, dict) else None
    if not messages:
        if summary_cache is not None:
            summary_cache.clear()
        return None
    try:
        from deerflow.agents.middlewares.tool_call_args import pair_tool_call_results
        from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
        from deerflow.subagents.acceptance_checks import summarize_test_output

        # Tool-call ids are unique per response, not per conversation: pair each
        # result with the call of its own response, so a reused id never labels
        # one command's output with another command.
        bash_calls = [occurrence for occurrence in pair_tool_call_results(messages) if occurrence.name in _BASH_EVIDENCE_TOOL_NAMES]
        if not bash_calls:
            if summary_cache is not None:
                summary_cache.clear()
            return []
        positions = {id(message): index for index, message in enumerate(messages)}
        answered = sorted((occurrence for occurrence in bash_calls if occurrence.result is not None), key=lambda occurrence: positions[id(occurrence.result)])
        executions: list[dict[str, Any]] = []
        # Only retained executions need full-output parsing. The per-run cache
        # survives values chunks, but keeps at most the same newest 20 outputs.
        next_cache: dict[tuple[str, str], tuple[str, str]] = {}
        for occurrence in answered[-_BASH_EVIDENCE_MAX_ENTRIES:]:
            message = occurrence.result
            tool_call_id = occurrence.call_id
            name = occurrence.name
            command = occurrence.args.get("command")
            command = command if isinstance(command, str) else ""
            # A truncated command loses its suffix; the matcher must not
            # treat shell-structure analysis of the prefix as proof (a
            # selection-changing suffix like ``-k smoke`` could be cut).
            command_truncated = len(command) > _BASH_EVIDENCE_COMMAND_CHARS
            command = command[:_BASH_EVIDENCE_COMMAND_CHARS]
            meta = (message.additional_kwargs or {}).get(TOOL_META_KEY) or {}
            meta_status = str(meta.get("status") or getattr(message, "status", "success") or "success")
            content = message.content if isinstance(message.content, str) else json.dumps(message.content, sort_keys=True, default=str)
            status, status_marker = _bash_evidence_status(content, meta_status)
            result_id = message.id if isinstance(message.id, str) and message.id else None
            cache_key = _bash_evidence_key({"result_id": result_id, "tool_call_id": tool_call_id})
            cached = summary_cache.get(cache_key) if summary_cache is not None else None
            if cached is not None and (cached[0] is content or cached[0] == content):
                test_summary = cached[1]
            else:
                test_summary = summarize_test_output(content)
            next_cache[cache_key] = (content, test_summary)
            output_tail = content[-_BASH_EVIDENCE_OUTPUT_TAIL_CHARS:]
            if len(content) > _BASH_EVIDENCE_OUTPUT_TAIL_CHARS and content[-_BASH_EVIDENCE_OUTPUT_TAIL_CHARS - 1] != "\n":
                # A clipped test name/log line can look like a summary after
                # losing its reporter prefix. Retain only complete lines.
                output_tail = output_tail.partition("\n")[2]
            executions.append(
                {
                    "tool_call_id": tool_call_id,
                    "result_id": result_id,
                    "tool_name": name,
                    "command": command,
                    "command_truncated": command_truncated,
                    "output_tail": output_tail,
                    "test_summary": test_summary,
                    "status": status,
                    "status_marker": status_marker,
                }
            )
        if summary_cache is not None:
            summary_cache.clear()
            summary_cache.update(next_cache)
        # Provenance stamp: whether the producing sandbox reuses one
        # persistent shell session. Captured here — while the state that
        # carried the evidence is at hand — because the parent-side checker
        # cannot derive it (its runtime has no ``sandbox`` key when the
        # parent delegated before touching one). ``None`` (unknown) fails
        # closed in the acceptance matcher.
        shell_persistent = _harvest_shell_persistence(final_state)
        for execution in executions:
            execution["shell_persistent"] = shell_persistent
        return executions[-_BASH_EVIDENCE_MAX_ENTRIES:]
    except Exception:
        logger.warning("Failed to harvest subagent bash execution evidence", exc_info=True)
        return None


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


_THREAD_INCARNATION_UNSET = object()


class SubagentExecutor(DelegatedTaskExecutor):
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        app_config: AppConfig | None = None,
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        uploaded_files: list[dict[str, Any]] | None = None,
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
        knowledge_scope: dict[str, Any] | None = None,
        extensions: Any | None = None,
        execution_capacity: SubagentExecutionCapacity | None = None,
        acceptance_criteria: list[str] | None = None,
        loop_detection_recorder: Any | None = None,
        tool_promotion_recorder: Any | None = None,
        tool_progress_recorder: Any | None = None,
        approval_runtime: Any | None = None,
        context_snapshot: ParentContextSnapshot | None = None,
        thread_incarnation: str | None | object = _THREAD_INCARNATION_UNSET,
        input_gate: Any | None = None,
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
            uploaded_files: Snapshot of files uploaded in the parent's current
                run. Seeded into the child graph state so ``list_uploaded_files``
                can exclude them from historical-upload results.
            thread_id: Thread ID for sandbox operations.
            thread_incarnation: Server-captured parent lifecycle. Explicit None
                preserves legacy scope; omission stays absent so MCP fails closed.
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
                from the parent run for Langfuse metadata correlation. Falls
                back to the ambient trace so the attribute is always a real
                id, never ``None``.
            knowledge_scope: Canonical execution-only knowledge scope inherited
                from the parent turn. Display labels are never propagated.
            extensions: The parent run's immutable ``LoadedExtensions`` snapshot,
                captured at ``task_tool`` dispatch. When None (embedded client,
                standalone LangGraph Server), ``_aexecute`` falls back to the
                process-wide singleton.
            execution_capacity: Optional explicitly shared admission controller.
                Direct ``create_deerflow_agent`` callers pass one through their
                ``SubagentRuntime``; application factories fall back to the
                startup-configured process singleton.
            acceptance_criteria: Optional lead-supplied completion requirements
                (RFC #4651 PR3). Criterion values are model-supplied untrusted
                data, so ``_build_initial_state`` appends them to the task
                ``HumanMessage`` (the channel ``InputSanitizationMiddleware``
                sanitizes and boundary-frames); the subagent's ``SystemMessage``
                carries only the framework-owned pointer note.
            loop_detection_recorder: Optional loop-safe recorder supplied by the
                parent task tool. Native subagents execute on a separate event
                loop, so this must be a proxy rather than the parent
                ``RunJournal`` itself.
            tool_promotion_recorder: Optional loop-safe recorder for deferred-tool
                promotion events. It follows the same isolated-loop boundary.
            tool_progress_recorder: Optional loop-safe recorder for tool-progress
                phase transitions. It follows the same isolated-loop boundary.
            context_snapshot: Optional immutable parent history captured by the
                ordinary task tool at dispatch. Rendered as background data,
                never as child execution evidence or inherited system authority.
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
        # Resolve thinking_enabled: config explicit > False
        self.thinking_enabled = config.thinking_enabled if config.thinking_enabled is not None else False
        # Resolve reasoning_effort: config explicit > None
        self.reasoning_effort = config.reasoning_effort

        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.uploaded_files = deepcopy(uploaded_files) if uploaded_files is not None else None
        self.context_snapshot = context_snapshot
        self.input_gate = input_gate
        self.thread_id = thread_id
        self.thread_incarnation = thread_incarnation
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
        # Resolved, not stored raw: the attribute is part of the non-nullable
        # trace contract, and ``_aexecute`` rebinds it because a subagent runs
        # on the isolated loop thread where the parent ContextVar may be gone.
        self.deerflow_trace_id = resolve_trace_id(deerflow_trace_id)
        self.knowledge_scope = execution_scope(knowledge_scope) if knowledge_scope is not None else None
        # Parent run's extension snapshot. Binding it here (rather than reading
        # the singleton at execution time) is what keeps one run on a single
        # extension generation: a concurrent ``set_loaded_extensions()`` between
        # the lead run's start and this subagent's execution must not swap the
        # generation underneath the delegated work.
        self.extensions = extensions
        self.execution_capacity = execution_capacity
        # Raw lead-supplied criteria; stripping/capping happens at render time
        # in report_contract.render_acceptance_criteria_block.
        self.acceptance_criteria = acceptance_criteria
        self.loop_detection_recorder = loop_detection_recorder
        self.tool_promotion_recorder = tool_promotion_recorder
        self.tool_progress_recorder = tool_progress_recorder
        self.approval_runtime = approval_runtime

        self._base_tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )
        self.tools = self._base_tools
        # Populated from the same per-user, config-filtered registry used to
        # build the prompt. Runtime skill activation middleware receives
        # this exact set so a subagent cannot activate an undisclosed skill.
        self._available_skill_names: set[str] = set()
        # Guard middlewares that expose ``consume_stop_reason`` (currently
        # ``TokenBudgetMiddleware``, ``LoopDetectionMiddleware`` and
        # ``ModelLengthFinishReasonMiddleware``), captured in ``_create_agent``
        # so ``_aexecute`` can read each after the run and surface whichever
        # cap fired (token_capped / loop_capped / model_length_capped) to the lead
        # (#3875 Phase 2). Collected as a list — every guard must be checked,
        # not just the first — because the v2 contract advertises more than one
        # cap reason.
        self._stop_reason_middlewares: list[Any] = []
        self._return_direct_tools: set[str] = set()
        # The one skill-authorization context for this execution, resolved
        # lazily by ``_resolve_skill_authorization`` and shared by the Layer 1
        # filter and every runtime ``skill:activate`` check (activation
        # middleware, describe gate, skill-read stamping).
        self._skill_authorization: Any | None = None
        # LangGraph super-step budget that buys ``config.max_turns`` turns,
        # resolved in ``_create_agent`` once the middleware chain — and with it
        # the compiled graph's per-turn node count — is known. Stays ``None``
        # until then; ``_aexecute`` falls back to the raw turn count so a test
        # double replacing ``_create_agent`` still produces a runnable config.
        self._recursion_limit: int | None = None
        # What this subagent was assembled from, published to extension
        # observers at the end of ``_create_agent``. The prompt and skill set
        # are captured while ``_build_initial_state`` renders them because
        # neither is recoverable from the compiled graph afterwards.
        self.assembly_descriptor: Any | None = None
        self._assembled_system_prompt = self.config.system_prompt or ""
        self._assembled_skills: list[Any] = []
        # Only these exact, build-generated instances receive the discovery
        # exemption in the final name-policy audit; names alone are insufficient.
        self._policy_discovery_tools: tuple[BaseTool, ...] = ()

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _get_resolved_app_config(self) -> AppConfig:
        """Return the one AppConfig snapshot used throughout this execution."""
        if self._resolved_app_config is None:
            self._resolved_app_config = get_app_config()
        return self._resolved_app_config

    async def _create_agent(
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

        Async because the middleware-declared-tool decision below calls the
        authorization provider's ``filter_resources`` — potentially external
        policy-service I/O — and this method runs on the shared event loop
        (``_aexecute`` awaits it), so the decision is offloaded to a worker
        thread with the same provider instance and context.
        """
        app_config = self._get_resolved_app_config()
        if self.model_name is None:
            self.model_name = resolve_subagent_model_name(self.config, self.parent_model, app_config=app_config)
        from deerflow.models.reasoning import ReasoningPolicyError, resolve_reasoning_contract, resolve_reasoning_request

        get_model_config = getattr(app_config, "get_model_config", None)
        model_config = get_model_config(self.model_name) if callable(get_model_config) else None
        if model_config is None:
            model_config = next((profile for profile in getattr(app_config, "models", []) if profile.name == self.model_name), None)
        try:
            effective_reasoning = resolve_reasoning_request(resolve_reasoning_contract(model_config), thinking_enabled=self.thinking_enabled, reasoning_effort=self.reasoning_effort)
        except ReasoningPolicyError as exc:
            raise ValueError(f"Model {self.model_name}: {exc}") from exc
        # Preserve the original request for the factory's validation and logs.
        # Provider construction can read local credentials (the Codex provider
        # loads the CLI auth.json), so keep the build off the event loop.
        model = await run_assembly(
            create_chat_model,
            name=self.model_name,
            thinking_enabled=self.thinking_enabled,
            reasoning_effort=self.reasoning_effort,
            app_config=app_config,
            attach_tracing=False,
        )

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
        # Phase 3 (Layer 2): arm the runtime ``skill:activate`` check on the
        # subagent chain too — a delegated task is a plain HumanMessage, so
        # task text containing /skill-name reaches the activation middleware.
        # Resolved through the same memoized helper the Layer 1 filter used
        # (``_resolve_skill_authorization``): provider factories are
        # deliberately uncached, so resolving independently here could hand the
        # runtime checks a different provider instance (and policy snapshot)
        # than the filter that built ``_available_skill_names``.
        skill_authorization = self._resolve_skill_authorization()
        if skill_authorization is not None:
            middleware_kwargs["skill_authorization"] = skill_authorization
        if mcp_routing_middleware is not None:
            middleware_kwargs["mcp_routing_middleware"] = mcp_routing_middleware
        middlewares = build_subagent_runtime_middlewares(**middleware_kwargs)
        if self.input_gate is not None:
            from deerflow.agents.middlewares.run_input_middleware import ChildInputContinuationMiddleware, ChildInputMiddleware

            middlewares.insert(0, ChildInputMiddleware(self.input_gate))
            middlewares.append(ChildInputContinuationMiddleware(self.input_gate))
        # Authorization Layer 1 for middleware-declared tools (e.g. extension
        # contributions): collect from the built stack, decide with the same
        # provider/principal as the ordinary pass (offloaded off the event
        # loop — a custom provider's filter_resources may do policy-service
        # I/O), then narrow the view build-locally. The verification before
        # create_agent is the backstop for third-party __copy__ behavior.
        declared_authorized = None
        layer_one = getattr(self, "_layer_one_outcome", None)
        authz_context = getattr(self, "_authz_context", None)
        # Production sets provider, context, and outcome together in
        # ``_build_initial_state``; a missing piece means no ordinary pass ran
        # on this executor (direct ``_create_agent`` calls in tests), so there
        # is no verdict set to seed the decision with and the pass is skipped.
        if authz_provider is not None and layer_one is not None and authz_context is not None:
            from deerflow.agents.middlewares.tool_declarations import (
                apply_declared_tool_view,
                collect_declared_tools,
                decide_declared_tools,
                verify_declared_tool_view,
            )

            declared = collect_declared_tools(middlewares)
            declared_authorized = await asyncio.to_thread(
                decide_declared_tools,
                declared,
                outcome=layer_one,
                context=authz_context,
                app_config=app_config,
                authorization_provider=authz_provider,
            )
            middlewares = apply_declared_tool_view(middlewares, authorized_names=declared_authorized)
            verify_declared_tool_view(middlewares, authorized_names=declared_authorized)
        elif authz_provider is not None:
            # Defense in depth: the provider is configured but the seeded
            # decision state is missing, so the declaration pass is skipped.
            # Layer 2 still enforces at call time, but middleware-declared
            # tools bypass Layer 1 in this build — log so a future refactor
            # that breaks the ``_build_initial_state`` invariant is visible
            # instead of silently reopening the channel.
            missing = [name for name, value in (("_layer_one_outcome", layer_one), ("_authz_context", authz_context)) if value is None]
            logger.warning(
                "Authorization provider is configured but %s %s not set for subagent %r; skipping the middleware-declared tool pass (Layer 2 still enforces at call time)",
                " and ".join(missing),
                "is" if len(missing) == 1 else "are",
                self.config.name,
            )
        bound_tools = list(tools if tools is not None else self.tools)
        # Native subagents have no resumable checkpoint/runtime. Reuse the lead
        # builder's configured policy so matching calls fail closed instead of
        # bypassing approval; disabled configuration remains a no-op.
        from deerflow.agents.lead_agent.agent import _insert_hitl_approval_middleware

        _insert_hitl_approval_middleware(middlewares, bound_tools, app_config, supports_resume=False, model_name=self.model_name)
        # Extensions can add tools through middleware after the inherited list
        # was filtered. Apply the same subagent policy to those declarations,
        # independently of global authorization, without changing shared stacks
        # or re-filtering generated discovery helpers in bound_tools.
        from deerflow.agents.middlewares.tool_declarations import ToolPolicyNameResolver, apply_declared_tool_policy, verify_subagent_tool_policy

        policy_names = ToolPolicyNameResolver()
        middlewares = apply_declared_tool_policy(middlewares, allowed=self.config.tools, disallowed=self.config.disallowed_tools, name_resolver=policy_names)
        # Collect every guard middleware that exposes ``consume_stop_reason``
        # (TokenBudgetMiddleware, LoopDetectionMiddleware,
        # ModelLengthFinishReasonMiddleware) so _aexecute can read
        # each after the run and surface whichever cap fired. Duck-typed
        # (``hasattr``) so this file needs no import of the middleware classes;
        # a list (not ``next(...)``) so every guard is checked and a later one
        # is picked up automatically.
        self._stop_reason_middlewares = [m for m in middlewares if hasattr(m, "consume_stop_reason")]
        self._recursion_limit = self._resolve_recursion_limit(middlewares)

        # system_prompt is included in initial state messages (see _build_initial_state)
        # to avoid multiple SystemMessages which some LLM APIs don't support.
        verify_subagent_tool_policy(
            bound_tools,
            middlewares,
            allowed=self.config.tools,
            disallowed=self.config.disallowed_tools,
            discovery_tools=getattr(self, "_policy_discovery_tools", ()),
            name_resolver=policy_names,
        )
        agent = create_agent(
            model=model,
            tools=bound_tools,
            middleware=middlewares,
            system_prompt=None,
            state_schema=ThreadState,
            checkpointer=False,
        )
        # Use the compiled registry: it includes middleware tools, normalized
        # callables, and LangChain's last-definition-wins name precedence.
        from langgraph.prebuilt import ToolNode

        tool_graph_node = agent.get_graph().nodes.get("tools")
        tool_node = tool_graph_node.data if tool_graph_node is not None else None
        self._return_direct_tools = {tool.name for tool in tool_node.tools_by_name.values() if tool.return_direct} if isinstance(tool_node, ToolNode) else set()
        self._describe_assembly(
            model_config=model_config,
            effective_reasoning=effective_reasoning,
            tools=bound_tools,
            middlewares=middlewares,
            deferred_setup=deferred_setup,
            extensions=extensions if extensions is not None else self.extensions,
        )
        return agent

    def _resolve_recursion_limit(self, middlewares: list[Any]) -> int:
        """Translate ``max_turns`` into the super-step budget it actually means.

        ``max_turns`` is the operator-facing policy ("how many times may this
        agent think and act"), while LangGraph's ``recursion_limit`` counts
        graph nodes. ``create_agent`` compiles one node per middleware
        lifecycle hook, so the two differ by the depth of the assembled chain —
        see ``turn_budget.py`` for the arithmetic. Resolving it here, from the
        chain this subagent was actually built with, keeps the budget stable as
        middlewares are added and lets a per-agent chain differ.
        """
        recursion_limit = resolve_recursion_limit(self.config.max_turns, middlewares)
        logger.debug(
            "[trace=%s] Subagent %s turn budget: max_turns=%s -> recursion_limit=%s (%d middlewares)",
            self.trace_id,
            self.config.name,
            self.config.max_turns,
            recursion_limit,
            len(middlewares),
        )
        # A hook that declares ``can_jump_to`` — agent-level hooks included —
        # can leave the straight path through the graph, spending super-steps
        # the flat per-turn cost does not model, so the budget silently becomes
        # a lower bound. No middleware in the subagent chain declares one today;
        # say so loudly if that changes, rather than letting runs quietly cap
        # short again.
        jumping_hooks = find_jumping_hooks(middlewares)
        if jumping_hooks:
            logger.warning(
                "[trace=%s] Subagent %s has jump-declaring middleware hooks (%s); recursion_limit=%s is a lower bound for max_turns=%s, so the run may cap early",
                self.trace_id,
                self.config.name,
                ", ".join(f"{name}.{hook}" for name, hook in jumping_hooks),
                recursion_limit,
                self.config.max_turns,
            )
        return recursion_limit

    def _describe_assembly(
        self,
        *,
        model_config: Any,
        effective_reasoning: "ResolvedReasoning",
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
                thinking_enabled=effective_reasoning.thinking_enabled,
                reasoning_effort=effective_reasoning.reasoning_effort,
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
        ``"loop_capped"`` when loop detection forced a stop,
        ``"model_length_capped"`` when the provider cut the response at its
        output limit, otherwise ``None``.
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
        else:
            allowed = None

        # Phase 3: enforce skill authorization (Layer 1). Filter the skill
        # allowlist by the provider's "skill" policy so denied skills never
        # reach the returned list (and are never turned into tools). Pass the
        # already-loaded ``all_skills`` names as candidates so we don't pay a
        # second ``load_skills`` round-trip inside the filter, and the memoized
        # authorization context so the filter's provider instance is the same
        # one the runtime ``skill:activate`` checks on this assembly use.
        from deerflow.authz.skill_filter import filter_available_skills_by_authorization

        resolved_app_config = self.app_config or get_app_config()
        allowed = filter_available_skills_by_authorization(
            allowed,
            context=self._skill_authz_context(),
            app_config=resolved_app_config,
            # Same bucket convention as the middleware chain (self.user_id or
            # DEFAULT_USER_ID); only consulted if candidates were not supplied.
            user_id=self.user_id or DEFAULT_USER_ID,
            candidate_skill_names=[s.name for s in all_skills],
            authorization=self._resolve_skill_authorization(),
        )

        if allowed is not None:
            return [s for s in all_skills if s.name in allowed]
        return all_skills

    def _resolve_skill_authorization(self):
        """The one skill-authorization context for this execution.

        Resolved once per executor assembly (executors are built per task
        dispatch) and shared by the Layer 1 filter in ``_load_skills``, the
        runtime ``skill:activate`` check on the activation middleware, the
        ``describe_skill`` gate, and the skill-read stamping middleware — so
        every layer of this assembly sees the same provider instance and
        policy snapshot. Providers are uncached by design; resolving per layer
        would let a custom provider observe different snapshots for visibility
        and activation within one run.
        """
        resolved = getattr(self, "_skill_authorization", None)
        if resolved is None:
            from deerflow.authz.skill_filter import resolve_skill_authorization

            resolved = resolve_skill_authorization(self._skill_authz_context(), self._get_resolved_app_config())
            self._skill_authorization = resolved
        return resolved

    def _skill_authz_context(self) -> dict[str, Any]:
        """Identity mapping shared by the Layer 1 filter and the runtime
        ``skill:activate`` check wired into the subagent middleware chain."""
        return {
            "user_id": self.user_id,
            "user_role": self.user_role,
            "oauth_provider": self.oauth_provider,
            "oauth_id": self.oauth_id,
            "channel_user_id": self.channel_user_id,
            "is_internal": self.is_internal,
            "authz_attributes": self.authz_attributes,
        }

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
        # loaded through read_file. Their allowed-tools declarations are
        # compatibility metadata only, not tool authority; loading them here
        # does not filter any tool.
        skills = await self._load_skills()
        self._assembled_skills = list(skills)
        self._available_skill_names = {skill.name for skill in skills}

        resolved_app_config = self._get_resolved_app_config()

        from deerflow.skills.describe import build_skill_search_setup, get_skill_index_prompt_section

        skill_setup = build_skill_search_setup(
            skills,
            enabled=resolved_app_config.skills.deferred_discovery,
            container_base_path=resolved_app_config.skills.container_path,
            skill_authorization=self._resolve_skill_authorization(),
        )

        # Apply authorization Layer 1: filter tools before deferred assembly
        # so denied tools can never enter the DeferredToolCatalog.
        from deerflow.agents.middlewares.tool_declarations import layer_one_outcome
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
        # The declaration pass in ``_create_agent`` reuses this run's provider,
        # context, and verdicts — one principal and one verdict set per run.
        self._authz_context = authz_context
        self._layer_one_outcome = layer_one_outcome(authorization_candidates, authorized_tools)
        configured_tools = [tool for tool in authorized_tools if id(tool) in configured_tool_ids]
        late_tools = [tool for tool in authorized_tools if id(tool) not in configured_tool_ids]

        # Assemble deferred tool_search after the subagent's name allow/deny and
        # authorization filters, mirroring the lead path so subagents stop
        # binding full MCP schemas.
        # The generated tool_search helper is intentionally not subject to the
        # subagent's name-level allow/deny (config.tools / disallowed_tools):
        # its catalog is built from that already-filtered list. The catalog remains
        # scoped to the subagent admitted tool list, and runtime authorization
        # still checks execution, so promotion cannot widen
        # the subagent's admitted tool authority.
        final_tools, deferred_setup = assemble_deferred_tools(
            configured_tools,
            enabled=resolved_app_config.tool_search.enabled,
        )
        final_tools.extend(late_tools)
        self._policy_discovery_tools = tuple(helper for helper in (deferred_setup.tool_search_tool, skill_setup.describe_skill_tool) if helper is not None and any(helper is tool for tool in final_tools))

        # Combine the system prompt and skill discovery metadata into a single
        # SystemMessage. Full SKILL.md bodies are loaded only when activated.
        # Some LLM APIs reject multiple SystemMessages with
        # "System message must be at the beginning."
        system_parts: list[str] = []
        if self.config.system_prompt:
            system_parts.append(self.config.system_prompt)
        if self.context_snapshot is not None:
            system_parts.append(SNAPSHOT_SYSTEM_NOTE)
        # RFC #4651 PR3: every subagent — built-in or custom — gets the same
        # report contract, so the citation / verifiable-handle requirements
        # never depend on the config author remembering them. The citation
        # clause only makes sense while receipts render, so it follows
        # verification.receipts_enabled.
        verification_cfg = getattr(resolved_app_config, "verification", None)
        receipts_enabled = getattr(verification_cfg, "receipts_enabled", True)
        system_parts.append(build_report_contract_section(receipts_enabled=receipts_enabled))
        # Acceptance criteria are model-supplied (ultimately user-influenceable)
        # data with the same provenance as the delegated prompt, so criterion
        # values travel in the task HumanMessage — the channel
        # InputSanitizationMiddleware escapes and boundary-frames as untrusted
        # input. The SystemMessage carries only a framework-owned pointer that
        # names the list's location and authority, never the criterion text: a
        # natural-language injection inside a criterion ("ignore the report
        # contract…") keeps task-data priority and cannot override framework
        # instructions via the system channel.
        criteria_block = render_acceptance_criteria_block(self.acceptance_criteria)
        if criteria_block:
            system_parts.append(build_acceptance_criteria_system_note(receipts_enabled=receipts_enabled))
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
            self._assembled_system_prompt = self.config.prompt_overlay.apply("\n\n".join(system_parts))
            messages.append(SystemMessage(content=self._assembled_system_prompt))

        if self.context_snapshot is not None:
            messages.append(self.context_snapshot.to_message())

        # Then the actual task, with any lead-supplied acceptance criteria
        # appended as untrusted data (see the channel note above).
        task_content = f"{task}\n\n{criteria_block}" if criteria_block else task
        messages.append(HumanMessage(content=task_content))

        state: dict[str, Any] = {
            "messages": messages,
        }

        # Pass through the parent runtime state that tools need. Each child
        # receives fresh containers so graph writes never mutate the snapshot
        # held by another execution.
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data
        if self.uploaded_files is not None:
            state["uploaded_files"] = deepcopy(self.uploaded_files)

        return state, final_tools, deferred_setup

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
                started_at=_utcnow(),
            )
        sandbox_lease_owner_id = f"subagent:{result.task_id}"
        execution_context: dict[str, Any] | None = None
        from deerflow.extensions import get_loaded_extensions

        loaded_extensions = result.loaded_extensions or self.extensions or get_loaded_extensions()
        task_store = result.task_store
        outcome = None

        def propose_terminal(status, **kwargs):
            nonlocal outcome
            outcome = WorkerOutcome(status=status.value, **kwargs)

        ai_messages = result.snapshot().ai_messages
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

        bash_summary_cache: dict[tuple[str, str], tuple[str, str]] = {}

        def current_bash_executions() -> list[dict[str, Any]] | None:
            # RFC #4651 PR4: evidence for tests_passed acceptance leaves.
            # Accumulated from every chunk (not harvested once at terminal) so
            # summarization compacting earlier messages cannot erase a recorded
            # execution. Criteria-free runs pay nothing.
            if not self.acceptance_criteria:
                return None
            return _harvest_bash_executions(final_state, summary_cache=bash_summary_cache)

        try:
            if result.cancel_event.is_set():
                propose_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    tool_receipts=terminal_receipts(),
                )
                return outcome

            state, final_tools, deferred_setup = await self._build_initial_state(task)
            agent = await self._create_agent(
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
                # Super-steps, not turns: ``_create_agent`` (just above) scaled
                # ``max_turns`` by the compiled chain's per-turn node count.
                # Unset only when that method was replaced by a test double.
                "recursion_limit": self._recursion_limit if self._recursion_limit is not None else self.config.max_turns,
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
            if self.thread_incarnation is not _THREAD_INCARNATION_UNSET:
                context[THREAD_INCARNATION_CONTEXT_KEY] = self.thread_incarnation
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
            context[DEERFLOW_TRACE_METADATA_KEY] = self.deerflow_trace_id
            if self.knowledge_scope is not None:
                context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = dict(self.knowledge_scope)
            context["is_subagent"] = True
            if self.approval_runtime is not None:
                context["__tool_approval_runtime"] = self.approval_runtime
                context["tool_approval_mode"] = self.approval_runtime.mode
            context[_SANDBOX_LEASE_OWNER_CONTEXT_KEY] = sandbox_lease_owner_id
            context[_SANDBOX_COMMAND_SCOPE_CONTEXT_KEY] = sandbox_lease_owner_id
            execution_context = context
            from deerflow.sandbox.lease import register_sandbox_prewarm_cleanup

            register_sandbox_prewarm_cleanup(context)
            context["agent_id"] = self.config.name
            if self.loop_detection_recorder is not None:
                context[LOOP_DETECTION_RECORDER_CONTEXT_KEY] = self.loop_detection_recorder
            if self.tool_promotion_recorder is not None:
                context[TOOL_PROMOTION_RECORDER_CONTEXT_KEY] = self.tool_promotion_recorder
            if self.tool_progress_recorder is not None:
                context[TOOL_PROGRESS_RECORDER_CONTEXT_KEY] = self.tool_progress_recorder

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution with max_turns={self.config.max_turns}")

            # Use stream instead of invoke to get real-time updates
            # This allows us to collect AI messages as they are generated

            # Pre-check: bail out immediately if already cancelled before streaming starts
            if result.cancel_event.is_set():
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled before streaming")
                propose_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    token_usage_records=collector.snapshot_records(),
                    tool_receipts=terminal_receipts(),
                )
                return outcome

            cancelled_during_stream = False
            stream = agent.astream(state, config=run_config, context=context, stream_mode="values")  # type: ignore[arg-type]
            try:
                async for chunk in stream:
                    # A yielded values chunk is already executed state.  Retain it
                    # before observing cooperative cancellation so terminal receipt
                    # harvesting includes a tool result that completed while the
                    # cancellation request was in flight.
                    final_state = chunk
                    result.update_knowledge_sources(chunk.get("messages") or [])
                    result.update_tool_receipts(terminal_receipts())
                    result.update_bash_executions(current_bash_executions())

                    # Cooperative cancellation: check if parent requested stop.
                    # Note: cancellation is only detected at astream iteration boundaries,
                    # so long-running tool calls within a single iteration will not be
                    # interrupted until the next chunk is yielded.
                    if result.cancel_event.is_set():
                        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled by parent")
                        cancelled_during_stream = True
                        break

                    # Capture every step message (assistant turns AND tool outputs)
                    # appended since the last chunk. A single super-step can append
                    # several ToolMessages when the model emits multiple tool calls in
                    # one turn, so capturing only messages[-1] would drop all but the
                    # last output (#3779). Dedup/serialization live in capture_step_message.
                    messages = chunk.get("messages") or []
                    previous_count = len(ai_messages)
                    processed_message_count = capture_new_step_messages(messages, ai_messages, seen_message_ids, processed_message_count)
                    result.publish_steps(ai_messages[previous_count:], collector.snapshot_records())
                    if len(ai_messages) > previous_count:
                        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured {len(ai_messages) - previous_count} step message(s); total #{len(ai_messages)}")
            finally:
                active_error = sys.exception()
                cancel_requested = cancelled_during_stream or result.cancel_event.is_set()
                slow_close_warning = asyncio.get_running_loop().call_later(
                    _STREAM_CLOSE_SLOW_WARNING_SECONDS,
                    logger.warning,
                    "[trace=%s] Subagent %s stream cleanup for execution %s is still running after %.1fs; cooperative terminalization and sandbox resource release have not occurred",
                    self.trace_id,
                    self.config.name,
                    result.task_id,
                    _STREAM_CLOSE_SLOW_WARNING_SECONDS,
                    context=Context(),
                )
                try:
                    await close_agent_stream(stream)
                except asyncio.CancelledError as exc:
                    close_failure = exc.__cause__
                    if isinstance(close_failure, Exception):
                        logger.warning(
                            "[trace=%s] Could not close interrupted subagent stream %s",
                            self.trace_id,
                            self.config.name,
                            exc_info=(type(close_failure), close_failure, close_failure.__traceback__),
                        )
                    raise
                except Exception:
                    cancel_requested = cancel_requested or result.cancel_event.is_set()
                    if active_error is None and not cancel_requested:
                        raise
                    logger.warning(
                        "[trace=%s] Could not close interrupted subagent stream %s",
                        self.trace_id,
                        self.config.name,
                        exc_info=True,
                    )
                else:
                    cancel_requested = cancel_requested or result.cancel_event.is_set()
                finally:
                    slow_close_warning.cancel()

            if cancel_requested:
                propose_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    token_usage_records=collector.snapshot_records(),
                    tool_receipts=terminal_receipts(),
                )
                return outcome

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")
            token_usage_records = collector.snapshot_records()
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                propose_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    token_usage_records=token_usage_records,
                    tool_receipts=terminal_receipts(),
                )
            else:
                final_result = _extract_final_result(
                    final_state,
                    trace_id=self.trace_id,
                    name=self.config.name,
                    return_direct_tools=self._return_direct_tools,
                )
                direct_results = _terminal_direct_results(final_state, self._return_direct_tools)
                if direct_results is not None and any(message.status == "error" for message in direct_results):
                    propose_terminal(
                        SubagentStatus.FAILED,
                        result=final_result,
                        error=f"Direct-return tool failure:\n{final_result}",
                        token_usage_records=token_usage_records,
                        tool_receipts=terminal_receipts(),
                    )
                    return outcome
                # A guard hard-stop (token budget or loop detection) does not raise
                # — it strips tool_calls so the run completes with a final answer.
                # ``consume_stop_reason`` on each guard tells us whether that
                # happened so we can mark the completed result with the cap reason
                # (token_capped / loop_capped) for the lead (#3875 Phase 2). It
                # pops the reason, so keep it on the branch that consumes it — a
                # fallback carries no tool_calls, so no guard hard-stop can have
                # co-occurred on the FAILED branch anyway.
                stop_reason = self._consume_guard_stop_reason()
                propose_terminal(
                    SubagentStatus.COMPLETED,
                    result=final_result,
                    stop_reason=stop_reason,
                    token_usage_records=token_usage_records,
                    tool_receipts=terminal_receipts(prefer_citing_turn=True),
                )

        except GraphRecursionError:
            # ``recursion_limit`` on run_config is ``self.config.max_turns``
            # scaled into super-steps (set above), so hitting it means the
            # subagent exhausted its turn budget — report the turn count, which
            # is the number the operator configured. Route into the additive
            # ``stop_reason`` channel (#3875 Phase 2) rather than a dedicated
            # status enum (which would break v1 contract consumers). If the run
            # streamed usable partial work, surface it as ``completed``;
            # otherwise ``failed``. Either way the lead can tell "out of budget"
            # from "broken subagent" without parsing result text.
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
                propose_terminal(
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
                    propose_terminal(
                        SubagentStatus.COMPLETED,
                        result=usable_partial,
                        stop_reason=stop_reason,
                        token_usage_records=records,
                        tool_receipts=terminal_receipts(prefer_citing_turn=True),
                    )
                else:
                    propose_terminal(
                        SubagentStatus.FAILED,
                        error=f"Reached max_turns={max_turns}",
                        stop_reason=stop_reason,
                        token_usage_records=records,
                        tool_receipts=terminal_receipts(),
                    )

        except asyncio.CancelledError:
            # The outer background wrapper observes cancellation only after this
            # function's task-stop hook. Publish it here so observers see ABORTED;
            # a previously published hard timeout still wins the terminal race.
            propose_terminal(
                SubagentStatus.CANCELLED,
                error="Cancelled by user",
                token_usage_records=collector.snapshot_records() if collector is not None else None,
                tool_receipts=terminal_receipts(),
            )
            raise

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
            propose_terminal(
                SubagentStatus.FAILED,
                error=str(e),
                token_usage_records=collector.snapshot_records() if collector is not None else None,
                tool_receipts=terminal_receipts(),
            )

        finally:
            # A completed model response can be in the collector before its
            # graph node publishes a values chunk. Publish final usage after
            # stream teardown, including cancellation and hard-timeout cleanup.
            if collector is not None:
                result.update_token_usage_records(collector.snapshot_records())

            async def cleanup_execution() -> None:
                if execution_context is not None:
                    try:
                        from deerflow.sandbox.lease import cancel_sandbox_execution_lease_async, release_sandbox_execution_lease_async

                        try:
                            if result.cancel_event.is_set() or (outcome is not None and outcome.status in ("cancelled", "failed", "timed_out")):
                                await cancel_sandbox_execution_lease_async(execution_context)
                        finally:
                            await release_sandbox_execution_lease_async(execution_context)
                    except Exception:
                        logger.warning(
                            "[trace=%s] Failed to release sandbox execution lease for subagent %s",
                            self.trace_id,
                            self.config.name,
                            exc_info=True,
                        )

            # Keep capacity and execution-done ownership until the whole tail settles.
            result.backend_cleanup = cleanup_execution

        return outcome
