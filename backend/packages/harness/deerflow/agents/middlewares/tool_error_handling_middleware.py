"""Tool error handling middleware and shared runtime middleware builders."""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.skill_context import (
    SKILL_CONTEXT_ENTRY_KEY,
    _tool_call_path,
    build_skill_entry_metadata_from_read,
)
from deerflow.agents.middlewares.tool_result_meta import (
    normalize_tool_result,
    stamp_exception_meta,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.summarization_config import DEFAULT_SKILL_FILE_READ_TOOL_NAMES
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.subagents.status_contract import (
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)

if TYPE_CHECKING:
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"
_TASK_TOOL_NAME = "task"
_RECOVERY_HINT = "Continue with available context, or choose an alternative tool."


def _stamp_task_exception_status(message: ToolMessage, *, tool_name: str, error: str) -> ToolMessage:
    """Stamp failed metadata on task exception wrappers produced here."""
    if tool_name != _TASK_TOOL_NAME:
        return message
    content, metadata_error = format_subagent_result_message("failed", error=error)
    if not content.endswith((".", "!", "?")):
        content += "."
    message.content = f"{content} {_RECOVERY_HINT}"
    existing = dict(message.additional_kwargs or {})
    existing.update(make_subagent_additional_kwargs("failed", error=metadata_error))
    message.additional_kwargs = existing
    return message


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Convert tool exceptions into error ToolMessages so the run can continue."""

    def __init__(self, *, app_config: AppConfig | None = None) -> None:
        super().__init__()
        self._app_config = app_config
        if app_config is None:
            self._skill_read_tool_names = frozenset(DEFAULT_SKILL_FILE_READ_TOOL_NAMES)
            self._skills_root = DEFAULT_SKILLS_CONTAINER_PATH
        else:
            self._skill_read_tool_names = frozenset(app_config.summarization.skill_file_read_tool_names)
            self._skills_root = app_config.skills.container_path

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. {_RECOVERY_HINT}"
        message = ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )
        # This middleware is the producer for exception wrappers, so task
        # failures raised before task_tool can build its own Command still
        # carry the same structured metadata.
        structured_error = f"{exc.__class__.__name__}: {detail}"
        message = _stamp_task_exception_status(message, tool_name=tool_name, error=structured_error)
        return stamp_exception_meta(message, structured_error)

    def _stamp_skill_read_metadata(
        self,
        message: ToolMessage,
        request: ToolCallRequest,
        *,
        tool_name: str,
    ) -> ToolMessage:
        if tool_name not in self._skill_read_tool_names:
            return message
        if getattr(message, "status", "success") == "error":
            return message
        content = message.content if isinstance(message.content, str) else None
        if content is None:
            return message
        path = _tool_call_path(request.tool_call)
        if path is None:
            return message
        entry = build_skill_entry_metadata_from_read(path, content, skills_root=self._skills_root)
        if entry is None:
            return message
        existing = dict(message.additional_kwargs or {})
        existing[SKILL_CONTEXT_ENTRY_KEY] = dict(entry)
        message.additional_kwargs = existing
        return message

    def _maybe_stamp(self, result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | Command:
        """Apply producer-bound metadata for tool results that need it."""
        if not isinstance(result, ToolMessage):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        return self._stamp_skill_read_metadata(result, request, tool_name=tool_name)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            result = handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (sync): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp(result, request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            result = await handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (async): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp(result, request))


def _build_runtime_middlewares(
    *,
    app_config: AppConfig,
    include_uploads: bool,
    include_dangling_tool_call_patch: bool,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    """Build shared base middlewares for agent execution."""
    from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from deerflow.agents.middlewares.tool_result_sanitization_middleware import ToolResultSanitizationMiddleware
    from deerflow.sandbox.middleware import SandboxMiddleware

    # Layer 1 — outermost wrap_model_call wrappers (listed outer→inner).
    # InputSanitizationMiddleware is first so it becomes the outermost
    # wrapper — sanitised messages are what every inner middleware sees.
    # ToolResultSanitizationMiddleware mirrors that guardrail for the other
    # untrusted-content entry point: remote tool results (web_fetch /
    # web_search) get the same framework/injection-tag neutralization. It sits
    # inner of ToolOutputBudgetMiddleware (listed after it) so it neutralizes
    # the raw tool output first; the budget wrapper then truncates the already
    # neutralized text.
    outer_wrappers: list[AgentMiddleware] = [
        InputSanitizationMiddleware(),
        ToolOutputBudgetMiddleware.from_app_config(app_config),
        ToolResultSanitizationMiddleware(),
    ]

    # Layer 2 — before_agent hooks that read/annotate thread-scoped data.
    thread_hooks: list[AgentMiddleware] = [
        ThreadDataMiddleware(lazy_init=lazy_init),
    ]
    if include_uploads:
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

        thread_hooks.append(UploadsMiddleware())
    thread_hooks.append(SandboxMiddleware(lazy_init=lazy_init))

    # Layer 3 — post-processing append-only middlewares.
    tail: list[AgentMiddleware] = []
    if include_dangling_tool_call_patch:
        from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        tail.append(DanglingToolCallMiddleware())
    tail.append(LLMErrorHandlingMiddleware(app_config=app_config))

    # Guardrail middleware (if configured)
    guardrails_config = app_config.guardrails
    if guardrails_config.enabled and guardrails_config.provider:
        import inspect

        from deerflow.guardrails.middleware import GuardrailMiddleware
        from deerflow.reflection import resolve_variable

        provider_cls = resolve_variable(guardrails_config.provider.use)
        provider_kwargs = dict(guardrails_config.provider.config) if guardrails_config.provider.config else {}
        # Pass framework hint if the provider accepts it (e.g. for config discovery).
        # Built-in providers like AllowlistProvider don't need it, so only inject
        # when the constructor accepts 'framework' or '**kwargs'.
        if "framework" not in provider_kwargs:
            try:
                sig = inspect.signature(provider_cls.__init__)
                if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    provider_kwargs["framework"] = "deerflow"
            except (ValueError, TypeError):
                pass
        provider = provider_cls(**provider_kwargs)
        tail.append(GuardrailMiddleware(provider, fail_closed=guardrails_config.fail_closed, passport=guardrails_config.passport))

    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    tail.append(SandboxAuditMiddleware())

    # ReadBeforeWriteMiddleware is the outermost write gate: it blocks writes to files
    # the model hasn't read in their current version.  It must sit outside ToolProgress
    # and ToolErrorHandling so that a blocked write returns immediately without consuming
    # a ToolProgress slot.  The middleware stamps deerflow_tool_meta on the blocked
    # ToolMessage itself so downstream callers receive a well-formed result.
    if app_config.read_before_write.enabled:
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        tail.append(ReadBeforeWriteMiddleware())

    # ToolProgressMiddleware must be outer (lower index) so its wrap_tool_call handler
    # chain includes ToolErrorHandlingMiddleware (inner), which stamps deerflow_tool_meta
    # on every result before ToolProgressMiddleware reads it in _update_state_from_result.
    # Framework rule: first in list = outermost (types.py: "compose with first in list as outermost layer").
    tool_progress_config = app_config.tool_progress
    _ToolProgressMiddleware = None
    if tool_progress_config.enabled:
        from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware as _ToolProgressMiddleware

        tail.append(_ToolProgressMiddleware.from_config(tool_progress_config))

    tail.append(ToolErrorHandlingMiddleware(app_config=app_config))

    middlewares = [*outer_wrappers, *thread_hooks, *tail]

    # Guard: ToolProgressMiddleware (outer) must appear before ToolErrorHandlingMiddleware (inner)
    # so that its wrap_tool_call chain encloses the stamping step.  Fail loudly at build time
    # rather than silently no-oping at runtime if a future insertion reverses the order.
    # Uses isinstance (not type().__name__) so subclasses and renames are covered.
    if _ToolProgressMiddleware is not None:
        _progress_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, _ToolProgressMiddleware)), None)
        _error_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, ToolErrorHandlingMiddleware)), None)
        if _progress_idx is not None and _error_idx is not None and _progress_idx > _error_idx:
            raise RuntimeError(f"ToolProgressMiddleware must be outer (index {_progress_idx}) of ToolErrorHandlingMiddleware (index {_error_idx}) — check middleware append order")

    return middlewares


def build_lead_runtime_middlewares(*, app_config: AppConfig, lazy_init: bool = True) -> list[AgentMiddleware]:
    """Middlewares shared by lead agent runtime before lead-only middlewares."""
    return _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=True,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )


def build_subagent_runtime_middlewares(
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
    deferred_setup: "DeferredToolSetup | None" = None,
    mcp_routing_middleware: AgentMiddleware | None = None,
    agent_name: str | None = None,
) -> list[AgentMiddleware]:
    """Middlewares shared by subagent runtime before subagent-only middlewares."""
    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()

    middlewares = _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=False,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )

    if model_name is None and app_config.models:
        model_name = app_config.models[0].name

    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        middlewares.append(ViewImageMiddleware())

    if mcp_routing_middleware is not None:
        middlewares.append(mcp_routing_middleware)

    # Hide deferred (MCP) tool schemas from the subagent's model binding until
    # tool_search promotes them. This is the same wiring the lead agent gets. The deferred
    # set + catalog hash come from the build-time setup (assembled after
    # tool-policy filtering); promotion is read from graph state. Empty/None
    # setup (deferral disabled or no MCP tool survived) is a pure no-op.
    if deferred_setup is not None and deferred_setup.deferred_names:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middlewares.append(DeferredToolFilterMiddleware(deferred_setup.deferred_names, deferred_setup.catalog_hash))
        from deerflow.agents.middlewares.mcp_routing_middleware import assert_mcp_routing_before_deferred_filter

        assert_mcp_routing_before_deferred_filter(middlewares)

    # LoopDetectionMiddleware — subagents inherit none of the lead's runaway
    # guards today (see #3875): with no loop detection a degenerate subagent tool
    # loop runs unchecked until ``max_turns``, re-sending a growing context each
    # turn (the reported 4.4M-token burn). Mirror the lead chain so the loop is
    # detected and broken. Subagents disallow ``task``, so only the tool-loop
    # heuristic can fire here — no recursive-delegation path to false-positive on.
    # Registered before SafetyFinishReasonMiddleware (earlier in the list).
    # LangChain dispatches after_model hooks in REVERSE registration order, so
    # SafetyFinishReasonMiddleware (appended below) executes first and strips
    # safety-terminated tool_calls; LoopDetectionMiddleware then accounts on the
    # cleaned message. This is the placement SafetyFinishReasonMiddleware's
    # docstring requires ("register after LoopDetection") and mirrors the lead
    # chain (``lead_agent/agent.py``). Phase 1 of #3875; a deterministic
    # turn/token budget with lead-visible stop reason is Phase 2.
    loop_detection_config = app_config.loop_detection
    if loop_detection_config.enabled:
        from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

        middlewares.append(LoopDetectionMiddleware.from_config(loop_detection_config))

    # TokenBudgetMiddleware — subagents inherit none of the lead's cost backstops
    # today (#3875 Phase 2): a degenerate subagent can burn pathological token
    # volume (the reported 4.4M run) before max_turns/timeout engage. Mirror the
    # lead chain so the per-run budget hard-stop engages. ``subagents.token_budget``
    # is enabled by default; per-agent override via
    # ``subagents.agents.<name>.token_budget``. The hard-stop does not raise —
    # it strips tool_calls so the run completes with a final answer — and the
    # executor reads ``consume_stop_reason`` to mark the completed result
    # ``token_capped`` for the lead. State is keyed by run_id and each task run
    # builds a fresh middleware instance (see ``executor._create_agent``), so
    # parallel subagents cannot cross-contaminate even though they share the
    # parent thread_id/run_id in context.
    #
    # Default-ceiling coupling (#3875 Phase 3 review): the default ``max_tokens``
    # is re-coupled to ``summarization.enabled`` — 1M when compaction is on, 2M
    # when off. This ONLY applies to the default; a user-set budget (global or
    # per-agent) always wins, so a deployment that pinned a value is never
    # silently changed by flipping the summarization switch.
    summarization_enabled = app_config.summarization.enabled
    if agent_name is not None:
        token_budget_config = app_config.subagents.get_token_budget_for(agent_name, summarization_enabled=summarization_enabled)
    else:
        token_budget_config = app_config.subagents.token_budget
    if token_budget_config.enabled:
        from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware

        middlewares.append(TokenBudgetMiddleware.from_config(token_budget_config))

    # Same provider safety-termination guard the lead agent uses — subagents
    # are equally exposed to truncated tool_calls returned with
    # finish_reason=content_filter (and friends), and the bad call would then
    # propagate back to the lead agent via the task tool result.
    safety_config = app_config.safety_finish_reason
    if safety_config.enabled:
        from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    # DurableContextMiddleware (#4039) — summarization stores compacted history in the
    # ``summary_text`` state channel instead of writing a summary message back
    # into ``messages``. Mirror the lead chain so subagents project that summary
    # into subsequent model requests; otherwise a message-count keep policy can
    # leave an assistant tool-call + tool-result tail with no leading user
    # context, which strict providers reject. The same middleware also keeps
    # skill references durable when their original read results are compacted.
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    middlewares.append(
        DurableContextMiddleware(
            skills_container_path=app_config.skills.container_path,
            skill_file_read_tool_names=app_config.summarization.skill_file_read_tool_names,
        )
    )

    # DeerFlowSummarizationMiddleware — subagents inherit none of the lead's
    # context compaction today (#3875 Phase 3): a deep-research subagent
    # (``max_turns`` up to 150) can accumulate >1M cumulative input before
    # max_turns/timeout/token_budget engage, even though Phase 2's budget now
    # caps the pathological tail. Gated on the SAME
    # ``app_config.summarization.enabled`` switch the lead reads (per
    # maintainer guidance in #3875) so a single config covers both chains —
    # no separate ``subagents.summarization`` field. The shared factory
    # returns ``None`` when summarization is disabled, so this is a pure
    # no-op when the switch is off. Trigger/keep/model/prompt all come from
    # the same ``summarization`` config the lead reads, so the two chains
    # cannot drift.
    #
    # Placement differs from the lead chain: the lead appends summarization
    # BEFORE the guard trio (loop/token/safety), here it is appended AFTER.
    # This is benign — compaction runs in ``before_model`` regardless of
    # relative position, and the guard middlewares account in ``after_model``
    # — but noted because the relative order is not an exact mirror.
    #
    # ``skip_memory_flush=True``: the factory otherwise attaches
    # ``memory_flush_hook`` (when ``memory.enabled``), which flushes
    # pre-compaction messages into the durable memory queue keyed by
    # ``thread_id``. Subagents share the parent's ``thread_id`` in context, so
    # without skipping the hook a subagent's internal turns would be written
    # into the PARENT thread's durable memory (#3875 Phase 3 review).
    #
    # The middleware rewrites history via ``RemoveMessage(id=REMOVE_ALL_MESSAGES)``,
    # which shrinks the messages channel mid-run;
    # ``capture_new_step_messages`` must tolerate that contraction (see
    # ``step_events.py``) or it drops steps captured after the compaction
    # point. It does not implement ``consume_stop_reason``, so it does not
    # interfere with the Phase 2 guard-cap stop-reason channel.
    from deerflow.agents.middlewares.summarization_middleware import create_summarization_middleware

    summarization_middleware = create_summarization_middleware(
        app_config=app_config,
        skip_memory_flush=True,
    )
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # SystemMessageCoalescingMiddleware (#4040) — DurableContextMiddleware above
    # inserts a second ``SystemMessage(authority_contract)`` after the leading
    # system prompt (subagents carry their prompt as a leading ``SystemMessage``
    # in ``messages``, not via ``create_agent(system_prompt=...)``). Two system
    # messages — or a non-leading one — are exactly what the strict backends this
    # targets (vLLM/SGLang/Qwen/Anthropic) reject, so the durable fix would trade
    # #4039's assistant-first 400 for a duplicate-system 400. Mirror the lead
    # chain: append the coalescer innermost so it merges every SystemMessage into
    # one leading ``system_message`` on the outgoing request. It only rewrites the
    # per-request payload (no ``after_model``/``consume_stop_reason``), so it is
    # inert to the Phase 2 guard-cap channel, and must sit inner of
    # DurableContextMiddleware to observe the injected system message.
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    middlewares.append(SystemMessageCoalescingMiddleware())

    return middlewares
