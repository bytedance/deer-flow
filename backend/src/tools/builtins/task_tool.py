"""Task tool for delegating work to subagents."""

import logging
import time
import uuid
from dataclasses import replace
from typing import Annotated, Literal

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.lead_agent.prompt import get_skills_prompt_section
from src.agents.middlewares.usage_tracking_middleware import add_subagent_usage
from src.agents.thread_state import SubagentTrajectoryState, ThreadState
from src.subagents import SubagentExecutor, get_subagent_config
from src.subagents.executor import SubagentStatus, cleanup_background_task, get_background_task_result

logger = logging.getLogger(__name__)


def _serialize_subagent_status(status: SubagentStatus) -> str:
    if status == SubagentStatus.COMPLETED:
        return "completed"
    if status == SubagentStatus.FAILED:
        return "failed"
    if status == SubagentStatus.TIMED_OUT:
        return "timed_out"
    if status == SubagentStatus.RUNNING:
        return "running"
    return "pending"


def _build_subagent_trajectory(
    *,
    task_id: str,
    subagent_type: str,
    description: str,
    prompt: str,
    status: SubagentStatus,
    result: str | None,
    error: str | None,
    started_at: str | None,
    completed_at: str | None,
    token_usage: dict[str, int] | None,
    messages: list[dict],
) -> dict[str, SubagentTrajectoryState]:
    return {
        task_id: {
            "task_id": task_id,
            "subagent_type": subagent_type,
            "description": description,
            "prompt": prompt,
            "status": _serialize_subagent_status(status),
            "result": result,
            "error": error,
            "started_at": started_at,
            "completed_at": completed_at,
            "token_usage": token_usage or {"input_tokens": 0, "output_tokens": 0},
            "messages": messages,
        }
    }


def _command_with_tool_message(
    *,
    content: str,
    tool_call_id: str,
    subagent_trajectories: dict[str, SubagentTrajectoryState] | None = None,
) -> Command:
    update: dict = {"messages": [ToolMessage(content, tool_call_id=tool_call_id)]}
    if subagent_trajectories is not None:
        update["subagent_trajectories"] = subagent_trajectories
    return Command(update=update)


@tool("task", parse_docstring=True)
def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    prompt: str,
    subagent_type: Literal["general-purpose", "bash"],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,
) -> Command | str:
    """Delegate a task to a specialized subagent that runs in its own context.

    Subagents help you:
    - Preserve context by keeping exploration and implementation separate
    - Handle complex multi-step tasks autonomously
    - Execute commands or operations in isolated contexts

    Available subagent types:
    - **general-purpose**: A capable agent for complex, multi-step tasks that require
      both exploration and action. Use when the task requires complex reasoning,
      multiple dependent steps, or would benefit from isolated context.
    - **bash**: Command execution specialist for running bash commands. Use for
      git operations, build processes, or when command output would be verbose.

    When to use this tool:
    - Complex tasks requiring multiple steps or tools
    - Tasks that produce verbose output
    - When you want to isolate context from the main conversation
    - Parallel research or exploration tasks

    When NOT to use this tool:
    - Simple, single-step operations (use tools directly)
    - Tasks requiring user interaction or clarification

    Args:
        description: A short (3-5 word) description of the task for logging/display. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent. Be specific and clear about what needs to be done. ALWAYS PROVIDE THIS PARAMETER SECOND.
        subagent_type: The type of subagent to use. ALWAYS PROVIDE THIS PARAMETER THIRD.
        max_turns: Optional maximum number of agent turns. Defaults to subagent's configured max.
    """
    # Get subagent configuration
    config = get_subagent_config(subagent_type)
    if config is None:
        return _command_with_tool_message(
            content=f"Error: Unknown subagent type '{subagent_type}'. Available: general-purpose, bash",
            tool_call_id=tool_call_id,
        )

    # Build config overrides
    overrides: dict = {}

    skills_section = get_skills_prompt_section()
    if skills_section:
        overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section

    if max_turns is not None:
        overrides["max_turns"] = max_turns

    if overrides:
        config = replace(config, **overrides)

    # Extract parent context from runtime
    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    parent_model_spec = None
    trace_id = None
    user_id = None
    parent_thinking_enabled = False
    parent_thinking_effort = None

    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id")
        user_id = runtime.context.get("user_id")

        # Try to get parent model from configurable
        metadata = runtime.config.get("metadata", {})
        parent_model = metadata.get("model_name")

        # Get runtime model spec for provider-based models (e.g. "anthropic:claude-sonnet-4-6")
        # This is needed so subagents can inherit the correct model + API key
        configurable = runtime.config.get("configurable", {})
        model_spec = configurable.get("model_spec")
        if isinstance(model_spec, dict):
            parent_model_spec = dict(model_spec)  # shallow copy
            # Ensure user_id is included for API key lookup
            if user_id and "user_id" not in parent_model_spec:
                parent_model_spec["user_id"] = user_id
        parent_thinking_enabled = bool(configurable.get("thinking_enabled", False))
        thinking_effort = configurable.get("thinking_effort")
        if isinstance(thinking_effort, str):
            normalized_effort = thinking_effort.strip().lower()
            parent_thinking_effort = normalized_effort or None

        # Get or generate trace_id for distributed tracing
        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    # Get available tools (excluding task tool to prevent nesting)
    # Lazy import to avoid circular dependency
    from src.tools import get_available_tools

    # Subagents should not have subagent tools enabled (prevent recursive nesting).
    # MCP tools are now supported: the executor uses asyncio.run() + agent.astream()
    # so async-only StructuredTools work correctly.
    tools = get_available_tools(model_name=parent_model, subagent_enabled=False, include_mcp=True)

    # Create executor
    executor = SubagentExecutor(
        config=config,
        tools=tools,
        parent_model=parent_model,
        parent_model_spec=parent_model_spec,
        parent_thinking_enabled=parent_thinking_enabled,
        parent_thinking_effort=parent_thinking_effort,
        sandbox_state=sandbox_state,
        thread_data=thread_data,
        thread_id=thread_id,
        trace_id=trace_id,
    )

    # Start background execution (always async to prevent blocking)
    # Use tool_call_id as task_id for better traceability
    task_id = executor.execute_async(prompt, task_id=tool_call_id, user_id=user_id)
    logger.info(f"[trace={trace_id}] Started background task {task_id}, polling for completion...")

    # Poll for task completion in backend (removes need for LLM to poll)
    poll_count = 0
    last_status = None
    last_trajectory_count = 0  # Track how many trajectory messages we've streamed

    writer = get_stream_writer()
    # Send Task Started message'
    writer(
        {
            "type": "task_started",
            "task_id": task_id,
            "description": description,
            "subagent_type": subagent_type,
            "prompt": prompt,
        }
    )

    while True:
        result = get_background_task_result(task_id)

        if result is None:
            logger.error(f"[trace={trace_id}] Task {task_id} not found in background tasks")
            writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared from background tasks"})
            cleanup_background_task(task_id)
            return _command_with_tool_message(
                content=f"Error: Task {task_id} disappeared from background tasks",
                tool_call_id=tool_call_id,
                subagent_trajectories=_build_subagent_trajectory(
                    task_id=task_id,
                    subagent_type=subagent_type,
                    description=description,
                    prompt=prompt,
                    status=SubagentStatus.FAILED,
                    result=None,
                    error="Task disappeared from background tasks",
                    started_at=None,
                    completed_at=None,
                    token_usage=None,
                    messages=[],
                ),
            )

        # Log status changes for debugging
        if result.status != last_status:
            logger.info(f"[trace={trace_id}] Task {task_id} status: {result.status.value}")
            last_status = result.status

        # Check for new trajectory messages (AI + tool) and send task_running events
        current_trajectory_count = len(result.trajectory_messages)
        if current_trajectory_count > last_trajectory_count:
            # Send task_running event for each new message in the trajectory
            for i in range(last_trajectory_count, current_trajectory_count):
                message = result.trajectory_messages[i]
                writer(
                    {
                        "type": "task_running",
                        "task_id": task_id,
                        "message": message,
                        "message_index": i + 1,  # 1-based index for display
                        "total_messages": current_trajectory_count,
                    }
                )
                msg_type = message.get("type", "unknown") if isinstance(message, dict) else "unknown"
                logger.info(f"[trace={trace_id}] Task {task_id} sent {msg_type} message #{i + 1}/{current_trajectory_count}")
            last_trajectory_count = current_trajectory_count

        # Check if task completed, failed, or timed out
        if result.status in (SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.TIMED_OUT):
            # Register subagent token usage for the lead agent's next after_model drain
            if result.token_usage and thread_id:
                add_subagent_usage(thread_id, result.token_usage)
                # Also emit immediately for real-time frontend display
                writer(
                    {
                        "type": "usage_update",
                        "input_tokens": result.token_usage.get("input_tokens", 0),
                        "output_tokens": result.token_usage.get("output_tokens", 0),
                    }
                )

            if result.status == SubagentStatus.COMPLETED:
                writer({"type": "task_completed", "task_id": task_id, "result": result.result, "trajectory": result.trajectory_messages or []})
                logger.info(f"[trace={trace_id}] Task {task_id} completed after {poll_count} polls")
                cleanup_background_task(task_id)
                final_text = f"Task Succeeded. Result: {result.result}"
                return _command_with_tool_message(
                    content=final_text,
                    tool_call_id=tool_call_id,
                    subagent_trajectories=_build_subagent_trajectory(
                        task_id=task_id,
                        subagent_type=subagent_type,
                        description=description,
                        prompt=prompt,
                        status=result.status,
                        result=result.result,
                        error=result.error,
                        started_at=result.started_at.isoformat() if result.started_at else None,
                        completed_at=result.completed_at.isoformat() if result.completed_at else None,
                        token_usage=result.token_usage,
                        messages=result.trajectory_messages or [],
                    ),
                )
            elif result.status == SubagentStatus.FAILED:
                writer({"type": "task_failed", "task_id": task_id, "error": result.error, "trajectory": result.trajectory_messages or []})
                logger.error(f"[trace={trace_id}] Task {task_id} failed: {result.error}")
                cleanup_background_task(task_id)
                final_text = f"Task failed. Error: {result.error}"
                return _command_with_tool_message(
                    content=final_text,
                    tool_call_id=tool_call_id,
                    subagent_trajectories=_build_subagent_trajectory(
                        task_id=task_id,
                        subagent_type=subagent_type,
                        description=description,
                        prompt=prompt,
                        status=result.status,
                        result=result.result,
                        error=result.error,
                        started_at=result.started_at.isoformat() if result.started_at else None,
                        completed_at=result.completed_at.isoformat() if result.completed_at else None,
                        token_usage=result.token_usage,
                        messages=result.trajectory_messages or [],
                    ),
                )
            else:
                writer({"type": "task_timed_out", "task_id": task_id, "error": result.error})
                logger.warning(f"[trace={trace_id}] Task {task_id} timed out: {result.error}")
                cleanup_background_task(task_id)
                final_text = f"Task timed out. Error: {result.error}"
                return _command_with_tool_message(
                    content=final_text,
                    tool_call_id=tool_call_id,
                    subagent_trajectories=_build_subagent_trajectory(
                        task_id=task_id,
                        subagent_type=subagent_type,
                        description=description,
                        prompt=prompt,
                        status=result.status,
                        result=result.result,
                        error=result.error,
                        started_at=result.started_at.isoformat() if result.started_at else None,
                        completed_at=result.completed_at.isoformat() if result.completed_at else None,
                        token_usage=result.token_usage,
                        messages=result.trajectory_messages or [],
                    ),
                )

        # Still running, wait before next poll
        time.sleep(5)  # Poll every 5 seconds
        poll_count += 1

        # Polling timeout as a safety net (in case thread pool timeout doesn't work)
        # Set to 16 minutes (longer than the default 15-minute thread pool timeout)
        # This catches edge cases where the background task gets stuck
        # NOTE: Do NOT call cleanup_background_task here — the background executor
        # may still be running and updating the task entry.
        if poll_count > 192:  # 192 * 5s = 16 minutes
            logger.error(f"[trace={trace_id}] Task {task_id} polling timed out after {poll_count} polls (should have been caught by thread pool timeout)")
            writer({"type": "task_timed_out", "task_id": task_id})
            return _command_with_tool_message(
                content=f"Task polling timed out after 16 minutes. This may indicate the background task is stuck. Status: {result.status.value}",
                tool_call_id=tool_call_id,
                subagent_trajectories=_build_subagent_trajectory(
                    task_id=task_id,
                    subagent_type=subagent_type,
                    description=description,
                    prompt=prompt,
                    status=SubagentStatus.TIMED_OUT,
                    result=result.result,
                    error="Polling timed out after 16 minutes",
                    started_at=result.started_at.isoformat() if result.started_at else None,
                    completed_at=result.completed_at.isoformat() if result.completed_at else None,
                    token_usage=result.token_usage,
                    messages=result.trajectory_messages or [],
                ),
            )
