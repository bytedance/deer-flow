"""Subagent execution engine."""

import asyncio
import logging
import threading
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

from deerflow.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from deerflow.models import create_chat_model
from deerflow.subagents.config import SubagentConfig

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
        结果: The final 结果 消息 (if completed).
        错误: 错误 消息 (if failed).
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

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []


#    Global storage 对于 background task results


_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

#    线程 pool 对于 background task scheduling and orchestration


_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")

#    线程 pool 对于 actual subagent execution (with timeout support)


#    Larger pool to avoid blocking when scheduler submits execution tasks


_execution_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-exec-")


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    """Filter tools based on subagent configuration.

    Args:
        all_tools: List of all 可用的 tools.
        allowed: Optional allowlist of 工具 names. If provided, only these tools are included.
        disallowed: Optional denylist of 工具 names. These tools are always excluded.

    Returns:
        Filtered 列表 of tools.
    """
    filtered = all_tools

    #    Apply allowlist 如果 specified


    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    #    Apply denylist


    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


def _get_model_name(config: SubagentConfig, parent_model: str | None) -> str | None:
    """Resolve the 模型 名称 for a subagent.

    Args:
        配置: Subagent configuration.
        parent_model: The parent 代理's 模型 名称.

    Returns:
        模型 名称 to use, or None to use 默认.
    """
    if config.model == "inherit":
        return parent_model
    return config.model


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
    ):
        """Initialize the executor.

        Args:
            配置: Subagent configuration.
            tools: List of all 可用的 tools (will be filtered).
            parent_model: The parent 代理's 模型 名称 for inheritance.
            sandbox_state: Sandbox 状态 from parent 代理.
            thread_data: 线程 数据 from parent 代理.
            thread_id: 线程 ID for sandbox operations.
            trace_id: Trace ID from parent for distributed tracing.
        """
        self.config = config
        self.parent_model = parent_model
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        #    Generate trace_id 如果 not provided (对于 顶部-level calls)


        self.trace_id = trace_id or str(uuid.uuid4())[:8]

        #    Filter tools based on 配置


        self.tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _create_agent(self):
        """Create the 代理 instance."""
        model_name = _get_model_name(self.config, self.parent_model)
        model = create_chat_model(name=model_name, thinking_enabled=False)

        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        #    Reuse shared 中间件 composition with lead 代理.


        middlewares = build_subagent_runtime_middlewares(lazy_init=True)

        return create_agent(
            model=model,
            tools=self.tools,
            middleware=middlewares,
            system_prompt=self.config.system_prompt,
            state_schema=ThreadState,
        )

    def _build_initial_state(self, task: str) -> dict[str, Any]:
        """Build the initial 状态 for 代理 execution.

        Args:
            task: The task 描述.

        Returns:
            Initial 状态 dictionary.
        """
        state: dict[str, Any] = {
            "messages": [HumanMessage(content=task)],
        }

        #    Pass through sandbox and 线程 数据 from parent


        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task asynchronously.

        Args:
            task: The task 描述 for the subagent.
            result_holder: Optional pre-created 结果 对象 to 更新 during execution.

        Returns:
            SubagentResult with the execution 结果.
        """
        if result_holder is not None:
            #    Use the provided 结果 holder (对于 异步 execution with real-time updates)


            result = result_holder
        else:
            #    Create a 新建 结果 对于 synchronous execution


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

            #    Build 配置 with thread_id 对于 sandbox access and recursion limit


            run_config: RunnableConfig = {
                "recursion_limit": self.config.max_turns,
            }
            context = {}
            if self.thread_id:
                run_config["configurable"] = {"thread_id": self.thread_id}
                context["thread_id"] = self.thread_id

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution with max_turns={self.config.max_turns}")

            #    Use stream instead of invoke to get real-time updates


            #    This allows us to collect AI messages as they are generated


            final_state = None
            async for chunk in agent.astream(state, config=run_config, context=context, stream_mode="values"):  #    类型: ignore[arg-类型]


                final_state = chunk

                #    Extract AI messages from the 当前 状态


                messages = chunk.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    #    Check 如果 this is a 新建 AI 消息


                    if isinstance(last_message, AIMessage):
                        #    Convert 消息 to 字典 对于 serialization


                        message_dict = last_message.model_dump()
                        #    Only add 如果 it's not already in the 列表 (avoid duplicates)


                        #    Check by comparing 消息 IDs 如果 可用的, otherwise compare full 字典


                        message_id = message_dict.get("id")
                        is_duplicate = False
                        if message_id:
                            is_duplicate = any(msg.get("id") == message_id for msg in result.ai_messages)
                        else:
                            is_duplicate = message_dict in result.ai_messages

                        if not is_duplicate:
                            result.ai_messages.append(message_dict)
                            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured AI message #  {len(result.ai_messages)}")



            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")

            if final_state is None:
                logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no final state")
                result.result = "No response generated"
            else:
                #    Extract the final 消息 - find the 最后 AIMessage


                messages = final_state.get("messages", [])
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} final messages count: {len(messages)}")

                #    Find the 最后 AIMessage in the conversation


                last_ai_message = None
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage):
                        last_ai_message = msg
                        break

                if last_ai_message is not None:
                    content = last_ai_message.content
                    #    Handle both str and 列表 content types 对于 the final 结果


                    if isinstance(content, str):
                        result.result = content
                    elif isinstance(content, list):
                        #    Extract text from 列表 of content blocks 对于 final 结果 only


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
                    #    Fallback: use the 最后 消息 如果 no AIMessage found


                    last_message = messages[-1]
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no AIMessage found, using last message: {type(last_message)}")
                    result.result = str(last_message.content) if hasattr(last_message, "content") else str(last_message)
                else:
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no messages in final state")
                    result.result = "No response generated"

            result.status = SubagentStatus.COMPLETED
            result.completed_at = datetime.now()

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
            result.status = SubagentStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now()

        return result

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously (wrapper around 异步 execution).

        This 方法 runs the 异步 execution in a 新建 event 循环, allowing
        asynchronous tools (like MCP tools) to be used within the 线程 pool.

        Args:
            task: The task 描述 for the subagent.
            result_holder: Optional pre-created 结果 对象 to 更新 during execution.

        Returns:
            SubagentResult with the execution 结果.
        """
        #    Run the 异步 execution in a 新建 event 循环


        #    This is necessary because:


        #    1. We may have 异步-only tools (like MCP tools)


        #    2. We're running inside a ThreadPoolExecutor which doesn't have an event 循环


        #
        #    Note: _aexecute() catches all exceptions internally, so this outer


        #    try-except only handles asyncio.运行() failures (e.g., 如果 called from


        #    an 异步 context where an event 循环 already exists). Subagent execution


        #    errors are handled within _aexecute() and returned as FAILED status.


        try:
            return asyncio.run(self._aexecute(task, result_holder))
        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            #    Create a 结果 with 错误 如果 we don't have one


            if result_holder is not None:
                result = result_holder
            else:
                result = SubagentResult(
                    task_id=str(uuid.uuid4())[:8],
                    trace_id=self.trace_id,
                    status=SubagentStatus.FAILED,
                )
            result.status = SubagentStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now()
            return result

    def execute_async(self, task: str, task_id: str | None = None) -> str:
        """Start a task execution in the background.

        Args:
            task: The task 描述 for the subagent.
            task_id: Optional task ID to use. If not provided, a random UUID will be generated.

        Returns:
            Task ID that can be used to 检查 status later.
        """
        #    Use provided task_id or generate a 新建 one


        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        #    Create initial 待处理 结果


        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}, timeout={self.config.timeout_seconds}s")

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        #    Submit to scheduler pool


        def run_task():
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now()
                result_holder = _background_tasks[task_id]

            try:
                #    Submit execution to execution pool with timeout


                #    Pass result_holder so 执行() can 更新 it in real-time


                execution_future: Future = _execution_pool.submit(self.execute, task, result_holder)
                try:
                    #    Wait 对于 execution with timeout


                    exec_result = execution_future.result(timeout=self.config.timeout_seconds)
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = exec_result.status
                        _background_tasks[task_id].result = exec_result.result
                        _background_tasks[task_id].error = exec_result.error
                        _background_tasks[task_id].completed_at = datetime.now()
                        _background_tasks[task_id].ai_messages = exec_result.ai_messages
                except FuturesTimeoutError:
                    logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                        _background_tasks[task_id].error = f"Execution timed out after {self.config.timeout_seconds} seconds"
                        _background_tasks[task_id].completed_at = datetime.now()
                    #    Cancel the future (best effort - may not 停止 the actual execution)


                    execution_future.cancel()
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = str(e)
                    _background_tasks[task_id].completed_at = datetime.now()

        _scheduler_pool.submit(run_task)
        return task_id


MAX_CONCURRENT_SUBAGENTS = 3


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the 结果 of a background task.

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


def cleanup_background_task(task_id: str) -> None:
    """Remove a completed task from background tasks.

    Should be called by task_tool after it finishes polling and returns the 结果.
    This prevents 内存 leaks from accumulated completed tasks.

    Only removes tasks that are in a terminal 状态 (COMPLETED/FAILED/TIMED_OUT)
    to avoid race conditions with the background executor still updating the task entry.

    Args:
        task_id: The task ID to remove.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is None:
            #    Nothing to clean 上; may have been removed already.


            logger.debug("Requested cleanup for unknown background task %s", task_id)
            return

        #    Only clean 上 tasks that are in a terminal 状态 to avoid races with


        #    the background executor still updating the task entry.


        is_terminal_status = result.status in {
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.TIMED_OUT,
        }
        if is_terminal_status or result.completed_at is not None:
            del _background_tasks[task_id]
            logger.debug("Cleaned up background task: %s", task_id)
        else:
            logger.debug(
                "Skipping cleanup for non-terminal background task %s (status=%s)",
                task_id,
                result.status.value if hasattr(result.status, "value") else result.status,
            )
