"""Lead agent factory.

INVARIANT — tracing callback placement
======================================

Tracing callbacks (Langfuse, LangSmith) are attached at the **graph
invocation root** in :func:`_make_lead_agent` (see the
``build_tracing_callbacks()`` block that appends to ``config["callbacks"]``).
Every ``create_chat_model(...)`` call inside this module — and inside any
middleware reachable from this graph (e.g. ``TitleMiddleware``) — MUST pass
``attach_tracing=False``.

Forgetting that flag emits duplicate spans (one rooted at the graph, one at
the model) AND prevents the Langfuse handler's ``propagate_attributes``
path from firing, so ``session_id`` / ``user_id`` never reach the trace.
The five current sites are: bootstrap agent, default agent, summarization
middleware, the async path inside ``TitleMiddleware``, and the skill security
scanner reached from the ``skill_manage`` tool (``skills/security_scanner.py``'s
``scan_skill_content``, which is dual-use: ``_scan_or_raise`` in
``tools/skill_manage_tool.py`` is the in-graph choke point and passes the flag,
while its standalone callers keep the default). Any new in-graph
``create_chat_model`` call must add to this list and pass the flag.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.configured_extensions import load_configured_extension_middlewares
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.model_length_finish_reason_middleware import ModelLengthFinishReasonMiddleware
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, create_summarization_middleware
from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
from deerflow.agents.middlewares.token_usage_middleware import TokenUsageMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import get_thread_state_schema, normalize_middleware_state_schemas
from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthzDecision, AuthzRequest
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.agents_config import load_agent_config, validate_agent_name
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.memory_config import should_use_memory_tools
from deerflow.config.subagents_config import DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
from deerflow.models import create_chat_model
from deerflow.runtime.checkpoint_mode import (
    INTERNAL_CHECKPOINT_MODE_KEY,
    freeze_checkpoint_channel_mode,
    freeze_checkpoint_snapshot_frequency,
    frozen_checkpoint_channel_mode,
    inject_checkpoint_mode,
)
from deerflow.skills.types import Skill
from deerflow.tracing import build_tracing_callbacks

logger = logging.getLogger(__name__)

_BOOTSTRAP_SKILL_NAMES = {"bootstrap"}
_NON_INTERACTIVE_DISABLED_TOOL_NAMES = frozenset({"ask_clarification"})

# Channels whose inbound messages originate from untrusted external
# commenters (anyone on a GitHub repo, etc.) and whose run context is
# therefore unsafe for admin-shaped tools like ``update_agent``. The
# corresponding gate lives in :func:`_make_lead_agent`; the channel name
# itself is plumbed into ``run_context`` by
# ``ChannelManager._resolve_run_params``.
_WEBHOOK_CHANNELS: frozenset[str] = frozenset({"github"})


@dataclass(frozen=True)
class LeadAgentAssembly:
    """The compiled graph plus what it was assembled from.

    ``descriptor`` is typed loosely on purpose: this module is imported during
    LangGraph Server startup and must not pull the extension contract package
    into that import path.
    """

    graph: Any
    descriptor: Any


def unwrap_agent_graph(agent_result: Any) -> Any:
    """Unwrap a lead assembly, leaving any other factory result untouched.

    The Gateway factory returns ``LeadAgentAssembly(graph, descriptor)``, but a
    third-party or test factory may still return a bare graph. Type-checking
    the result rather than duck-typing ``.graph`` keeps both contracts valid.

    Lives beside the dataclass so "what counts as an assembly, and which
    attribute holds the graph" is answered in one place. Callers that must
    survive this module failing to import (the runtime worker, the Gateway's
    state accessor — both of which have to keep serving custom factories that
    never produce an assembly) guard the import and fall back to the result
    unchanged.
    """
    return agent_result.graph if isinstance(agent_result, LeadAgentAssembly) else agent_result


def _default_max_total_subagents(app_config: object) -> int:
    subagents_config = getattr(app_config, "subagents", None)
    return getattr(subagents_config, "max_total_per_run", DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN)


def _subagent_release_policy(
    app_config: AppConfig,
    *,
    enabled: bool,
    max_concurrent: int,
    max_total: int,
) -> dict[str, object]:
    """Delegation limits as the run will actually enforce them.

    The per-type turn/timeout caps are read here rather than left implicit
    because a subagent config edit changes what the lead agent can spend
    without changing anything visible in the lead's own configuration.
    """
    policy: dict[str, object] = {
        "enabled": enabled,
        "max_concurrent": max_concurrent,
        "max_total": max_total,
        "type_allowlist": [],
        "runtime_limits": {},
    }
    if not enabled:
        return policy

    from deerflow.subagents import get_available_subagent_names, get_subagent_config

    type_allowlist = sorted(set(get_available_subagent_names(app_config=app_config)))
    runtime_limits: dict[str, object] = {}
    for name in type_allowlist:
        subagent_config = get_subagent_config(name, app_config=app_config)
        if subagent_config is None:
            continue
        runtime_limits[name] = {
            "max_turns": subagent_config.max_turns,
            "timeout_seconds": subagent_config.timeout_seconds,
        }
    policy["type_allowlist"] = type_allowlist
    policy["runtime_limits"] = runtime_limits
    return policy


def _resolve_runtime_option(cfg: dict, key: str, agent_value, default):
    """Resolve a runtime option with ``request > agent config > default`` precedence.

    ``key in cfg`` (not ``cfg.get(key)``) distinguishes "request omitted the
    field" from "request set it to a falsy value", so a request-supplied
    ``thinking_enabled: false`` is honored instead of falling through to the
    agent default. ``agent_value`` is used only when it is not ``None`` (a
    custom agent's unset field means "do not override" — issue #4336).
    """
    if key in cfg:
        return cfg[key]
    if agent_value is not None:
        return agent_value
    return default


def _append_memory_tools_without_name_conflicts(tools: list) -> None:
    """Append memory tools without dropping unrelated duplicate-named tools."""
    from deerflow.agents.memory.tools import get_memory_tools

    existing_names = {getattr(tool, "name", None) for tool in tools}
    for memory_tool in get_memory_tools():
        if memory_tool.name in existing_names:
            logger.warning("Memory tool name %r already exists and was skipped.", memory_tool.name)
            continue
        tools.append(memory_tool)
        existing_names.add(memory_tool.name)


def _get_runtime_config(config: RunnableConfig) -> dict:
    """Merge legacy configurable options with LangGraph runtime context."""
    cfg = dict(config.get("configurable", {}) or {})
    context = config.get("context", {}) or {}
    if isinstance(context, dict):
        cfg.update(context)
    return cfg


def _resolve_model_name(requested_model_name: str | None = None, *, app_config: AppConfig | None = None) -> str:
    """Resolve a runtime model name safely, falling back to default if invalid. Returns None if no models are configured."""
    app_config = app_config or get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(f"Model '{requested_model_name}' not found in config; fallback to default model '{default_model_name}'.")
    return default_model_name


def _authorize_model_name(
    model_name: str,
    *,
    context: Mapping[str, Any],
    app_config: AppConfig,
) -> str:
    """Enforce ``model:use`` authorization on the resolved model name.

    When ``authorization.enabled`` is false this is a no-op (returns
    *model_name* unchanged). When enabled, the resolved model is checked
    against the provider's policy via ``authorize("model", "use")`` so the
    runtime path and the Gateway ``get_model`` route enforce the same
    action-scoped contract (matters for custom providers that distinguish
    ``list`` from ``use``). On deny, a graceful fallback to the first
    ``filter_resources``-allowed model is attempted (RFC §9: "fall back to an
    allowed default, not error, to avoid breaking runs"). If no model is
    allowed and ``fail_closed`` is true, ``ValueError`` is raised (matching
    the existing "no models configured" contract); fail-open returns the
    original name.

    Mirrors the Principal/provider pattern of ``apply_tool_authorization`` so
    the tool path and the model path share one identity source.
    """
    authz_config = app_config.authorization
    if authz_config.enabled is not True:
        return model_name

    provider = resolve_authorization_provider(authz_config)
    if provider is None:
        return model_name

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    all_names = [m.name for m in app_config.models]

    # Check the resolved model against the action-scoped ``model:use`` policy.
    # This aligns with the Gateway ``get_model`` route, which also checks
    # ``authorize("model", "use")``. For the built-in RBAC provider (which
    # ignores ``action``) this is equivalent to a membership check; for a
    # custom provider that distinguishes ``list`` from ``use``, it prevents
    # a model visible via ``filter_resources`` but denied for ``use`` from
    # being silently selected at runtime.
    try:
        decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=model_name))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
        if decision.allow:
            return model_name
    except Exception:
        logger.warning("Authorization provider failed while checking model:use for '%s'", model_name, exc_info=True)
        if authz_config.fail_closed:
            raise ValueError("No models are authorized for the current role (authorization provider error).")
        return model_name

    # Denied — graceful fallback: pick the first model that ``filter_resources``
    # says is visible AND that also passes ``authorize("model", "use")``. For the
    # built-in RBAC provider (which ignores ``action``) this is equivalent to
    # picking the first visible name; for a custom provider that distinguishes
    # ``list`` from ``use``, it ensures the fallback is actually usable.
    try:
        allowed_names = provider.filter_resources(principal, "model", all_names)
        if not isinstance(allowed_names, list) or any(not isinstance(n, str) for n in allowed_names):
            raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
    except Exception:
        logger.warning("Authorization provider failed while resolving allowed models", exc_info=True)
        if authz_config.fail_closed:
            raise ValueError("No models are authorized for the current role (authorization provider error).")
        return model_name

    for candidate in allowed_names:
        if candidate == model_name:
            continue  # already denied above
        try:
            cb_decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=candidate))
            if isinstance(cb_decision, AuthzDecision) and cb_decision.allow:
                logger.warning(
                    "Model '%s' is not authorized for the current role; fallback to '%s'.",
                    model_name,
                    candidate,
                )
                return candidate
        except Exception:
            logger.warning(
                "Authorization provider failed while checking model:use fallback for '%s'",
                candidate,
                exc_info=True,
            )
            if authz_config.fail_closed:
                raise ValueError("No models are authorized for the current role (authorization provider error).")
            return model_name
    if authz_config.fail_closed:
        raise ValueError("No models are authorized for the current role.")
    logger.warning("No models are authorized for the current role; fail_open allows '%s'.", model_name)
    return model_name


def _create_summarization_middleware(
    *,
    app_config: AppConfig | None = None,
    run_model_name: str | None = None,
    extensions=None,
) -> DeerFlowSummarizationMiddleware | None:
    """Create and configure the summarization middleware from config.

    ``run_model_name`` is the resolved run model; it is the source of truth for
    ``model_name: null`` summarization and the explicit-summary-model fallback, so a
    custom agent's model is used instead of ``config.models[0]``.
    """
    return create_summarization_middleware(
        app_config=app_config,
        run_model_name=run_model_name,
        extensions=extensions,
    )


def _create_todo_list_middleware(is_plan_mode: bool) -> TodoMiddleware | None:
    """Create and configure the TodoList middleware.

    Args:
        is_plan_mode: Whether to enable plan mode with TodoList middleware.

    Returns:
        TodoMiddleware instance if plan mode is enabled, None otherwise.
    """
    if not is_plan_mode:
        return None

    # Custom prompts matching DeerFlow's style
    system_prompt = """
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly

**When to Use:**
This tool is designed for complex objectives that require systematic tracking:
- Complex multi-step tasks requiring 3+ distinct steps
- Non-trivial tasks needing careful planning and execution
- User explicitly requests a todo list
- User provides multiple tasks (numbered or comma-separated list)
- The plan may need revisions based on intermediate results

**When NOT to Use:**
- Single, straightforward tasks
- Trivial tasks (< 3 steps)
- Purely conversational or informational requests
- Simple tool calls where the approach is obvious

**Best Practices:**
- Break down complex tasks into smaller, actionable steps
- Use clear, descriptive task names
- Remove tasks that become irrelevant
- Add new tasks discovered during implementation
- Don't be afraid to revise the todo list as you learn more

**Task Management:**
Writing todos takes time and tokens - use it when helpful for managing complex problems, not for simple requests.
</todo_list_system>
"""

    tool_description = """Use this tool to create and manage a structured task list for complex work sessions.

**IMPORTANT: Only use this tool for complex tasks (3+ steps). For simple requests, just do the work directly.**

## When to Use

Use this tool in these scenarios:
1. **Complex multi-step tasks**: When a task requires 3 or more distinct steps or actions
2. **Non-trivial tasks**: Tasks requiring careful planning or multiple operations
3. **User explicitly requests todo list**: When the user directly asks you to track tasks
4. **Multiple tasks**: When users provide a list of things to be done
5. **Dynamic planning**: When the plan may need updates based on intermediate results

## When NOT to Use

Skip this tool when:
1. The task is straightforward and takes less than 3 steps
2. The task is trivial and tracking provides no benefit
3. The task is purely conversational or informational
4. It's clear what needs to be done and you can just do it

## How to Use

1. **Starting a task**: Mark it as `in_progress` BEFORE beginning work
2. **Completing a task**: Mark it as `completed` IMMEDIATELY after finishing
3. **Updating the list**: Add new tasks, remove irrelevant ones, or update descriptions as needed
4. **Multiple updates**: You can make several updates at once (e.g., complete one task and start the next)

## Task States

- `pending`: Task not yet started
- `in_progress`: Currently working on (can have multiple if tasks run in parallel)
- `completed`: Task finished successfully

## Task Completion Requirements

**CRITICAL: Only mark a task as completed when you have FULLY accomplished it.**

Never mark a task as completed if:
- There are unresolved issues or errors
- Work is partial or incomplete
- You encountered blockers preventing completion
- You couldn't find necessary resources or dependencies
- Quality standards haven't been met

If blocked, keep the task as `in_progress` and create a new task describing what needs to be resolved.

## Best Practices

- Create specific, actionable items
- Break complex tasks into smaller, manageable steps
- Use clear, descriptive task names
- Update task status in real-time as you work
- Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
- Remove tasks that are no longer relevant
- **IMPORTANT**: When you write the todo list, mark your first task(s) as `in_progress` immediately
- **IMPORTANT**: Unless all tasks are completed, always have at least one task `in_progress` to show progress

Being proactive with task management demonstrates thoroughness and ensures all requirements are completed successfully.

**Remember**: If you only need a few tool calls to complete a task and it's clear what to do, it's better to just do the task directly and NOT use this tool at all.
"""

    return TodoMiddleware(system_prompt=system_prompt, tool_description=tool_description)


# ThreadDataMiddleware must be before SandboxMiddleware to ensure thread_id is available
# UploadsMiddleware should be after ThreadDataMiddleware to access thread_id
# DanglingToolCallMiddleware patches missing ToolMessages before model sees the history
# SummarizationMiddleware should be early to reduce context before other processing
# TodoListMiddleware should be before ClarificationMiddleware to allow todo management
# TitleMiddleware generates title after first exchange
# MemoryMiddleware queues conversation for memory update (after TitleMiddleware)
# ViewImageMiddleware should be before ClarificationMiddleware to inject image details before LLM
# ToolErrorHandlingMiddleware should be before ClarificationMiddleware to convert tool exceptions to ToolMessages
# ClarificationMiddleware should be last to intercept clarification requests after model calls
def build_middlewares(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str | None = None,
    custom_middlewares: list[AgentMiddleware] | None = None,
    *,
    available_skills: set[str] | None = None,
    app_config: AppConfig | None = None,
    deferred_setup=None,
    mcp_routing_middleware: AgentMiddleware | None = None,
    user_id: str | None = None,
    authorization_provider=None,
    extensions=None,
):
    """Build the lead-agent middleware chain based on runtime configuration.

    Public entry point for the lead agent's full middleware composition. Used by
    ``make_lead_agent`` and by the embedded ``DeerFlowClient`` (a lead-agent variant
    that needs the identical chain). Keep this name stable: it is imported across a
    module boundary, so renames/signature changes ripple into ``client.py``.

    Args:
        config: Runtime configuration containing configurable options like is_plan_mode.
        model_name: Resolved runtime model name; gates vision-only middleware.
        agent_name: If provided, MemoryMiddleware will use per-agent memory storage.
        custom_middlewares: Optional list of custom middlewares to inject into the chain.
        app_config: Explicit AppConfig; falls back to ``get_app_config()`` when omitted.
        deferred_setup: Optional deferred-MCP-tool setup that attaches
            ``DeferredToolFilterMiddleware`` when ``tool_search`` is enabled.
        mcp_routing_middleware: Optional PR2 middleware that auto-promotes
            deferred MCP schemas before the deferred filter runs.
        user_id: Effective user ID for user-scoped skill loading. Passed through
            to ``SkillActivationMiddleware`` so it can resolve per-user custom skills.
        authorization_provider: Provider already resolved for assembly-time
            filtering. Reused by the execution-time authorization middleware.
        extensions: Loaded extensions whose middleware contributions are merged
            into the final stack. Defaults to the process-wide set.

    Returns:
        List of middleware instances.
    """
    resolved_app_config = app_config or get_app_config()
    from deerflow.extensions import get_agent_build_extensions

    resolved_extensions = extensions if extensions is not None else get_agent_build_extensions()
    runtime_middleware_kwargs = {
        "app_config": resolved_app_config,
        "lazy_init": True,
    }
    if authorization_provider is not None:
        runtime_middleware_kwargs["authorization_provider"] = authorization_provider
    if authorization_provider is not None and deferred_setup is not None:
        runtime_middleware_kwargs["deferred_setup"] = deferred_setup
    middlewares = build_lead_runtime_middlewares(**runtime_middleware_kwargs)

    # Always inject current date (and optionally memory) as <system-reminder> into the
    # first HumanMessage to keep the system prompt fully static for prefix-cache reuse.
    from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware

    middlewares.append(DynamicContextMiddleware(agent_name=agent_name, app_config=resolved_app_config))

    # Deterministically load a full SKILL.md when the user starts the turn with
    # /skill-name. This keeps the base system prompt metadata-only while giving
    # explicit user activation priority over model-side relevance guessing.
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

    slash_source_owner_token = secrets.token_urlsafe(24)
    middlewares.append(
        SkillActivationMiddleware(
            available_skills=available_skills,
            app_config=resolved_app_config,
            user_id=user_id,
            slash_source_owner_token=slash_source_owner_token,
        )
    )

    # Enabled skills are only discoverable metadata. Apply allowed-tools at
    # runtime after explicit slash activation or an actual skill-file load.
    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    middlewares.append(
        SkillToolPolicyMiddleware(
            available_skills=available_skills,
            app_config=resolved_app_config,
            user_id=user_id,
            slash_source_owner_token=slash_source_owner_token,
        )
    )

    # Capture completed task delegations and loaded skill files before
    # summarization can compact them, then inject durable context channels
    # (summary + ledger + skills) into model calls.
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    middlewares.append(
        DurableContextMiddleware(
            skills_container_path=resolved_app_config.skills.container_path,
            skill_file_read_tool_names=resolved_app_config.summarization.skill_file_read_tool_names,
        )
    )

    # Add summarization middleware if enabled
    summarization_middleware = _create_summarization_middleware(
        app_config=resolved_app_config,
        run_model_name=model_name,
        extensions=resolved_extensions,
    )
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # Add TodoList middleware if plan mode is enabled
    cfg = _get_runtime_config(config)
    is_plan_mode = cfg.get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # Add TokenUsageMiddleware when token_usage tracking is enabled
    if resolved_app_config.token_usage.enabled:
        middlewares.append(TokenUsageMiddleware())

    # Add TitleMiddleware
    middlewares.append(
        TitleMiddleware(
            app_config=resolved_app_config,
            extensions=resolved_extensions,
        )
    )

    # Add MemoryMiddleware after TitleMiddleware. Tool mode normally skips it;
    # conversation-extraction backends may explicitly retain passive writes.
    if should_use_memory_tools(resolved_app_config.memory):
        from deerflow.agents.memory.manager import backend_requires_passive_writes_in_tool_mode

        if backend_requires_passive_writes_in_tool_mode(resolved_app_config.memory.manager_class):
            middlewares.append(MemoryMiddleware(agent_name=agent_name, memory_config=resolved_app_config.memory))
    else:
        if resolved_app_config.memory.mode == "tool" and not resolved_app_config.memory.enabled:
            logger.warning("memory.mode is 'tool' but memory.enabled is false; memory tools will not be registered.")
        middlewares.append(MemoryMiddleware(agent_name=agent_name, memory_config=resolved_app_config.memory))

    # Add ViewImageMiddleware only if the current model supports vision.
    # Use the resolved runtime model_name from make_lead_agent to avoid stale config values.
    model_config = resolved_app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # Auto-promote deferred MCP schemas from PR1 routing metadata before the
    # deferred filter decides which schemas to hide for this model call.
    if mcp_routing_middleware is not None:
        middlewares.append(mcp_routing_middleware)

    # Hide deferred tool schemas from model binding until tool_search promotes them.
    # The lead deferred set + catalog hash come from the full build-time MCP
    # catalog; SkillToolPolicyMiddleware separately filters model visibility,
    # tool_search results, and execution for the active skill at runtime.
    if deferred_setup is not None and deferred_setup.deferred_names:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middlewares.append(DeferredToolFilterMiddleware(deferred_setup.deferred_names, deferred_setup.catalog_hash))
        from deerflow.agents.middlewares.mcp_routing_middleware import assert_mcp_routing_before_deferred_filter

        assert_mcp_routing_before_deferred_filter(middlewares)

    # Coalesce every SystemMessage into a single leading one before the request
    # reaches the provider. Strict backends (vLLM, SGLang, Qwen, Anthropic)
    # reject non-leading SystemMessages. See system_message_coalescing_middleware.py.
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    middlewares.append(SystemMessageCoalescingMiddleware())

    # Add SubagentLimitMiddleware to truncate excess parallel task calls
    subagent_enabled = cfg.get("subagent_enabled", False)
    effective_max_subagents_per_run: int | None = None
    if subagent_enabled:
        max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
        max_total_subagents = cfg.get("max_total_subagents", _default_max_total_subagents(resolved_app_config))
        effective_max_subagents_per_run = max_total_subagents
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents, max_total=max_total_subagents))

    # LoopDetectionMiddleware — detect and break repetitive tool call loops
    loop_detection_config = resolved_app_config.loop_detection
    if loop_detection_config.enabled:
        middlewares.append(LoopDetectionMiddleware.from_config(loop_detection_config))

    # TokenBudgetMiddleware - enforce per-run token limits
    token_budget_config = resolved_app_config.token_budget
    if token_budget_config.enabled:
        from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware

        middlewares.append(TokenBudgetMiddleware.from_config(token_budget_config))

    # Inject custom middlewares before ClarificationMiddleware
    if custom_middlewares:
        middlewares.extend(custom_middlewares)

    configured_middlewares = load_configured_extension_middlewares(resolved_app_config)
    if configured_middlewares:
        middlewares.extend(configured_middlewares)

    # A provider may return an empty AIMessage after tool execution. Retry the
    # final response once, then persist a visible error fallback rather than
    # allowing LangChain's no-tool-call router to end a silent successful run.
    middlewares.append(TerminalResponseMiddleware())

    # A provider may also cap the final assistant response at the model output
    # limit. Preserve the assistant content unchanged, but stamp a run-level
    # stop_reason so Gateway consumers can tell a length-capped completion from
    # a clean one.
    middlewares.append(ModelLengthFinishReasonMiddleware())

    # SafetyFinishReasonMiddleware — suppress tool execution when the provider
    # safety-terminated the response. Registered after the terminal-response
    # and custom/configured middlewares so LangChain's reverse-order after_model
    # dispatch runs Safety first; cleared tool_calls then flow through the
    # remaining accounting/terminal guards without firing extra alarms.
    safety_config = resolved_app_config.safety_finish_reason
    if safety_config.enabled:
        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    # ClarificationMiddleware should always be last
    middlewares.append(ClarificationMiddleware())

    # Extension contributions are merged only here, once the full stack exists.
    # Doing it inside build_lead_runtime_middlewares() would place
    # MODEL_PHYSICAL contributions above the lead-specific middlewares appended
    # above, changing what "the final request" means for observers.
    from deerflow_extension_api import AgentScope

    from deerflow.extensions.stack import compose_with_extensions

    if not resolved_extensions.has_middleware_contributors:
        return compose_with_extensions(middlewares, AgentScope.LEAD, None, resolved_extensions)

    from deerflow_extension_api import AgentBuildContext

    from deerflow.extensions.policy import project_host_policy

    return compose_with_extensions(
        middlewares,
        AgentScope.LEAD,
        AgentBuildContext(
            scope=AgentScope.LEAD,
            agent_name=agent_name,
            model_name=model_name,
            policy=project_host_policy(
                resolved_app_config,
                token_budget_config=token_budget_config,
                max_subagents_per_run=effective_max_subagents_per_run,
            ),
        ),
        resolved_extensions,
    )


def _available_skill_names(agent_config, is_bootstrap: bool) -> set[str] | None:
    if is_bootstrap:
        return set(_BOOTSTRAP_SKILL_NAMES)
    if agent_config and agent_config.skills is not None:
        return set(agent_config.skills)
    return None


def _load_enabled_available_skills(available_skills: set[str] | None, *, app_config: AppConfig, user_id: str | None = None) -> list[Skill]:
    try:
        from deerflow.agents.lead_agent.prompt import get_enabled_skills_for_config

        skills = get_enabled_skills_for_config(app_config, user_id=user_id)
    except Exception:
        logger.exception("Failed to load enabled skills")
        raise

    if available_skills is None:
        return skills
    return [skill for skill in skills if skill.name in available_skills]


def make_lead_agent(config: RunnableConfig):
    """LangGraph graph factory; keep the signature compatible with LangGraph Server."""
    return assemble_lead_agent(config).graph


def assemble_lead_agent(
    config: RunnableConfig,
    *,
    app_config: AppConfig | None = None,
) -> LeadAgentAssembly:
    """Return the compiled lead graph together with its assembly descriptor.

    Gateway workers use this explicit assembly result so what the agent was
    built from does not have to be recovered from LangGraph private runtime
    keys or mutable graph attributes. ``make_lead_agent`` remains the
    graph-only LangGraph Server ABI declared in ``langgraph.json``.
    """
    runtime_config = _get_runtime_config(config)
    runtime_app_config = app_config or runtime_config.get("app_config")
    if not isinstance(runtime_app_config, AppConfig):
        runtime_app_config = get_app_config()
    # Mode selection precedence, pinned by test_checkpoint_mode.py:
    # - First freeze: the app config owns the process mode; a client-supplied
    #   configurable key is ignored so a direct LangGraph request cannot
    #   reconfigure (or crash) a fresh process.
    # - Once frozen: an internally injected key (run worker / gateway) or the
    #   app config must match the frozen mode; ``freeze_checkpoint_channel_mode``
    #   fails closed on any mismatch, so neither a forged key nor a config.yaml
    #   change can silently reconfigure the process.
    frozen_mode = frozen_checkpoint_channel_mode()
    if frozen_mode is None:
        requested_mode = runtime_app_config.database.checkpoint_channel_mode
    else:
        requested_mode = (config.get("configurable", {}) or {}).get(
            INTERNAL_CHECKPOINT_MODE_KEY,
            runtime_app_config.database.checkpoint_channel_mode,
        )
    mode = freeze_checkpoint_channel_mode(requested_mode)
    # The snapshot cadence travels with the mode: restart-required, frozen
    # from the app config, and deliberately not client-injectable (a forged
    # configurable key must not recompile the channel table either).
    freeze_checkpoint_snapshot_frequency(runtime_app_config.database.checkpoint_delta.snapshot_frequency)
    inject_checkpoint_mode(config, mode)
    return _assemble_lead_agent(config, app_config=runtime_app_config)


def _make_lead_agent(config: RunnableConfig, *, app_config: AppConfig):
    """Internal graph-only entry point.

    Kept as a graph-returning wrapper because callers inside the harness (and
    the model-resolution tests) want the compiled graph without the mode
    freeze that :func:`assemble_lead_agent` performs.
    """
    return _assemble_lead_agent(config, app_config=app_config).graph


def _complete_assembly(
    *,
    config: RunnableConfig,
    graph: Any,
    namespace: str,
    agent_name: str,
    requested_model: str | None,
    effective_model: str,
    model_config: object,
    model_overrides: dict[str, object] | None = None,
    thinking_enabled: bool,
    reasoning_effort: object,
    rendered_base_prompt: str,
    tools: list[object],
    middlewares: list[object],
    deferred_names: frozenset[str],
    enabled_skills: list[object],
    effective_policies: dict[str, object],
) -> LeadAgentAssembly:
    """Describe the finished graph and hand the description to observers.

    The recursion limit is folded in here rather than at either call site: it
    is a per-invocation budget the Gateway clamps, so it belongs to the
    assembly even though nothing inside the factory chose it.

    Building the descriptor hashes every tool's description and JSON schema
    and probes every middleware — real work on every assembly. Skipped
    entirely when no observer is registered to receive it, mirroring
    ``notify_agent_assembled``'s own zero-observer fast path.
    """
    from deerflow.extensions import get_agent_build_extensions

    resolved_extensions = get_agent_build_extensions()
    if not resolved_extensions.has_agent_assembly_observers:
        return LeadAgentAssembly(graph=graph, descriptor=None)

    from deerflow.agents.assembly_descriptor import build_assembly_descriptor
    from deerflow.extensions.notify import notify_agent_assembled

    resolved_policies = dict(effective_policies)
    resolved_policies.setdefault(
        "recursion_limit",
        config.get("recursion_limit", "framework-default"),
    )
    descriptor = build_assembly_descriptor(
        namespace=namespace,
        agent_name=agent_name,
        requested_model=requested_model,
        effective_model=effective_model,
        model_config=model_config,
        model_overrides=model_overrides,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        rendered_base_prompt=rendered_base_prompt,
        tools=tools,
        middlewares=middlewares,
        deferred_names=deferred_names,
        enabled_skills=enabled_skills,
        effective_policies=resolved_policies,
    )
    notify_agent_assembled(descriptor, resolved_extensions)
    return LeadAgentAssembly(graph=graph, descriptor=descriptor)


def _assemble_lead_agent(config: RunnableConfig, *, app_config: AppConfig) -> LeadAgentAssembly:
    # Lazy import to avoid circular dependency
    from deerflow.tools import get_available_tools
    from deerflow.tools.builtins import setup_agent, update_agent
    from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware, get_mcp_routing_hints_prompt_section

    cfg = _get_runtime_config(config)
    resolved_app_config = app_config
    mode = (config.get("configurable", {}) or {}).get(
        INTERNAL_CHECKPOINT_MODE_KEY,
        resolved_app_config.database.checkpoint_channel_mode,
    )

    # Resolve one authoritative identity for every user-scoped factory input.
    # Agent Server's reserved auth fields win over ordinary client-supplied
    # context/configurable values; the embedded Gateway path uses context.user_id.
    from deerflow.runtime.user_context import resolve_config_user_id

    resolved_user_id = resolve_config_user_id(config)

    requested_model_name: str | None = cfg.get("model_name") or cfg.get("model")
    is_plan_mode = cfg.get("is_plan_mode", False)
    requested_subagent_enabled = cfg.get("subagent_enabled", False)
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    max_total_subagents = cfg.get("max_total_subagents", _default_max_total_subagents(resolved_app_config))
    is_bootstrap = cfg.get("is_bootstrap", False)
    non_interactive = bool(cfg.get("non_interactive", False))
    agent_name = validate_agent_name(cfg.get("agent_name"))

    agent_config = load_agent_config(agent_name, user_id=resolved_user_id) if not is_bootstrap else None
    # Keep compatibility with lightweight AgentConfig-shaped objects used by
    # integrations that predate caller-level subagent restrictions.
    allowed_subagents = getattr(agent_config, "allowed_subagents", None) if agent_config is not None else None
    # The request switch may disable delegation, but it can never widen the
    # server-side custom-agent policy. An explicit empty list is a hard deny.
    subagent_enabled = bool(requested_subagent_enabled and allowed_subagents != [])
    config.setdefault("configurable", {})["subagent_enabled"] = subagent_enabled
    if isinstance(config.get("context"), dict):
        config["context"]["subagent_enabled"] = subagent_enabled
    available_skills = _available_skill_names(agent_config, is_bootstrap)
    # Custom agent model from agent config (if any), or None to let _resolve_model_name pick the default
    agent_model_name = agent_config.model if agent_config and agent_config.model else None

    # thinking / reasoning precedence: request > custom agent default > runtime
    # default (issue #4336). See ``_resolve_runtime_option`` for the falsy-vs-unset
    # handling.
    agent_thinking = getattr(agent_config, "thinking_enabled", None) if agent_config else None
    agent_reasoning = getattr(agent_config, "reasoning_effort", None) if agent_config else None
    thinking_enabled = bool(_resolve_runtime_option(cfg, "thinking_enabled", agent_thinking, True))
    reasoning_effort = _resolve_runtime_option(cfg, "reasoning_effort", agent_reasoning, None)

    # Per-agent sampling overrides (temperature / max_tokens) layered on top of
    # the resolved model profile (issue #4336). None when the agent set none.
    agent_model_settings = getattr(agent_config, "model_settings", None) if agent_config else None
    agent_model_overrides = agent_model_settings.model_dump(exclude_none=True) if agent_model_settings else None

    # Final model name resolution: request → agent config → global default, with fallback for unknown names
    model_name = _resolve_model_name(requested_model_name or agent_model_name, app_config=resolved_app_config)

    # Phase 3: enforce model:use authorization. On deny, fall back to the first
    # allowed model (graceful) rather than crashing the run (RFC §9).
    model_name = _authorize_model_name(model_name, context=cfg, app_config=resolved_app_config)

    model_config = resolved_app_config.get_model_config(model_name)

    if model_config is None:
        raise ValueError("No chat model could be resolved. Please configure at least one model in config.yaml or provide a valid 'model_name'/'model' in the request.")
    if thinking_enabled and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False

    logger.info(
        "Create Agent(%s) -> thinking_enabled: %s, reasoning_effort: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s, max_total_subagents: %s",
        agent_name or "default",
        thinking_enabled,
        reasoning_effort,
        model_name,
        is_plan_mode,
        subagent_enabled,
        max_concurrent_subagents,
        max_total_subagents,
    )

    # Inject run metadata for LangSmith trace tagging
    if "metadata" not in config:
        config["metadata"] = {}

    config["metadata"].update(
        {
            "agent_name": agent_name or "default",
            "model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "is_plan_mode": is_plan_mode,
            "subagent_enabled": subagent_enabled,
            "tool_groups": agent_config.tool_groups if agent_config else None,
            "available_skills": sorted(available_skills) if available_skills is not None else None,
            "allowed_subagents": list(allowed_subagents) if allowed_subagents is not None else None,
        }
    )

    # Inject tracing callbacks at the graph invocation root so a single LangGraph
    # run produces one trace with all node / LLM / tool calls as child spans,
    # AND so the Langfuse handler sees ``on_chain_start(parent_run_id=None)`` and
    # actually propagates ``langfuse_session_id`` / ``langfuse_user_id`` from
    # ``config["metadata"]`` onto the trace. Without root-level attachment the
    # model is a nested observation and the handler strips ``langfuse_*`` keys.
    tracing_callbacks = build_tracing_callbacks()
    if tracing_callbacks:
        existing = config.get("callbacks") or []
        if not isinstance(existing, list):
            existing = list(existing)
        config["callbacks"] = [*existing, *tracing_callbacks]

    enabled_skills = _load_enabled_available_skills(available_skills, app_config=resolved_app_config, user_id=resolved_user_id)

    # Build skill search setup (deferred skill discovery).
    # Controlled by skills.deferred_discovery — independent from tool_search.enabled.
    from deerflow.skills.describe import build_skill_search_setup

    skill_search_enabled = resolved_app_config.skills.deferred_discovery
    container_base_path = resolved_app_config.skills.container_path

    if is_bootstrap:
        # Special bootstrap agent with minimal prompt for initial custom agent creation flow
        # Keep the bootstrap skill set intentionally narrow so agent creation
        # remains deterministic before the custom agent's own config exists.
        bootstrap_skills = [s for s in enabled_skills if s.name in _BOOTSTRAP_SKILL_NAMES]
        skill_setup = build_skill_search_setup(
            bootstrap_skills,
            enabled=skill_search_enabled,
            container_base_path=container_base_path,
        )
        raw_tools = get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled, app_config=resolved_app_config) + [setup_agent]
        configured_tools = raw_tools
        if non_interactive:
            configured_tools = [tool for tool in configured_tools if tool.name not in _NON_INTERACTIVE_DISABLED_TOOL_NAMES]
        authorization_candidates = [*configured_tools]
        if skill_setup.describe_skill_tool:
            authorization_candidates.append(skill_setup.describe_skill_tool)
        if should_use_memory_tools(resolved_app_config.memory):
            _append_memory_tools_without_name_conflicts(authorization_candidates)
        configured_tool_ids = {id(tool) for tool in configured_tools}
        authorized_tools, _authz_provider = apply_tool_authorization(
            authorization_candidates,
            context=cfg,
            app_config=resolved_app_config,
        )
        configured_tools = [tool for tool in authorized_tools if id(tool) in configured_tool_ids]
        late_tools = [tool for tool in authorized_tools if id(tool) not in configured_tool_ids]
        final_tools, setup = assemble_deferred_tools(configured_tools, enabled=resolved_app_config.tool_search.enabled)
        final_tools.extend(late_tools)
        mcp_routing_middleware = build_mcp_routing_middleware(
            final_tools,
            setup,
            top_k=resolved_app_config.tool_search.auto_promote_top_k,
        )
        middlewares = build_middlewares(
            config,
            model_name=model_name,
            agent_name=agent_name,
            available_skills=set(_BOOTSTRAP_SKILL_NAMES),
            app_config=resolved_app_config,
            deferred_setup=setup,
            mcp_routing_middleware=mcp_routing_middleware,
            user_id=resolved_user_id,
            authorization_provider=_authz_provider,
        )
        system_prompt = apply_prompt_template(
            subagent_enabled=subagent_enabled,
            max_concurrent_subagents=max_concurrent_subagents,
            max_total_subagents=max_total_subagents,
            available_skills=set(_BOOTSTRAP_SKILL_NAMES),
            app_config=resolved_app_config,
            deferred_names=setup.deferred_names,
            user_id=resolved_user_id,
            skill_names=skill_setup.skill_names or None,
            allowed_subagents=allowed_subagents,
        )
        graph = create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, app_config=resolved_app_config, attach_tracing=False),
            tools=final_tools,
            middleware=normalize_middleware_state_schemas(middlewares, mode),
            system_prompt=system_prompt,
            state_schema=get_thread_state_schema(mode),
        )
        return _complete_assembly(
            config=config,
            graph=graph,
            namespace="deerflow",
            agent_name="bootstrap",
            requested_model=requested_model_name or agent_model_name,
            effective_model=model_name,
            model_config=model_config,
            thinking_enabled=thinking_enabled,
            reasoning_effort=None,
            rendered_base_prompt=system_prompt,
            tools=final_tools,
            middlewares=middlewares,
            deferred_names=setup.deferred_names,
            enabled_skills=bootstrap_skills,
            effective_policies={
                "bootstrap": True,
                "non_interactive": non_interactive,
                "plan_mode": is_plan_mode,
                "subagents": _subagent_release_policy(
                    resolved_app_config,
                    enabled=subagent_enabled,
                    max_concurrent=max_concurrent_subagents,
                    max_total=max_total_subagents,
                ),
                "deferred_tools": {
                    "enabled": resolved_app_config.tool_search.enabled,
                    "catalog_hash": setup.catalog_hash,
                },
                "deferred_skills": skill_search_enabled,
            },
        )

    # Custom agents can update their own SOUL.md / config via update_agent.
    # The default agent (no agent_name) does not see this tool.
    # Build skill search setup from the agent-available skills. The same
    # allowlist is enforced by the runtime policy resolver, so describe_skill
    # cannot expose a skill this custom agent is not allowed to activate.
    skill_setup = build_skill_search_setup(
        enabled_skills,
        enabled=skill_search_enabled,
        container_base_path=container_base_path,
    )
    #
    # Withhold ``update_agent`` from runs triggered by webhook channels
    # (currently only ``github``). Webhook prompts come from arbitrary
    # external commenters — anyone who can post on a configured repo and
    # types ``@<bot>`` clears the trigger gate. Exposing the tool there
    # gives that commenter a path to mutate the agent's ``tool_groups``
    # / ``SOUL.md`` / ``model``, and the change persists for every
    # subsequent run. Self-mutation belongs in operator-trusted surfaces
    # (the chat UI, the HTTP API), not in webhook fan-out.
    #
    # The channel name is plumbed into ``run_context`` by
    # ``ChannelManager._resolve_run_params``; bootstrap and direct invocations
    # leave it unset, so ``update_agent`` remains available there.
    channel_name = cfg.get("channel_name")
    is_webhook_channel = channel_name in _WEBHOOK_CHANNELS
    extra_tools = [update_agent] if agent_name and not is_webhook_channel else []
    # Default lead agent (unchanged behavior)
    raw_tools = get_available_tools(model_name=model_name, groups=agent_config.tool_groups if agent_config else None, subagent_enabled=subagent_enabled, app_config=resolved_app_config)
    configured_tools = raw_tools + extra_tools
    if non_interactive:
        configured_tools = [tool for tool in configured_tools if tool.name not in _NON_INTERACTIVE_DISABLED_TOOL_NAMES]
    authorization_candidates = [*configured_tools]
    if skill_setup.describe_skill_tool:
        authorization_candidates.append(skill_setup.describe_skill_tool)
    if should_use_memory_tools(resolved_app_config.memory):
        _append_memory_tools_without_name_conflicts(authorization_candidates)
    configured_tool_ids = {id(tool) for tool in configured_tools}
    authorized_tools, _authz_provider = apply_tool_authorization(
        authorization_candidates,
        context=cfg,
        app_config=resolved_app_config,
    )
    configured_tools = [tool for tool in authorized_tools if id(tool) in configured_tool_ids]
    late_tools = [tool for tool in authorized_tools if id(tool) not in configured_tool_ids]
    final_tools, setup = assemble_deferred_tools(configured_tools, enabled=resolved_app_config.tool_search.enabled)
    final_tools.extend(late_tools)
    mcp_routing_middleware = build_mcp_routing_middleware(
        final_tools,
        setup,
        top_k=resolved_app_config.tool_search.auto_promote_top_k,
    )
    mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(authorized_tools, deferred_names=setup.deferred_names)
    middlewares = build_middlewares(
        config,
        model_name=model_name,
        agent_name=agent_name,
        available_skills=available_skills,
        app_config=resolved_app_config,
        deferred_setup=setup,
        mcp_routing_middleware=mcp_routing_middleware,
        user_id=resolved_user_id,
        authorization_provider=_authz_provider,
    )
    system_prompt = apply_prompt_template(
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
        max_total_subagents=max_total_subagents,
        agent_name=agent_name,
        available_skills=available_skills,
        app_config=resolved_app_config,
        deferred_names=setup.deferred_names,
        mcp_routing_hints_section=mcp_routing_hints_section,
        user_id=resolved_user_id,
        skill_names=skill_setup.skill_names or None,
        allowed_subagents=allowed_subagents,
    )
    graph = create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort, app_config=resolved_app_config, attach_tracing=False, model_overrides=agent_model_overrides),
        tools=final_tools,
        middleware=normalize_middleware_state_schemas(middlewares, mode),
        system_prompt=system_prompt,
        state_schema=get_thread_state_schema(mode),
    )
    return _complete_assembly(
        config=config,
        graph=graph,
        namespace="deerflow",
        agent_name=agent_name or "lead-agent",
        requested_model=requested_model_name or agent_model_name,
        effective_model=model_name,
        model_config=model_config,
        model_overrides=agent_model_overrides,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        rendered_base_prompt=system_prompt,
        tools=final_tools,
        middlewares=middlewares,
        deferred_names=setup.deferred_names,
        enabled_skills=enabled_skills,
        effective_policies={
            "bootstrap": False,
            "non_interactive": non_interactive,
            "plan_mode": is_plan_mode,
            "subagents": _subagent_release_policy(
                resolved_app_config,
                enabled=subagent_enabled,
                max_concurrent=max_concurrent_subagents,
                max_total=max_total_subagents,
            ),
            "deferred_tools": {
                "enabled": resolved_app_config.tool_search.enabled,
                "catalog_hash": setup.catalog_hash,
            },
            "deferred_skills": skill_search_enabled,
        },
    )
