"""Pure-argument factory for DeerFlow agents.

``create_deerflow_agent`` accepts plain Python arguments — it does not load
YAML or install process-global runtime dependencies. It is the SDK-level entry
point sitting between the raw
``langchain.agents.create_agent`` primitive and the config-driven
``make_lead_agent`` application factory.

Direct callers that need an isolated native-subagent capacity or a durable
batch worker pass a caller-owned ``SubagentRuntime`` explicitly. When omitted,
subagent tools retain their application-compatible process-global fallback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.features import RuntimeFeatures
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.thread_state import adapt_state_schema_for_mode, get_thread_state_schema, normalize_middleware_state_schemas
from deerflow.config.database_config import CheckpointChannelMode
from deerflow.tools.builtins import ask_clarification_tool

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

    from deerflow.config.memory_config import MemoryConfig
    from deerflow.subagents.runtime import SubagentRuntime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TodoMiddleware prompts (minimal SDK version)
# ---------------------------------------------------------------------------

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

_TODO_TOOL_DESCRIPTION = "Use this tool to create and manage a structured task list for complex work sessions.  Only use for complex tasks (3+ steps)."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_deerflow_agent(
    model: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] | None = None,
    features: RuntimeFeatures | None = None,
    extra_middleware: list[AgentMiddleware] | None = None,
    plan_mode: bool = False,
    state_schema: type | None = None,
    checkpoint_channel_mode: CheckpointChannelMode = "full",
    checkpoint_snapshot_frequency: int | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    name: str = "default",
    subagent_runtime: SubagentRuntime | None = None,
) -> CompiledStateGraph:
    """Create a DeerFlow agent from plain Python arguments.

    The factory assembly itself reads no config files. Pass ``subagent_runtime``
    when direct SDK-created graphs must share an explicit native-subagent
    capacity or caller-managed durable batch worker.

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
        Cannot be combined with *features* or *extra_middleware*.
    features:
        Declarative feature flags.  Cannot be combined with *middleware*.
    extra_middleware:
        Additional middlewares inserted into the auto-assembled chain via
        ``@Next``/``@Prev`` positioning.  Cannot be used with *middleware*.
    plan_mode:
        Enable TodoMiddleware for task tracking.
    state_schema:
        LangGraph state type.  Defaults to ``ThreadState``.
    checkpoint_channel_mode:
        Checkpoint representation for accumulating channels.  Defaults to the
        full-state compatibility schema.  ``"delta"`` requires the guarded
        persistence paths (mode markers + compatibility gate) and is therefore
        rejected when combined with *checkpointer* in this factory; without a
        checkpointer the graph is ephemeral and delta is allowed.
    checkpoint_snapshot_frequency:
        DeltaChannel snapshot cadence for ``"delta"`` mode.  ``None`` uses the
        process-frozen value, falling back to the config default.  Ignored in
        ``"full"`` mode.
    checkpointer:
        Optional persistence backend.
    name:
        Agent name (passed to middleware that cares, e.g. ``MemoryMiddleware``).
    subagent_runtime:
        Explicit process runtime shared by direct SDK-created graphs. Required
        only when the caller needs non-default native-subagent capacity or a
        caller-managed durable batch worker without Gateway/DeerFlowClient
        startup. Requires ``features.subagent`` to be enabled.

    Raises
    ------
    ValueError
        If both *middleware* and *features*/*extra_middleware* are provided.
    """
    if middleware is not None and features is not None:
        raise ValueError("Cannot specify both 'middleware' and 'features'.  Use one or the other.")
    if checkpoint_channel_mode == "delta" and checkpointer is not None:
        raise ValueError(
            "create_deerflow_agent does not support checkpoint_channel_mode='delta' with a checkpointer: "
            "persisted graphs built here bypass checkpoint mode marker injection and the fail-closed "
            "compatibility gate (see deerflow.runtime.checkpoint_mode), so a mixed-mode store would "
            "silently corrupt thread state.  Use the guarded application paths (make_lead_agent or "
            "DeerFlowClient) for delta persistence; delta without a checkpointer is ephemeral and allowed."
        )
    if middleware is not None and extra_middleware:
        raise ValueError("Cannot use 'extra_middleware' with 'middleware' (full takeover).")
    if subagent_runtime is not None and (middleware is not None or features is None or features.subagent is False):
        raise ValueError("subagent_runtime requires features.subagent to be enabled; it cannot be used with middleware full takeover")
    if subagent_runtime is not None and subagent_runtime.batch_config is not None and subagent_runtime.batch_submitter is None:
        raise RuntimeError("The explicit durable batch worker is not running; await subagent_runtime.start() or enter it with 'async with' before calling create_deerflow_agent")
    if extra_middleware:
        for mw in extra_middleware:
            if not isinstance(mw, AgentMiddleware):
                raise TypeError(f"extra_middleware items must be AgentMiddleware instances, got {type(mw).__name__}")

    effective_tools: list[BaseTool] = list(tools or [])
    effective_state = get_thread_state_schema(checkpoint_channel_mode, checkpoint_snapshot_frequency) if state_schema is None else adapt_state_schema_for_mode(state_schema, checkpoint_channel_mode, checkpoint_snapshot_frequency)

    if middleware is not None:
        effective_middleware = list(middleware)
    else:
        feat = features or RuntimeFeatures()
        effective_middleware, extra_tools = _assemble_from_features(
            feat,
            name=name,
            plan_mode=plan_mode,
            extra_middleware=extra_middleware or [],
            subagent_runtime=subagent_runtime,
        )
        # Deduplicate by tool name — user-provided tools take priority.
        existing_names = {t.name for t in effective_tools}
        for t in extra_tools:
            if t.name not in existing_names:
                effective_tools.append(t)
                existing_names.add(t.name)

    effective_middleware = normalize_middleware_state_schemas(
        effective_middleware,
        checkpoint_channel_mode,
        checkpoint_snapshot_frequency,
    )

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


def _assemble_from_features(
    feat: RuntimeFeatures,
    *,
    name: str = "default",
    plan_mode: bool = False,
    extra_middleware: list[AgentMiddleware] | None = None,
    subagent_runtime: SubagentRuntime | None = None,
) -> tuple[list[AgentMiddleware], list[BaseTool]]:
    """Build an ordered middleware chain + extra tools from *feat*.

    Middleware order matches ``make_lead_agent`` (14 middlewares):

      0-2. Sandbox infrastructure (ThreadData → Uploads → Sandbox)
      3.   DanglingToolCallMiddleware (always)
      4.   GuardrailMiddleware (guardrail feature)
      5.   ToolErrorHandlingMiddleware (always)
      6.   SummarizationMiddleware (summarization feature)
      7.   TodoMiddleware (plan_mode parameter)
      8.   TitleMiddleware (auto_title feature)
      9.   MemoryMiddleware (memory feature)
      10.  ViewImageMiddleware (vision feature)
      11.  SubagentLimitMiddleware (subagent feature)
      12.  LoopDetectionMiddleware (loop_detection feature)
      13.  ClarificationMiddleware (always last)

    Two-phase ordering:
      1. Built-in chain — fixed sequential append.
      2. Extra middleware — inserted via @Next/@Prev.

    Each feature value is handled as:
      - ``False``: skip
      - ``True``: create the built-in default middleware (not available for
        ``summarization`` and ``guardrail`` — these require a custom instance)
      - ``AgentMiddleware`` instance: use directly (custom replacement)
    """
    chain: list[AgentMiddleware] = []
    extra_tools: list[BaseTool] = []

    # --- [0-2] Sandbox infrastructure ---
    if feat.sandbox is not False:
        if isinstance(feat.sandbox, AgentMiddleware):
            chain.append(feat.sandbox)
        else:
            from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
            from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
            from deerflow.sandbox.middleware import SandboxMiddleware

            chain.append(ThreadDataMiddleware(lazy_init=True))
            chain.append(UploadsMiddleware())
            chain.append(SandboxMiddleware(lazy_init=True))

    # --- [3] DanglingToolCall (always) ---
    chain.append(DanglingToolCallMiddleware())

    # --- [4] Guardrail ---
    if feat.guardrail is not False:
        if isinstance(feat.guardrail, AgentMiddleware):
            chain.append(feat.guardrail)
        else:
            raise ValueError("guardrail=True requires a custom AgentMiddleware instance (no built-in GuardrailMiddleware yet)")

    # --- [5] ToolErrorHandling (always) ---
    chain.append(ToolErrorHandlingMiddleware())

    # --- [6] Summarization ---
    if feat.summarization is not False:
        if isinstance(feat.summarization, AgentMiddleware):
            chain.append(feat.summarization)
        else:
            raise ValueError("summarization=True requires a custom AgentMiddleware instance (SummarizationMiddleware needs a model argument)")

    # --- [7] TodoMiddleware (plan_mode) ---
    if plan_mode:
        from deerflow.agents.middlewares.todo_middleware import TodoMiddleware

        chain.append(TodoMiddleware(system_prompt=_TODO_SYSTEM_PROMPT, tool_description=_TODO_TOOL_DESCRIPTION))

    # --- [8] Auto Title ---
    if feat.auto_title is not False:
        if isinstance(feat.auto_title, AgentMiddleware):
            chain.append(feat.auto_title)
        else:
            from deerflow.agents.middlewares.title_middleware import TitleMiddleware

            chain.append(TitleMiddleware())

    # --- [9] Memory ---
    if feat.memory is not False:
        if isinstance(feat.memory, AgentMiddleware):
            chain.append(feat.memory)
        else:
            from deerflow.config.memory_config import get_memory_config, should_use_memory_tools

            memory_cfg: MemoryConfig = feat.memory_config or get_memory_config()
            if should_use_memory_tools(memory_cfg):
                from deerflow.agents.memory.manager import backend_requires_passive_writes_in_tool_mode
                from deerflow.agents.memory.tools import get_memory_tools

                existing_names = {tool.name for tool in extra_tools}
                for memory_tool in get_memory_tools():
                    if memory_tool.name in existing_names:
                        logger.warning("Memory tool name %r already exists and was skipped.", memory_tool.name)
                        continue
                    extra_tools.append(memory_tool)
                    existing_names.add(memory_tool.name)
                if backend_requires_passive_writes_in_tool_mode(memory_cfg.manager_class):
                    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

                    chain.append(MemoryMiddleware(agent_name=name, memory_config=memory_cfg))
            else:
                if memory_cfg.mode == "tool" and not memory_cfg.enabled:
                    logger.warning("memory.mode is 'tool' but memory.enabled is false; memory tools will not be registered.")
                from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

                chain.append(MemoryMiddleware(agent_name=name, memory_config=memory_cfg))

    # --- [10] Vision ---
    if feat.vision is not False:
        if isinstance(feat.vision, AgentMiddleware):
            chain.append(feat.vision)
        else:
            from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

            chain.append(ViewImageMiddleware())

        if feat.sandbox is not False:
            from deerflow.tools.builtins import view_image_tool

            extra_tools.append(view_image_tool)

    # --- [11] Subagent ---
    if feat.subagent is not False:
        if isinstance(feat.subagent, AgentMiddleware):
            chain.append(feat.subagent)
        else:
            from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
            from deerflow.config.subagents_config import DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
            from deerflow.subagents.capacity import configured_subagent_max_running

            max_concurrent = subagent_runtime.config.max_running if subagent_runtime is not None else configured_subagent_max_running()
            max_total = subagent_runtime.max_total_per_run if subagent_runtime is not None else DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
            chain.append(
                SubagentLimitMiddleware(
                    max_concurrent=max_concurrent,
                    max_total=max_total,
                )
            )
        from deerflow.tools.builtins import task_tool

        if subagent_runtime is None:
            extra_tools.append(task_tool)
        else:
            from deerflow.tools.builtins.task_tool import bind_task_tool

            extra_tools.append(
                bind_task_tool(
                    subagent_runtime.execution_capacity,
                    app_config=subagent_runtime.app_config,
                )
            )

        if subagent_runtime is not None and subagent_runtime.batch_submitter is not None:
            from deerflow.tools.builtins.batch_task_tool import bind_batch_tools

            extra_tools.extend(
                bind_batch_tools(
                    submitter_provider=lambda: subagent_runtime.batch_submitter,
                    app_config=subagent_runtime.app_config,
                )
            )
        elif subagent_runtime is None:
            from deerflow.subagents.batch_runtime import is_subagent_batch_runtime_available

            if is_subagent_batch_runtime_available():
                from deerflow.tools.builtins import batch_status, batch_task, cancel_batch

                extra_tools.extend((batch_task, batch_status, cancel_batch))

    # --- [12] LoopDetection ---
    if feat.loop_detection is not False:
        if isinstance(feat.loop_detection, AgentMiddleware):
            chain.append(feat.loop_detection)
        else:
            from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
            from deerflow.config.loop_detection_config import LoopDetectionConfig

            chain.append(LoopDetectionMiddleware.from_config(LoopDetectionConfig()))

    # --- [13] TokenBudget ---
    if feat.token_budget is not False:
        if isinstance(feat.token_budget, AgentMiddleware):
            chain.append(feat.token_budget)
        else:
            from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
            from deerflow.config.token_budget_config import TokenBudgetConfig

            chain.append(TokenBudgetMiddleware.from_config(TokenBudgetConfig()))

    # --- [14] Clarification (always last among built-ins) ---
    chain.append(ClarificationMiddleware())
    extra_tools.append(ask_clarification_tool)

    # --- Insert extra_middleware via @Next/@Prev ---
    if extra_middleware:
        _insert_extra(chain, extra_middleware)
        # Invariant: ClarificationMiddleware must always be last.
        # @Next(ClarificationMiddleware) could push it off the tail.
        clar_idx = next(i for i, m in enumerate(chain) if isinstance(m, ClarificationMiddleware))
        if clar_idx != len(chain) - 1:
            chain.append(chain.pop(clar_idx))

    return chain, extra_tools


# ---------------------------------------------------------------------------
# Internal: extra middleware insertion with @Next/@Prev
# ---------------------------------------------------------------------------


def _insert_extra(chain: list[AgentMiddleware], extras: list[AgentMiddleware]) -> None:
    """Insert extra middlewares into *chain* using ``@Next``/``@Prev`` anchors.

    Algorithm:
      1. Validate: no middleware has both @Next and @Prev.
      2. Conflict detection: two extras targeting same anchor (same or opposite direction) → error.
      3. Insert unanchored extras before ClarificationMiddleware.
      4. Insert anchored extras iteratively (supports cross-external anchoring).
      5. If an anchor cannot be resolved after all rounds → error.
    """
    next_targets: dict[type, type] = {}
    prev_targets: dict[type, type] = {}

    anchored: list[tuple[AgentMiddleware, str, type]] = []
    unanchored: list[AgentMiddleware] = []

    for mw in extras:
        next_anchor = getattr(type(mw), "_next_anchor", None)
        prev_anchor = getattr(type(mw), "_prev_anchor", None)

        if next_anchor and prev_anchor:
            raise ValueError(f"{type(mw).__name__} cannot have both @Next and @Prev")

        if next_anchor:
            if next_anchor in next_targets:
                raise ValueError(f"Conflict: {type(mw).__name__} and {next_targets[next_anchor].__name__} both @Next({next_anchor.__name__})")
            if next_anchor in prev_targets:
                raise ValueError(f"Conflict: {type(mw).__name__} @Next({next_anchor.__name__}) and {prev_targets[next_anchor].__name__} @Prev({next_anchor.__name__}) — use cross-anchoring between extras instead")
            next_targets[next_anchor] = type(mw)
            anchored.append((mw, "next", next_anchor))
        elif prev_anchor:
            if prev_anchor in prev_targets:
                raise ValueError(f"Conflict: {type(mw).__name__} and {prev_targets[prev_anchor].__name__} both @Prev({prev_anchor.__name__})")
            if prev_anchor in next_targets:
                raise ValueError(f"Conflict: {type(mw).__name__} @Prev({prev_anchor.__name__}) and {next_targets[prev_anchor].__name__} @Next({prev_anchor.__name__}) — use cross-anchoring between extras instead")
            prev_targets[prev_anchor] = type(mw)
            anchored.append((mw, "prev", prev_anchor))
        else:
            unanchored.append(mw)

    # Unanchored → before ClarificationMiddleware
    clarification_idx = next(i for i, m in enumerate(chain) if isinstance(m, ClarificationMiddleware))
    for mw in unanchored:
        chain.insert(clarification_idx, mw)
        clarification_idx += 1

    # Anchored → iterative insertion (supports external-to-external anchoring)
    pending = list(anchored)
    max_rounds = len(pending) + 1
    for _ in range(max_rounds):
        if not pending:
            break
        remaining = []
        for mw, direction, anchor in pending:
            idx = next(
                (i for i, m in enumerate(chain) if isinstance(m, anchor)),
                None,
            )
            if idx is None:
                remaining.append((mw, direction, anchor))
                continue
            if direction == "next":
                chain.insert(idx + 1, mw)
            else:
                chain.insert(idx, mw)
        if len(remaining) == len(pending):
            names = [type(m).__name__ for m, _, _ in remaining]
            anchor_types = {a for _, _, a in remaining}
            remaining_types = {type(m) for m, _, _ in remaining}
            circular = anchor_types & remaining_types
            if circular:
                raise ValueError(f"Circular dependency among extra middlewares: {', '.join(t.__name__ for t in circular)}")
            raise ValueError(f"Cannot resolve positions for {', '.join(names)} — anchors {', '.join(a.__name__ for _, _, a in remaining)} not found in chain")
        pending = remaining
