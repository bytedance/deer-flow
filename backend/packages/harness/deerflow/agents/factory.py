"""Configuration-free factory for DeerFlow agents.

``create_deep_agent`` accepts plain Python arguments — no YAML files, no
global singletons.  It is the SDK-level entry point sitting between the raw
``langchain.agents.create_agent`` primitive and the config-driven
``make_lead_agent`` application factory.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.features import AgentFeatures, SubagentOptions, SummarizationOptions
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins import ask_clarification_tool

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware priority constants (lower = runs earlier)
# ---------------------------------------------------------------------------
_ORDER_THREAD_DATA = 100
_ORDER_UPLOADS = 200
_ORDER_SANDBOX = 300
_ORDER_DANGLING_TOOL_CALL = 400
_ORDER_TOOL_ERROR = 500
_ORDER_SUMMARIZATION = 600
_ORDER_TODO_LIST = 700
_ORDER_TITLE = 800
_ORDER_MEMORY = 900
_ORDER_VIEW_IMAGE = 1000
_ORDER_SUBAGENT_LIMIT = 1100
_ORDER_LOOP_DETECTION = 1200
_ORDER_EXTRA_BASE = 8000
_ORDER_CLARIFICATION = 9999


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_deep_agent(
    model: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] | None = None,
    features: AgentFeatures | None = None,
    state_schema: type | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    name: str = "default",
) -> CompiledStateGraph:
    """Create a DeerFlow agent.  Pure arguments — no config files read.

    Parameters
    ----------
    model:
        Chat model instance.
    tools:
        User-provided tools.  Feature-injected tools are appended automatically.
    system_prompt:
        System message.  ``None`` uses a minimal default.
    middleware:
        **Full takeover** — if provided, this exact list is used.
        Cannot be combined with *features*.
    features:
        Declarative feature flags.  Ignored when *middleware* is given.
    state_schema:
        LangGraph state type.  Defaults to ``ThreadState``.
    checkpointer:
        Optional persistence backend.
    name:
        Agent name (passed to middleware that cares, e.g. ``MemoryMiddleware``).

    Raises
    ------
    ValueError
        If both *middleware* and *features* are provided.
    """
    if middleware is not None and features is not None:
        raise ValueError("Cannot specify both 'middleware' and 'features'.  Use one or the other.")

    effective_tools: list[BaseTool] = list(tools or [])
    effective_state = state_schema or ThreadState

    if middleware is not None:
        effective_middleware = list(middleware)
    else:
        feat = features or AgentFeatures()
        effective_middleware, extra_tools = _assemble_from_features(feat, name=name)
        # Deduplicate by tool name — user-provided tools take priority.
        existing_names = {t.name for t in effective_tools}
        for t in extra_tools:
            if t.name not in existing_names:
                effective_tools.append(t)
                existing_names.add(t.name)

    return create_agent(
        model=model,
        tools=effective_tools or None,
        middleware=effective_middleware,
        system_prompt=system_prompt,
        state_schema=effective_state,
        checkpointer=checkpointer,
        name=name,
    )


# ---------------------------------------------------------------------------
# Internal: feature-driven middleware assembly
# ---------------------------------------------------------------------------

# Minimal TodoMiddleware prompts for SDK users.  The config-driven path
# (lead_agent/agent.py) carries a more detailed version with full usage
# guidelines.  Phase 2 will extract both into a shared module.
_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly
</todo_list_system>
"""

_TODO_TOOL_DESCRIPTION = (
    "Use this tool to create and manage a structured task list for complex work sessions.  "
    "Only use for complex tasks (3+ steps)."
)


def _assemble_from_features(
    feat: AgentFeatures,
    *,
    name: str = "default",
) -> tuple[list[AgentMiddleware], list[BaseTool]]:
    """Build an ordered middleware chain + extra tools from *feat*."""
    pending: list[tuple[int, AgentMiddleware]] = []
    extra_tools: list[BaseTool] = []

    # --- Sandbox infrastructure ---
    if feat.sandbox:
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
        from deerflow.sandbox.middleware import SandboxMiddleware

        pending.append((_ORDER_THREAD_DATA, ThreadDataMiddleware(lazy_init=True)))
        pending.append((_ORDER_UPLOADS, UploadsMiddleware()))
        pending.append((_ORDER_SANDBOX, SandboxMiddleware(lazy_init=True)))

    # --- Always-on error handling ---
    pending.append((_ORDER_DANGLING_TOOL_CALL, DanglingToolCallMiddleware()))
    pending.append((_ORDER_TOOL_ERROR, ToolErrorHandlingMiddleware()))

    # --- Summarization ---
    if feat.summarization is not False:
        from langchain.agents.middleware import SummarizationMiddleware

        kwargs: dict = {}
        if isinstance(feat.summarization, SummarizationOptions):
            if feat.summarization.model is not None:
                kwargs["model"] = feat.summarization.model
            if feat.summarization.trigger is not None:
                kwargs["trigger"] = feat.summarization.trigger
            if feat.summarization.keep is not None:
                kwargs["keep"] = feat.summarization.keep
        pending.append((_ORDER_SUMMARIZATION, SummarizationMiddleware(**kwargs)))

    # --- Plan Mode (TodoList) ---
    if feat.plan_mode:
        from deerflow.agents.middlewares.todo_middleware import TodoMiddleware

        pending.append((_ORDER_TODO_LIST, TodoMiddleware(system_prompt=_TODO_SYSTEM_PROMPT, tool_description=_TODO_TOOL_DESCRIPTION)))

    # --- Auto Title ---
    if feat.auto_title:
        from deerflow.agents.middlewares.title_middleware import TitleMiddleware

        pending.append((_ORDER_TITLE, TitleMiddleware()))

    # --- Memory ---
    if feat.memory is not False:
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

        pending.append((_ORDER_MEMORY, MemoryMiddleware(agent_name=name)))

    # --- Vision ---
    if feat.vision:
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
        from deerflow.tools.builtins import view_image_tool

        pending.append((_ORDER_VIEW_IMAGE, ViewImageMiddleware()))
        extra_tools.append(view_image_tool)

    # --- Subagent ---
    if feat.subagent is not False:
        from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
        from deerflow.tools.builtins import task_tool

        opts_sub = feat.subagent if isinstance(feat.subagent, SubagentOptions) else SubagentOptions()
        pending.append((_ORDER_SUBAGENT_LIMIT, SubagentLimitMiddleware(max_concurrent=opts_sub.max_concurrent)))
        extra_tools.append(task_tool)

    # --- Loop Detection ---
    if feat.loop_detection:
        from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

        pending.append((_ORDER_LOOP_DETECTION, LoopDetectionMiddleware()))

    # --- Extra user-provided middleware ---
    for i, mw in enumerate(feat.extra_middleware):
        pending.append((_ORDER_EXTRA_BASE + i, mw))

    # --- Clarification (always last) ---
    pending.append((_ORDER_CLARIFICATION, ClarificationMiddleware()))
    extra_tools.append(ask_clarification_tool)

    # Sort by priority and return.
    pending.sort(key=lambda pair: pair[0])
    return [mw for _, mw in pending], extra_tools
