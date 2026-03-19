"""中间件 for 内存 mechanism."""

import re
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.memory.queue import get_memory_queue
from deerflow.config.memory_config import get_memory_config


class MemoryMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


def _filter_messages_for_memory(messages: list[Any]) -> list[Any]:
    """Filter messages to keep only 用户 inputs and final assistant responses.

    This filters out:
    - 工具 messages (intermediate 工具 call results)
    - AI messages with tool_calls (intermediate steps, not final responses)
    - The <uploaded_files> block injected by UploadsMiddleware into human messages
      (文件 paths are 会话-scoped and must not persist in long-term 内存).
      The 用户's actual question is preserved; only turns whose content is entirely
      the upload block (nothing remains after stripping) are dropped along with
      their paired assistant 响应.

    Only keeps:
    - Human messages (with the ephemeral upload block removed)
    - AI messages without tool_calls (final assistant responses), unless the
      paired human turn was upload-only and had no real 用户 text.

    Args:
        messages: List of all conversation messages.

    Returns:
        Filtered 列表 containing only 用户 inputs and final assistant responses.
    """
    _UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            content_str = str(content)
            if "<uploaded_files>" in content_str:
                #    Strip the ephemeral upload block; keep the 用户's real question.


                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    #    Nothing 左 — the entire turn was upload bookkeeping;


                    #    skip it and the paired assistant 响应.


                    skip_next_ai = True
                    continue
                #    Rebuild the 消息 with cleaned content so the 用户's question


                #    is still 可用的 对于 内存 summarisation.


                from copy import copy

                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)
        #    Skip 工具 messages and AI messages with tool_calls



    return filtered


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    """中间件 that queues conversation for 内存 更新 after 代理 execution.

    This 中间件:
    1. After each 代理 execution, queues the conversation for 内存 更新
    2. Only includes 用户 inputs and final assistant responses (ignores 工具 calls)
    3. The queue uses debouncing to batch multiple updates together
    4. 内存 is updated asynchronously via LLM summarization
    """

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None):
        """Initialize the MemoryMiddleware.

        Args:
            agent_name: If provided, 内存 is stored per-代理. If None, uses global 内存.
        """
        super().__init__()
        self._agent_name = agent_name

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue conversation for 内存 更新 after 代理 completes.

        Args:
            状态: The 当前 代理 状态.
            runtime: The runtime context.

        Returns:
            None (no 状态 changes needed from this 中间件).
        """
        config = get_memory_config()
        if not config.enabled:
            return None

        #    Get 线程 ID from runtime context


        thread_id = runtime.context.get("thread_id")
        if not thread_id:
            print("MemoryMiddleware: No thread_id in context, skipping memory update")
            return None

        #    Get messages from 状态


        messages = state.get("messages", [])
        if not messages:
            print("MemoryMiddleware: No messages in state, skipping memory update")
            return None

        #    Filter to only keep 用户 inputs and final assistant responses


        filtered_messages = _filter_messages_for_memory(messages)

        #    Only queue 如果 there's meaningful conversation


        #    At minimum need one 用户 消息 and one assistant 响应


        user_messages = [m for m in filtered_messages if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered_messages if getattr(m, "type", None) == "ai"]

        if not user_messages or not assistant_messages:
            return None

        #    Queue the filtered conversation 对于 内存 更新


        queue = get_memory_queue()
        queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name)

        return None
