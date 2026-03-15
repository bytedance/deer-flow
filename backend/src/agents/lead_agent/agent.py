import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig

from src.agents.lead_agent.prompt import _build_ptc_section, apply_prompt_template
from src.agents.middlewares.clarification_middleware import ClarificationMiddleware
from src.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from src.agents.middlewares.memory_middleware import MemoryMiddleware
from src.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from src.agents.middlewares.timeline_logging_middleware import TimelineLoggingMiddleware
from src.agents.middlewares.title_middleware import TitleMiddleware
from src.agents.middlewares.todo_middleware import TodoMiddleware
from src.agents.middlewares.tool_retry_middleware import ToolRetryMiddleware
from src.agents.middlewares.uploads_middleware import UploadsMiddleware
from src.agents.middlewares.usage_tracking_middleware import UsageTrackingMiddleware
from src.agents.middlewares.view_image_middleware import ViewImageMiddleware
from src.agents.thread_state import ThreadState
from src.config.app_config import get_app_config
from src.config.summarization_config import get_summarization_config
from src.models import create_chat_model
from src.sandbox.middleware import SandboxMiddleware

logger = logging.getLogger(__name__)


RUNTIME_MODEL_PROVIDERS = {
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "kimi",
    "zai",
    "minimax",
    "epfl-rcp",
}


def _runtime_model_spec_from_model_name(model_name: str | None) -> dict[str, str] | None:
    """Build a runtime model spec from provider-style model IDs.

    Supports IDs like:
    - provider:model_id
    - provider:model_id:tier
    - provider:model_id:tier:thinking_effort
    """
    if not isinstance(model_name, str):
        return None
    parts = [part.strip() for part in model_name.split(":", 3)]
    if len(parts) < 2:
        return None
    provider = parts[0].lower()
    model_id = parts[1]
    tier = parts[2] if len(parts) >= 3 else ""
    thinking_effort = parts[3] if len(parts) >= 4 else ""

    if provider not in RUNTIME_MODEL_PROVIDERS or not model_id:
        return None

    runtime_model: dict[str, str] = {
        "provider": provider,
        "model_id": model_id,
    }
    if tier and tier.lower() != "standard":
        runtime_model["tier"] = tier
    if thinking_effort:
        runtime_model["thinking_effort"] = thinking_effort
    return runtime_model


def _create_summarization_middleware() -> SummarizationMiddleware | None:
    """Create and configure the summarization middleware from config."""
    config = get_summarization_config()

    if not config.enabled:
        return None

    # Prepare trigger parameter
    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    # Prepare keep parameter
    keep = config.keep.to_tuple()

    # Prepare model parameter
    if config.model_name:
        model = config.model_name
    else:
        # Use a lightweight model for summarization to save costs
        # Falls back to default model if not explicitly specified
        model = create_chat_model(thinking_enabled=False)

    # Prepare kwargs
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize

    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    return SummarizationMiddleware(**kwargs)


def _create_todo_list_middleware(is_plan_mode: bool) -> TodoMiddleware | None:
    """Create and configure the TodoList middleware.

    Uses TodoMiddleware (extends TodoListMiddleware) which detects when
    SummarizationMiddleware truncates the write_todos tool call out of
    context and injects a reminder so the model retains awareness.

    Args:
        is_plan_mode: Whether to enable plan mode with TodoList middleware.

    Returns:
        TodoMiddleware instance if plan mode is enabled, None otherwise.
    """
    if not is_plan_mode:
        return None

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
# ToolSearchMiddleware gates which tools are visible to the LLM (after ToolRetry, before UsageTracking)
# SummarizationMiddleware should be early to reduce context before other processing
# TodoListMiddleware should be before ClarificationMiddleware to allow todo management
# TitleMiddleware generates title after first exchange
# MemoryMiddleware queues conversation for memory update (after TitleMiddleware)
# ViewImageMiddleware should be before ClarificationMiddleware to inject image details before LLM
# ClarificationMiddleware should be last to intercept clarification requests after model calls
def _build_middlewares(config: RunnableConfig, tool_search_ctx: dict | None = None):
    """Build middleware chain based on runtime configuration.

    Args:
        config: Runtime configuration containing configurable options like is_plan_mode.
        tool_search_ctx: Optional dict with 'catalog', 'tool_search_tool', and 'core_tool_names'
            for enabling tool search middleware.

    Returns:
        List of middleware instances.
    """
    middlewares = [
        ThreadDataMiddleware(),
        UploadsMiddleware(),
        SandboxMiddleware(),
        DanglingToolCallMiddleware(),
        ToolRetryMiddleware(),
    ]

    # Add tool search middleware if catalog has deferred tools
    if tool_search_ctx is not None:
        from src.agents.middlewares.tool_search_middleware import ToolSearchMiddleware

        catalog = tool_search_ctx["catalog"]
        if catalog.get_deferred_entries():
            middlewares.append(ToolSearchMiddleware(
                catalog=catalog,
                tool_search_tool=tool_search_ctx["tool_search_tool"],
                core_tool_names=tool_search_ctx["core_tool_names"],
            ))

    middlewares.append(UsageTrackingMiddleware())

    # Add summarization middleware if enabled
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # Add TodoList middleware if plan mode is enabled
    is_plan_mode = config.get("configurable", {}).get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # Add TitleMiddleware
    middlewares.append(TitleMiddleware())

    # Add MemoryMiddleware (after TitleMiddleware)
    middlewares.append(MemoryMiddleware())

    # Add ArtifactSyncMiddleware (enqueues S3 upload after agent execution)
    from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

    middlewares.append(ArtifactSyncMiddleware())

    # Add ViewImageMiddleware only if the current model supports vision
    configurable = config.get("configurable", {})
    model_name = configurable.get("model_name") or configurable.get("model")
    runtime_model = configurable.get("model_spec")
    app_config = get_app_config()
    # If no model_name specified, use the first model (default)
    if model_name is None and app_config.models:
        model_name = app_config.models[0].name

    model_config = app_config.get_model_config(model_name) if model_name else None
    supports_vision = None
    if isinstance(runtime_model, dict):
        supports_vision = runtime_model.get("supports_vision")
    if supports_vision is True:
        middlewares.append(ViewImageMiddleware())
    elif model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # Add SubagentLimitMiddleware to truncate excess parallel task calls
    subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
    if subagent_enabled:
        max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))

    # Log timeline snapshots after all message mutations (before ClarificationMiddleware)
    middlewares.append(TimelineLoggingMiddleware())

    # ClarificationMiddleware should always be last
    middlewares.append(ClarificationMiddleware())
    return middlewares


def make_lead_agent(config: RunnableConfig):
    # Lazy import to avoid circular dependency
    from src.tools import get_available_tools

    configurable = config.get("configurable", {})
    thinking_enabled = configurable.get("thinking_enabled", True)
    model_name = configurable.get("model_name") or configurable.get("model")
    runtime_model = configurable.get("model_spec")
    if runtime_model is None:
        runtime_model = _runtime_model_spec_from_model_name(model_name)
    # Inject user_id into runtime model spec so the factory can look up stored API keys
    if isinstance(runtime_model, dict) and "user_id" not in runtime_model:
        user_id = configurable.get("user_id")
        if user_id:
            runtime_model = {**runtime_model, "user_id": user_id}
    if isinstance(runtime_model, dict) and "thinking_effort" not in runtime_model:
        thinking_effort = configurable.get("thinking_effort")
        if isinstance(thinking_effort, str) and thinking_effort.strip():
            runtime_model = {**runtime_model, "thinking_effort": thinking_effort.strip().lower()}
    if isinstance(configurable, dict) and isinstance(runtime_model, dict):
        configurable["model_spec"] = runtime_model
    is_plan_mode = configurable.get("is_plan_mode", False)
    subagent_enabled = configurable.get("subagent_enabled", False)
    max_concurrent_subagents = configurable.get("max_concurrent_subagents", 3)
    logger.info("Agent config: thinking_enabled=%s, model_name=%s, is_plan_mode=%s, subagent_enabled=%s, max_concurrent_subagents=%s", thinking_enabled, model_name, is_plan_mode, subagent_enabled, max_concurrent_subagents)

    # Inject run metadata for LangSmith trace tagging
    if "metadata" not in config:
        config["metadata"] = {}
    config["metadata"].update(
        {
            "model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "is_plan_mode": is_plan_mode,
            "subagent_enabled": subagent_enabled,
        }
    )

    tools = get_available_tools(model_name=model_name, runtime_model=runtime_model, subagent_enabled=subagent_enabled)

    # Build tool search catalog for dynamic tool discovery
    tool_search_ctx = _build_tool_search_context(tools)

    # Compute tool usage policies based on available tools
    from src.tools.docs.tool_policies import get_tool_usage_policies

    tool_names = [getattr(t, "name", "") for t in tools]
    tool_policies = get_tool_usage_policies(tool_names)

    # Generate tool search prompt section if there are deferred tools
    tool_search_section = ""
    if tool_search_ctx is not None:
        tool_search_section = tool_search_ctx["catalog"].format_catalog_summary()

    # Generate PTC prompt section (empty if PTC disabled or no MCP tools)
    ptc_section = _build_ptc_section()

    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, runtime_model=runtime_model),
        tools=tools,
        middleware=_build_middlewares(config, tool_search_ctx=tool_search_ctx),
        system_prompt=apply_prompt_template(
            subagent_enabled=subagent_enabled,
            max_concurrent_subagents=max_concurrent_subagents,
            thinking_enabled=thinking_enabled,
            tool_policies=tool_policies,
            tool_search_section=tool_search_section,
            ptc_section=ptc_section,
        ),
        state_schema=ThreadState,
    )


def _build_tool_search_context(tools: list) -> dict | None:
    """Build tool search catalog and context for the middleware.

    Returns None if tool search is not needed (too few tools or no deferred tools).

    Args:
        tools: All available tools from get_available_tools().

    Returns:
        Dict with 'catalog', 'tool_search_tool', and 'core_tool_names', or None.
    """
    from src.tools.builtins.tool_search_tool import tool_search_tool
    from src.tools.catalog import ToolCatalog

    app_config = get_app_config()

    # Core tools: config-defined tools (sandbox, web, etc.) + built-in tools
    core_tool_names = {t.name for t in app_config.tools} | {
        "present_files", "ask_clarification", "reflection",
        "view_image", "task", "write_todos", "tool_search",
    }

    # Build MCP server mapping for catalog metadata
    mcp_server_map = _build_mcp_server_map(tools)

    # Build catalog from all tools
    catalog = ToolCatalog.from_tools(
        tools=tools,
        core_tool_names=core_tool_names,
        mcp_server_map=mcp_server_map,
    )

    # Only activate if there are deferred tools
    if not catalog.get_deferred_entries():
        return None

    # Add tool_search to the tool list so it gets registered in ToolNode
    tools.append(tool_search_tool)

    logger.info(
        "Tool search enabled: %d total tools, %d core, %d deferred",
        len(catalog.entries),
        len([e for e in catalog.entries.values() if e.is_core]),
        len(catalog.get_deferred_entries()),
    )

    return {
        "catalog": catalog,
        "tool_search_tool": tool_search_tool,
        "core_tool_names": core_tool_names,
    }


def _build_mcp_server_map(tools: list) -> dict[str, str]:
    """Build a mapping from tool name to MCP server name.

    MCP adapter tools may have metadata about their origin server.
    """
    from langchain_core.tools import BaseTool

    server_map: dict[str, str] = {}
    for tool in tools:
        if not isinstance(tool, BaseTool):
            continue
        # langchain-mcp-adapters may store server info in metadata
        metadata = getattr(tool, "metadata", None)
        if isinstance(metadata, dict):
            server_name = metadata.get("mcp_server_name")
            if server_name:
                server_map[tool.name] = server_name
    return server_map
