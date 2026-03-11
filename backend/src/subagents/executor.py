"""Subagent execution engine."""

import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from src.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from src.models import create_chat_model
from src.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


class SubagentStatus(Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Unique identifier for this execution.
        trace_id: Trace ID for distributed tracing (links parent and subagent logs).
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed).
        started_at: When execution started.
        completed_at: When execution completed.
        ai_messages: List of complete AI messages (as dicts) generated during execution.
    """

    task_id: str
    trace_id: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    trajectory_messages: list[dict[str, Any]] | None = None
    token_usage: dict[str, int] | None = None

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []
        if self.trajectory_messages is None:
            self.trajectory_messages = []
        if self.token_usage is None:
            self.token_usage = {"input_tokens": 0, "output_tokens": 0}


# Global storage for background task results
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# Thread pool sizing: configurable via environment, defaults to max(8, cpu_count * 2)
_SCHEDULER_WORKERS = int(
    os.environ.get(
        "SUBAGENT_SCHEDULER_WORKERS",
        max(8, (os.cpu_count() or 4) * 2),
    )
)
_EXECUTION_WORKERS = int(
    os.environ.get(
        "SUBAGENT_EXECUTION_WORKERS",
        max(8, (os.cpu_count() or 4) * 2),
    )
)

# Thread pool for background task scheduling and orchestration
_scheduler_pool = ThreadPoolExecutor(
    max_workers=_SCHEDULER_WORKERS,
    thread_name_prefix="subagent-scheduler-",
)

# Thread pool for actual subagent execution (with timeout support)
_execution_pool = ThreadPoolExecutor(
    max_workers=_EXECUTION_WORKERS,
    thread_name_prefix="subagent-exec-",
)

# ---------------------------------------------------------------------------
# Per-user concurrency control
# ---------------------------------------------------------------------------
MAX_CONCURRENT_SUBAGENTS_PER_USER = int(os.environ.get("MAX_CONCURRENT_SUBAGENTS_PER_USER", 3))

# Bounded LRU cache of per-user semaphores: user_id -> (Semaphore, last_used)
_user_semaphores: dict[str, tuple[threading.Semaphore, float]] = {}
_user_semaphores_lock = threading.Lock()
_MAX_SEMAPHORE_CACHE_SIZE = 1000


def _get_user_semaphore(user_id: str) -> threading.Semaphore:
    """Get or create a per-user concurrency semaphore.

    Uses a bounded LRU cache. When the cache exceeds _MAX_SEMAPHORE_CACHE_SIZE,
    the oldest 20% of entries (by last-used timestamp) are evicted.
    """
    with _user_semaphores_lock:
        entry = _user_semaphores.get(user_id)
        now = time.monotonic()

        if entry is not None:
            sem, _ = entry
            _user_semaphores[user_id] = (sem, now)
            return sem

        # Evict oldest entries if cache is full
        if len(_user_semaphores) >= _MAX_SEMAPHORE_CACHE_SIZE:
            sorted_entries = sorted(_user_semaphores.items(), key=lambda x: x[1][1])
            evict_count = _MAX_SEMAPHORE_CACHE_SIZE // 5  # Remove 20%
            for key, _ in sorted_entries[:evict_count]:
                del _user_semaphores[key]

        sem = threading.Semaphore(MAX_CONCURRENT_SUBAGENTS_PER_USER)
        _user_semaphores[user_id] = (sem, now)
        return sem


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


_RUNTIME_MODEL_PROVIDERS = {
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "kimi",
    "zai",
    "minimax",
    "epfl-rcp",
}


def _parse_runtime_model_spec(model_name: str) -> dict[str, str] | None:
    """Parse a model_name string like 'anthropic:claude-sonnet-4-6' into a runtime model spec dict.

    Returns None if the string is not a recognized runtime model spec.
    """
    parts = [p.strip() for p in model_name.split(":", 3)]
    if len(parts) < 2:
        return None
    provider = parts[0].lower()
    model_id = parts[1]
    if provider not in _RUNTIME_MODEL_PROVIDERS or not model_id:
        return None

    spec: dict[str, str] = {
        "provider": provider,
        "model_id": model_id,
    }
    if len(parts) >= 3 and parts[2] and parts[2].lower() != "standard":
        spec["tier"] = parts[2]
    if len(parts) >= 4 and parts[3]:
        spec["thinking_effort"] = parts[3]
    return spec


def _get_model_name(config: SubagentConfig, parent_model: str | None) -> str | None:
    """Resolve the model name for a subagent.

    Args:
        config: Subagent configuration.
        parent_model: The parent agent's model name.

    Returns:
        Model name to use, or None to use default.
    """
    if config.model == "inherit":
        return parent_model
    return config.model


def _resolve_thinking_enabled(config: SubagentConfig, parent_thinking_enabled: bool) -> bool:
    """Resolve effective thinking_enabled for a subagent."""
    if config.thinking_enabled == "inherit":
        return parent_thinking_enabled
    return bool(config.thinking_enabled)


def _resolve_thinking_effort(config: SubagentConfig, parent_thinking_effort: str | None) -> str | None:
    """Resolve effective thinking effort for a subagent."""
    if config.thinking_effort == "inherit":
        return parent_thinking_effort
    if isinstance(config.thinking_effort, str):
        normalized = config.thinking_effort.strip().lower()
        return normalized or None
    return None


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        parent_model: str | None = None,
        parent_model_spec: dict | None = None,
        parent_thinking_enabled: bool = False,
        parent_thinking_effort: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
    ):
        """Initialize the executor.

        Args:
            config: Subagent configuration.
            tools: List of all available tools (will be filtered).
            parent_model: The parent agent's model name for inheritance.
            parent_model_spec: Optional runtime model spec dict (provider, model_id, etc.)
                for provider-based models that aren't in config.yaml.
            parent_thinking_enabled: Parent run thinking flag (used when config inherits).
            parent_thinking_effort: Parent adaptive effort (used when config inherits).
            sandbox_state: Sandbox state from parent agent.
            thread_data: Thread data from parent agent.
            thread_id: Thread ID for sandbox operations.
            trace_id: Trace ID from parent for distributed tracing.
        """
        self.config = config
        self.parent_model = parent_model
        self.parent_model_spec = parent_model_spec
        self.thinking_enabled = _resolve_thinking_enabled(config, parent_thinking_enabled)
        self.thinking_effort = _resolve_thinking_effort(config, parent_thinking_effort)
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # Generate trace_id if not provided (for top-level calls)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

        # Filter tools based on config
        self.tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _create_agent(self):
        """Create the agent instance."""
        model_name = _get_model_name(self.config, self.parent_model)

        # Use runtime model spec if available (for provider-based models like
        # "anthropic:claude-sonnet-4-6" that aren't in config.yaml).
        runtime_model: dict[str, Any] | None = None
        if self.parent_model_spec and self.config.model == "inherit":
            runtime_model = dict(self.parent_model_spec)
        elif model_name and ":" in model_name:
            # Fallback: parse runtime model spec from model_name string
            runtime_model = _parse_runtime_model_spec(model_name)

        if runtime_model is not None:
            if self.thinking_effort is not None:
                runtime_model["thinking_effort"] = self.thinking_effort
            model = create_chat_model(runtime_model=runtime_model, thinking_enabled=self.thinking_enabled)
        else:
            model = create_chat_model(name=model_name, thinking_enabled=self.thinking_enabled)

        # Subagents need minimal middlewares to ensure tools can access sandbox and thread_data
        # These middlewares will reuse the sandbox/thread_data from parent agent
        from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from src.sandbox.middleware import SandboxMiddleware

        middlewares = [
            ThreadDataMiddleware(lazy_init=True),  # Compute thread paths
            SandboxMiddleware(lazy_init=True),  # Reuse parent's sandbox (no re-acquisition)
        ]

        return create_agent(
            model=model,
            tools=self.tools,
            middleware=middlewares,
            system_prompt=self.config.system_prompt,
            state_schema=ThreadState,
        )

    def _build_initial_state(self, task: str) -> dict[str, Any]:
        """Build the initial state for agent execution.

        Args:
            task: The task description.

        Returns:
            Initial state dictionary.
        """
        state: dict[str, Any] = {
            "messages": [HumanMessage(content=task)],
        }

        # Pass through sandbox and thread data from parent
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously.

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

        try:
            agent = self._create_agent()
            state = self._build_initial_state(task)

            # Build config with thread_id for sandbox access and recursion limit.
            # LangGraph's recursion_limit counts graph node transitions (agent→tool→agent),
            # not LLM calls. Each "turn" traverses ~3 nodes, so we multiply max_turns
            # by 3 and add a buffer to avoid premature termination.
            run_config: RunnableConfig = {
                "recursion_limit": max(self.config.max_turns * 3, 25),
            }
            context = {}
            if self.thread_id:
                run_config["configurable"] = {"thread_id": self.thread_id}
                context["thread_id"] = self.thread_id

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting execution with max_turns={self.config.max_turns}")

            # Use stream instead of invoke to get real-time updates
            # This allows us to collect AI messages as they are generated
            final_state = None
            seen_message_count = 0
            for chunk in agent.stream(state, config=run_config, context=context, stream_mode="values"):  # type: ignore[arg-type]
                final_state = chunk

                # Extract streamed messages from the current state
                messages = chunk.get("messages", [])
                if not isinstance(messages, list) or len(messages) <= seen_message_count:
                    continue

                new_messages = messages[seen_message_count:]
                seen_message_count = len(messages)

                for streamed_message in new_messages:
                    msg_type = getattr(streamed_message, "type", None)

                    # Capture full subagent trajectory (AI + tool interactions).
                    if msg_type in {"ai", "tool"}:
                        if hasattr(streamed_message, "model_dump"):
                            result.trajectory_messages.append(streamed_message.model_dump())
                        elif hasattr(streamed_message, "dict"):
                            result.trajectory_messages.append(streamed_message.dict())
                        else:
                            result.trajectory_messages.append(
                                {
                                    "type": msg_type,
                                    "content": getattr(streamed_message, "content", None),
                                    "id": getattr(streamed_message, "id", None),
                                }
                            )

                    if isinstance(streamed_message, AIMessage):
                        # Keep backward compatibility for streaming UI updates.
                        message_dict = streamed_message.model_dump()
                        result.ai_messages.append(message_dict)
                        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured AI message #{len(result.ai_messages)}")

                        # Accumulate token usage from this AI message
                        msg_usage = getattr(streamed_message, "usage_metadata", None)
                        if msg_usage and result.token_usage is not None:
                            result.token_usage["input_tokens"] += msg_usage.get("input_tokens", 0)
                            result.token_usage["output_tokens"] += msg_usage.get("output_tokens", 0)

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed execution")

            if final_state is None:
                logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no final state")
                result.result = "No response generated"
            else:
                # Extract the final message - find the last AIMessage
                messages = final_state.get("messages", [])
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} final messages count: {len(messages)}")

                # Find the last AIMessage in the conversation
                last_ai_message = None
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage):
                        last_ai_message = msg
                        break

                if last_ai_message is not None:
                    content = last_ai_message.content
                    # Handle both str and list content types for the final result
                    if isinstance(content, str):
                        result.result = content
                    elif isinstance(content, list):
                        # Extract text from list of content blocks for final result only
                        text_parts = []
                        for block in content:
                            if isinstance(block, str):
                                text_parts.append(block)
                            elif isinstance(block, dict) and "text" in block:
                                text_parts.append(block["text"])
                        result.result = "\n".join(text_parts) if text_parts else "No text content in response"
                    else:
                        result.result = str(content)
                elif messages:
                    # Fallback: use the last message if no AIMessage found
                    last_message = messages[-1]
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no AIMessage found, using last message: {type(last_message)}")
                    result.result = str(last_message.content) if hasattr(last_message, "content") else str(last_message)
                else:
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no messages in final state")
                    result.result = "No response generated"

            result.status = SubagentStatus.COMPLETED
            result.completed_at = datetime.now()

            # ── Prometheus metrics ─────────────────────────────────────
            try:
                from src.gateway.metrics import subagent_tasks_total

                subagent_tasks_total.labels(status="completed").inc()
            except Exception:
                pass

        except GraphRecursionError:
            # Graceful degradation: the agent hit its step limit but may have
            # produced useful partial work.  Instead of failing, we extract
            # the best result we have from the trajectory collected so far.
            logger.warning(
                f"[trace={self.trace_id}] Subagent {self.config.name} hit recursion limit "
                f"({max(self.config.max_turns * 3, 25)} steps). "
                "Wrapping up with partial results."
            )

            # Try to build a result from the last AI message in the trajectory
            partial_result: str | None = None
            for msg_dict in reversed(result.trajectory_messages):
                if msg_dict.get("type") == "ai":
                    content = msg_dict.get("content")
                    if isinstance(content, str) and content.strip():
                        partial_result = content
                        break
                    elif isinstance(content, list):
                        text_parts = [
                            b["text"] if isinstance(b, dict) and "text" in b else str(b)
                            for b in content
                            if isinstance(b, str) or (isinstance(b, dict) and "text" in b)
                        ]
                        if text_parts:
                            partial_result = "\n".join(text_parts)
                            break

            if partial_result:
                result.result = (
                    partial_result
                    + "\n\n---\n*Note: This subagent reached its maximum step limit "
                    "and returned partial results.*"
                )
                result.status = SubagentStatus.COMPLETED
            else:
                result.result = (
                    "This subagent reached its maximum step limit before producing a final answer. "
                    "The work done so far is available in the message history above."
                )
                result.status = SubagentStatus.COMPLETED

            result.completed_at = datetime.now()

            try:
                from src.gateway.metrics import subagent_tasks_total
                subagent_tasks_total.labels(status="completed").inc()
            except Exception:
                pass

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            result.status = SubagentStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now()

            # ── Prometheus metrics ─────────────────────────────────────
            try:
                from src.gateway.metrics import subagent_tasks_total

                subagent_tasks_total.labels(status="failed").inc()
            except Exception:
                pass

        return result

    def execute_async(
        self,
        task: str,
        task_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description for the subagent.
            task_id: Optional task ID to use. If not provided, a random UUID will be generated.
            user_id: Optional user ID for per-user concurrency limiting.

        Returns:
            Task ID that can be used to check status later.
        """
        # Use provided task_id or generate a new one
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        # Create initial pending result
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}")

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        # Submit to scheduler pool
        def run_task():
            # Acquire per-user semaphore to enforce concurrency limits
            sem = _get_user_semaphore(user_id or "anonymous")
            acquired = sem.acquire(timeout=30)
            if not acquired:
                logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} concurrency limit reached for user {user_id}")
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = f"Concurrency limit reached: max {MAX_CONCURRENT_SUBAGENTS_PER_USER} concurrent subagents per user"
                    _background_tasks[task_id].completed_at = datetime.now()
                return

            try:
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.RUNNING
                    _background_tasks[task_id].started_at = datetime.now()
                    result_holder = _background_tasks[task_id]

                # Submit execution to execution pool with timeout
                # Pass result_holder so execute() can update it in real-time
                execution_future: Future = _execution_pool.submit(self.execute, task, result_holder)
                try:
                    # Wait for execution with timeout
                    exec_result = execution_future.result(timeout=self.config.timeout_seconds)
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = exec_result.status
                        _background_tasks[task_id].result = exec_result.result
                        _background_tasks[task_id].error = exec_result.error
                        _background_tasks[task_id].completed_at = datetime.now()
                        _background_tasks[task_id].ai_messages = exec_result.ai_messages
                        _background_tasks[task_id].trajectory_messages = exec_result.trajectory_messages
                except FuturesTimeoutError:
                    logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                        _background_tasks[task_id].error = f"Execution timed out after {self.config.timeout_seconds} seconds"
                        _background_tasks[task_id].completed_at = datetime.now()
                    # Cancel the future (best effort - may not stop the actual execution)
                    execution_future.cancel()

                    try:
                        from src.gateway.metrics import subagent_tasks_total

                        subagent_tasks_total.labels(status="timed_out").inc()
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = str(e)
                    _background_tasks[task_id].completed_at = datetime.now()
            finally:
                sem.release()

        _scheduler_pool.submit(run_task)
        return task_id


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        task_id: The task ID returned by execute_async.

    Returns:
        SubagentResult if found, None otherwise.
    """
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def list_background_tasks() -> list[SubagentResult]:
    """List all background tasks.

    Returns:
        List of all SubagentResult instances.
    """
    with _background_tasks_lock:
        return list(_background_tasks.values())
