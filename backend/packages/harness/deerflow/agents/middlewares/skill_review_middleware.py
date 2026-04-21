"""Middleware that triggers background skill review after sufficient tool-call iterations."""

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.skill_review.reviewer import SkillReviewer
from deerflow.config.app_config import get_app_config

logger = logging.getLogger(__name__)

_MAX_TRACKED_THREADS = 100  # LRU eviction limit


class SkillReviewMiddleware(AgentMiddleware[AgentState]):
    """After-agent middleware that triggers skill review when iteration threshold is reached.

    Counts tool-call iterations per thread. Once the count reaches
    ``config.skill_evolution.creation_nudge_interval``, a background
    ``SkillReviewer`` is launched and the counter is reset.
    """

    def __init__(self, config=None):
        super().__init__()
        self._config = config
        self._reviewer: SkillReviewer | None = None
        self._lock = threading.Lock()
        # Per-thread accumulated tool-call rounds since last review; OrderedDict for LRU eviction
        self._iters: OrderedDict[str, int] = OrderedDict()
        # Per-thread last-seen total tool-call rounds (to compute per-turn deltas)
        self._last_seen: dict[str, int] = {}
        logger.info("SkillReviewMiddleware.__init__ called, config=%s, skill_evolution=%s", type(config).__name__, getattr(config, "skill_evolution", None))

    def _ensure_config(self):
        """Lazily resolve config and reviewer (avoids import-time disk reads)."""
        if self._config is None:
            self._config = get_app_config()
        if self._reviewer is None:
            self._reviewer = SkillReviewer(self._config)

    def _get_thread_id(self, runtime: Runtime) -> str | None:
        """Extract thread_id from runtime context, then fall back to LangGraph configurable."""
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id:
            return thread_id
        config_data = get_config()
        return config_data.get("configurable", {}).get("thread_id")

    def _count_tool_call_rounds(self, state: AgentState) -> int:
        """Count total tool-call rounds (AI messages that contain tool_calls) in the conversation."""
        messages = state.get("messages", [])
        total = 0
        for msg in messages:
            if getattr(msg, "type", None) == "ai":
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    total += 1
        return total

    def _evict_if_needed(self) -> None:
        """Evict least recently used threads if over the limit.

        Must be called while holding self._lock.
        """
        while len(self._iters) > _MAX_TRACKED_THREADS:
            evicted_id, _ = self._iters.popitem(last=False)
            self._last_seen.pop(evicted_id, None)
            logger.debug("Evicted skill review counter for thread %s (LRU)", evicted_id)

    @override
    async def awrap_tool_call(self, request, handler):
        """Before tool execution: if skill_manage is called, reset the counter for this thread."""
        tool_name = request.tool_call.get("name", "")
        if tool_name == "skill_manage":
            thread_id = self._get_thread_id(request.runtime) if request.runtime else None
            if thread_id:
                with self._lock:
                    self._iters.pop(thread_id, None)
                    logger.info("SkillReviewMiddleware: counter reset for thread %s (skill_manage called)", thread_id)
        return await handler(request)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """Check iteration count and trigger background skill review if threshold reached."""
        logger.info("SkillReviewMiddleware.aafter_agent CALLED — entry point reached")
        self._ensure_config()

        if not getattr(self._config, "skill_evolution", None) or not self._config.skill_evolution.enabled:
            logger.info("SkillReviewMiddleware: skill_evolution not enabled, skipping")
            return None

        thread_id = self._get_thread_id(runtime)
        logger.info("SkillReviewMiddleware: thread_id=%s", thread_id)
        if not thread_id:
            logger.info("No thread_id in context, skipping skill review check")
            return None

        total_rounds = self._count_tool_call_rounds(state)
        logger.info("SkillReviewMiddleware: total_rounds=%d", total_rounds)
        if total_rounds == 0:
            return None

        threshold = self._config.skill_evolution.creation_nudge_interval

        with self._lock:
            last_seen = self._last_seen.get(thread_id, 0)
            new_rounds = total_rounds - last_seen
            self._last_seen[thread_id] = total_rounds

            if new_rounds <= 0:
                return None

            if thread_id in self._iters:
                self._iters.move_to_end(thread_id)
            else:
                self._iters[thread_id] = 0
                self._evict_if_needed()

            self._iters[thread_id] += new_rounds
            current = self._iters[thread_id]
            logger.info("SkillReviewMiddleware: thread=%s, new_rounds=%d, current=%d, threshold=%d", thread_id, new_rounds, current, threshold)

            if current < threshold:
                return None

            # Threshold reached — reset counter and trigger review
            self._iters[thread_id] = 0

        # Launch background review in a separate thread with its own event loop
        # to avoid RuntimeError when the main agent's event loop closes.
        messages = state.get("messages", [])
        if messages:
            logger.info("Skill review triggered for thread %s (%d tool-call iterations)", thread_id, current)
            try:
                thread = threading.Thread(
                    target=lambda: asyncio.run(self._reviewer.review(thread_id, messages)),
                    daemon=True,
                    name=f"skill-review-{thread_id}",
                )
                thread.start()
            except Exception:
                logger.warning("Failed to launch skill review for thread %s", thread_id, exc_info=True)

        return None
