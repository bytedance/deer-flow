"""Middleware to detect and break repetitive tool call loops.

P0 safety: prevents the agent from calling the same tool with the same
arguments indefinitely until the recursion limit kills the run.

Detection strategy:
  1. After each model response, hash the tool calls (name + args).
  2. Track recent hashes in a sliding window.
  3. If the same hash appears >= warn_threshold times, inject a
     "you are repeating yourself — wrap up" system message.
  4. If it appears >= hard_limit times, strip all tool_calls from the
     response so the agent is forced to produce a final text answer.
"""

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Defaults — can be overridden via constructor
_DEFAULT_WARN_THRESHOLD = 3  # inject warning after 3 identical calls
_DEFAULT_HARD_LIMIT = 5  # force-stop after 5 identical calls
_DEFAULT_WINDOW_SIZE = 20  # track last N tool calls


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """Deterministic hash of a set of tool calls (name + args)."""
    normalized = []
    for tc in sorted(tool_calls, key=lambda t: t.get("name", "")):
        normalized.append({
            "name": tc.get("name", ""),
            "args": tc.get("args", {}),
        })
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


_WARNING_MSG = (
    "[LOOP DETECTED] You are repeating the same tool calls. "
    "Stop calling tools and produce your final answer now. "
    "If you cannot complete the task, summarize what you accomplished so far."
)

_HARD_STOP_MSG = (
    "[FORCED STOP] Repeated tool calls exceeded the safety limit. "
    "Producing final answer with results collected so far."
)


class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    """Detects and breaks repetitive tool call loops.

    Args:
        warn_threshold: Number of identical tool call sets before injecting
            a warning message. Default: 3.
        hard_limit: Number of identical tool call sets before stripping
            tool_calls entirely. Default: 5.
        window_size: Size of the sliding window for tracking calls.
            Default: 20.
    """

    def __init__(
        self,
        warn_threshold: int = _DEFAULT_WARN_THRESHOLD,
        hard_limit: int = _DEFAULT_HARD_LIMIT,
        window_size: int = _DEFAULT_WINDOW_SIZE,
    ):
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        # Per-thread tracking: thread_id -> list of recent hashes
        self._history: dict[str, list[str]] = defaultdict(list)
        self._warned: dict[str, set[str]] = defaultdict(set)

    def _get_thread_id(self, state: AgentState) -> str:
        """Extract thread_id from state for per-thread tracking."""
        thread_data = state.get("thread_data")
        if thread_data and isinstance(thread_data, dict):
            return thread_data.get("workspace_path", "default") or "default"
        return "default"

    def _track_and_check(self, state: AgentState) -> tuple[str | None, bool]:
        """Track tool calls and check for loops.

        Returns:
            (warning_message_or_none, should_hard_stop)
        """
        messages = state.get("messages", [])
        if not messages:
            return None, False

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None, False

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None, False

        thread_id = self._get_thread_id(state)
        call_hash = _hash_tool_calls(tool_calls)

        # Append to sliding window
        history = self._history[thread_id]
        history.append(call_hash)
        if len(history) > self.window_size:
            history[:] = history[-self.window_size:]

        # Count occurrences in window
        count = history.count(call_hash)

        tool_names = [tc.get("name", "?") for tc in tool_calls]

        if count >= self.hard_limit:
            logger.error(
                "Loop hard limit reached — forcing stop",
                extra={
                    "thread_id": thread_id,
                    "call_hash": call_hash,
                    "count": count,
                    "tools": tool_names,
                },
            )
            return _HARD_STOP_MSG, True

        if count >= self.warn_threshold:
            warned = self._warned[thread_id]
            if call_hash not in warned:
                warned.add(call_hash)
                logger.warning(
                    "Repetitive tool calls detected — injecting warning",
                    extra={
                        "thread_id": thread_id,
                        "call_hash": call_hash,
                        "count": count,
                        "tools": tool_names,
                    },
                )
            return _WARNING_MSG, False

        return None, False

    def _apply(self, state: AgentState) -> dict | None:
        warning, hard_stop = self._track_and_check(state)

        if hard_stop:
            # Strip tool_calls from the last AIMessage to force text output
            messages = state.get("messages", [])
            last_msg = messages[-1]
            stripped_msg = last_msg.model_copy(update={
                "tool_calls": [],
                "content": (last_msg.content or "") + f"\n\n{_HARD_STOP_MSG}",
            })
            return {"messages": [stripped_msg]}

        if warning:
            # Inject a system message warning the model
            return {"messages": [SystemMessage(content=warning)]}

        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    def reset(self, thread_id: str | None = None) -> None:
        """Clear tracking state. If thread_id given, clear only that thread."""
        if thread_id:
            self._history.pop(thread_id, None)
            self._warned.pop(thread_id, None)
        else:
            self._history.clear()
            self._warned.clear()
