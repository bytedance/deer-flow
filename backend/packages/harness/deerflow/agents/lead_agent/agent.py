import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.agents_config import load_agent_config
from deerflow.config.app_config import get_app_config
from deerflow.config.summarization_config import get_summarization_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


def _resolve_model_name(requested_model_name: str | None = None) -> str:
    """Resolve a runtime 模型 名称 safely, falling back to 默认 if 无效. Returns None if no models are configured."""
    app_config = get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(f"Model '{requested_model_name}' not found in config; fallback to default model '{default_model_name}'.")
    return default_model_name


def _create_summarization_middleware() -> SummarizationMiddleware | None:
    """Create and configure the summarization 中间件 from 配置."""
    config = get_summarization_config()

    if not config.enabled:
        return None

    #    Prepare trigger 参数


    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    #    Prepare keep 参数


    keep = config.keep.to_tuple()

    #    Prepare 模型 参数


    if config.model_name:
        model = config.model_name
    else:
        #    Use a lightweight 模型 对于 summarization to 保存 costs


        #    Falls back to 默认 模型 如果 not explicitly specified


        model = create_chat_model(thinking_enabled=False)

    #    Prepare kwargs


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
    """Create and configure the TodoList 中间件.

    Args:
        is_plan_mode: Whether to enable plan mode with TodoList 中间件.

    Returns:
        TodoMiddleware instance if plan mode is 已启用, None otherwise.
    """
    if not is_plan_mode:
        return None

    #    Custom prompts matching DeerFlow's style


    system_prompt = """
<todo_list_system>
You have access to the `write_todos` 工具 to help you manage and track 复杂 multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can 运行 in 并行)
- Update the 待办 列表 in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this 工具 for 简单 tasks (< 3 steps) - just complete them directly

**When to Use:**
This 工具 is designed for 复杂 objectives that require systematic tracking:
- Complex multi-step tasks requiring 3+ distinct steps
- Non-trivial tasks needing careful planning and execution
- 用户 explicitly requests a 待办 列表
- 用户 provides multiple tasks (numbered or comma-separated 列表)
- The plan may need revisions based on intermediate results

**When NOT to Use:**
- Single, straightforward tasks
- Trivial tasks (< 3 steps)
- Purely conversational or informational requests
- Simple 工具 calls where the approach is obvious

**Best Practices:**
- Break 下 复杂 tasks into smaller, actionable steps
- Use clear, descriptive task names
- Remove tasks that become irrelevant
- Add 新建 tasks discovered during implementation
- Don't be afraid to revise the 待办 列表 as you learn more

**Task Management:**
Writing todos takes time and tokens - use it when helpful for managing 复杂 problems, not for 简单 requests.
</todo_list_system>
"""

    tool_description = """Use this 工具 to 创建 and manage a structured task 列表 for 复杂 work sessions.

**IMPORTANT: Only use this 工具 for 复杂 tasks (3+ steps). For 简单 requests, just do the work directly.**

#   # When to Use



Use this 工具 in these scenarios:
1. **Complex multi-step tasks**: When a task requires 3 or more distinct steps or actions
2. **Non-trivial tasks**: Tasks requiring careful planning or multiple operations
3. **用户 explicitly requests 待办 列表**: When the 用户 directly asks you to track tasks
4. **Multiple tasks**: When users provide a 列表 of things to be done
5. **Dynamic planning**: When the plan may need updates based on intermediate results

#   # When NOT to Use



Skip this 工具 when:
1. The task is straightforward and takes less than 3 steps
2. The task is trivial and tracking provides no benefit
3. The task is purely conversational or informational
4. It's clear what needs to be done and you can just do it

#   # How to Use



1. **Starting a task**: Mark it as `in_progress` BEFORE beginning work
2. **Completing a task**: Mark it as `completed` IMMEDIATELY after finishing
3. **Updating the 列表**: Add 新建 tasks, remove irrelevant ones, or 更新 descriptions as needed
4. **Multiple updates**: You can make several updates at once (e.g., complete one task and 开始 the 下一个)

#   # Task States



- `待处理`: Task not yet started
- `in_progress`: Currently working on (can have multiple if tasks 运行 in 并行)
- `completed`: Task finished successfully

#   # Task Completion Requirements



**CRITICAL: Only mark a task as completed when you have FULLY accomplished it.**

Never mark a task as completed if:
- There are unresolved issues or errors
- Work is partial or incomplete
- You encountered blockers preventing completion
- You couldn't find necessary resources or dependencies
- Quality standards haven't been met

If blocked, keep the task as `in_progress` and 创建 a 新建 task describing what needs to be resolved.

#   # Best Practices



- Create specific, actionable items
- Break 复杂 tasks into smaller, manageable steps
- Use clear, descriptive task names
- Update task status in real-time as you work
- Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
- Remove tasks that are no longer relevant
- **IMPORTANT**: When you write the 待办 列表, mark your 第一 task(s) as `in_progress` immediately
- **IMPORTANT**: Unless all tasks are completed, always have at least one task `in_progress` to show progress

Being proactive with task management demonstrates thoroughness and ensures all requirements are completed successfully.

**Remember**: If you only need a few 工具 calls to complete a task and it's clear what to do, it's better to just do the task directly and NOT use this 工具 at all.
"""

    return TodoMiddleware(system_prompt=system_prompt, tool_description=tool_description)


#    ThreadDataMiddleware must be before SandboxMiddleware to ensure thread_id is 可用的


#    UploadsMiddleware should be after ThreadDataMiddleware to access thread_id


#    DanglingToolCallMiddleware patches missing ToolMessages before 模型 sees the history


#    SummarizationMiddleware should be early to reduce context before other processing


#    TodoListMiddleware should be before ClarificationMiddleware to allow 待办 management


#    TitleMiddleware generates title after 第一 exchange


#    MemoryMiddleware queues conversation 对于 内存 更新 (after TitleMiddleware)


#    ViewImageMiddleware should be before ClarificationMiddleware to inject image details before LLM


#    ToolErrorHandlingMiddleware should be before ClarificationMiddleware to convert 工具 exceptions to ToolMessages


#    ClarificationMiddleware should be 最后 to intercept clarification requests after 模型 calls


def _build_middlewares(config: RunnableConfig, model_name: str | None, agent_name: str | None = None):
    """Build 中间件 chain based on runtime configuration.

    Args:
        配置: Runtime configuration containing configurable options like is_plan_mode.
        agent_name: If provided, MemoryMiddleware will use per-代理 内存 storage.

    Returns:
        List of 中间件 instances.
    """
    middlewares = build_lead_runtime_middlewares(lazy_init=True)

    #    Add summarization 中间件 如果 已启用


    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    #    Add TodoList 中间件 如果 plan mode is 已启用


    is_plan_mode = config.get("configurable", {}).get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    #    Add TitleMiddleware


    middlewares.append(TitleMiddleware())

    #    Add MemoryMiddleware (after TitleMiddleware)


    middlewares.append(MemoryMiddleware(agent_name=agent_name))

    #    Add ViewImageMiddleware only 如果 the 当前 模型 supports vision.


    #    Use the resolved runtime model_name from make_lead_agent to avoid stale 配置 values.


    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    #    Add DeferredToolFilterMiddleware to hide deferred 工具 schemas from 模型 binding


    if app_config.tool_search.enabled:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
        middlewares.append(DeferredToolFilterMiddleware())

    #    Add SubagentLimitMiddleware to truncate excess 并行 task calls


    subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
    if subagent_enabled:
        max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))

    #    LoopDetectionMiddleware — detect and 中断 repetitive 工具 call loops


    middlewares.append(LoopDetectionMiddleware())

    #    ClarificationMiddleware should always be 最后


    middlewares.append(ClarificationMiddleware())
    return middlewares


def make_lead_agent(config: RunnableConfig):
    #    Lazy import to avoid circular dependency


    from deerflow.tools import get_available_tools
    from deerflow.tools.builtins import setup_agent

    cfg = config.get("configurable", {})

    thinking_enabled = cfg.get("thinking_enabled", True)
    reasoning_effort = cfg.get("reasoning_effort", None)
    requested_model_name: str | None = cfg.get("model_name") or cfg.get("model")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    is_bootstrap = cfg.get("is_bootstrap", False)
    agent_name = cfg.get("agent_name")

    agent_config = load_agent_config(agent_name) if not is_bootstrap else None
    #    Custom 代理 模型 or 回退 to global/默认 模型 resolution


    agent_model_name = agent_config.model if agent_config and agent_config.model else _resolve_model_name()

    #    Final 模型 名称 resolution with 请求 override, then 代理 配置, then global 默认


    model_name = requested_model_name or agent_model_name

    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None

    if model_config is None:
        raise ValueError("No chat model could be resolved. Please configure at least one model in config.yaml or provide a valid 'model_name'/'model' in the request.")
    if thinking_enabled and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False

    logger.info(
        "Create Agent(%s) -> thinking_enabled: %s, reasoning_effort: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s",
        agent_name or "default",
        thinking_enabled,
        reasoning_effort,
        model_name,
        is_plan_mode,
        subagent_enabled,
        max_concurrent_subagents,
    )

    #    Inject 运行 metadata 对于 LangSmith trace tagging


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
        }
    )

    if is_bootstrap:
        #    Special bootstrap 代理 with minimal 提示词 对于 initial custom 代理 creation flow


        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name),
            system_prompt=apply_prompt_template(subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, available_skills=set(["bootstrap"])),
            state_schema=ThreadState,
        )

    #    Default lead 代理 (unchanged behavior)


    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort),
        tools=get_available_tools(model_name=model_name, groups=agent_config.tool_groups if agent_config else None, subagent_enabled=subagent_enabled),
        middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name),
        system_prompt=apply_prompt_template(subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, agent_name=agent_name),
        state_schema=ThreadState,
    )
