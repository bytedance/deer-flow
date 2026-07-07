"""Combined middleware: loop detection + token budget enforcement.

Merges two formerly separate middlewares (``LoopDetectionMiddleware`` and
``TokenBudgetMiddleware``) to share the ``wrap_model_call`` hook, warning
queue, and lifecycle management — reducing chain traversal overhead.

Both detection strategies keep their own configs and state dictionaries;
only the Middleware SPI layer is unified.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware

if TYPE_CHECKING:
    from deerflow.config.loop_detection_config import LoopDetectionConfig
    from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

# Maximum warning queue length per run (shared drain)
_MAX_PENDING_WARNINGS = 4


class ResourceGuardMiddleware(AgentMiddleware[AgentState]):
    """Combined safety guard: loop detection + token budget enforcement.

    Delegates detection to the existing ``LoopDetectionMiddleware._track_and_check``
    and ``TokenBudgetMiddleware._apply`` implementations (instantiated as
    stateless strategy objects), but shares a single ``wrap_model_call`` hook
    and warning-drain lifecycle.
    """

    def __init__(
        self,
        loop_config: LoopDetectionConfig,
        budget_config: TokenBudgetConfig,
    ) -> None:
        super().__init__()
        self._loop = LoopDetectionMiddleware.from_config(loop_config) if loop_config.enabled else None
        self._budget = TokenBudgetMiddleware.from_config(budget_config) if budget_config.enabled else None
        self._lock = threading.Lock()
        # Shared pending-warning queue: keyed by (thread_id, run_id)
        self._pending_warnings: dict[tuple[str, str], list[str]] = defaultdict(list)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        if self._loop:
            self._loop.before_agent(state, runtime)
        if self._budget:
            self._budget.before_agent(state, runtime)
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self.before_agent(state, runtime)
        return None

    def _get_pending_key(self, runtime: Runtime) -> tuple[str, str]:
        """Stable key for per-(thread, run) warning isolation."""
        thread_id = "default"
        run_id = "default"
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict):
            thread_id = str(ctx.get("thread_id", "default"))
            run_id = str(ctx.get("run_id", "default"))
        return (thread_id, run_id)

    def _queue_warning(self, runtime: Runtime, warning: str) -> None:
        key = self._get_pending_key(runtime)
        with self._lock:
            queue = self._pending_warnings[key]
            if warning not in queue:
                queue.append(warning)
                if len(queue) > _MAX_PENDING_WARNINGS:
                    del queue[: len(queue) - _MAX_PENDING_WARNINGS]

    def _drain_warnings(self, runtime: Runtime) -> list[str]:
        key = self._get_pending_key(runtime)
        with self._lock:
            return self._pending_warnings.pop(key, [])

    def _clear_stale_warnings(self, runtime: Runtime) -> None:
        """Drop pending warnings owned by previous runs in this thread."""
        thread_id, current_run_id = self._get_pending_key(runtime)
        with self._lock:
            for key in list(self._pending_warnings):
                if key[0] == thread_id and key[1] != current_run_id:
                    self._pending_warnings.pop(key, None)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        # ── Layer 1: loop detection (hash-based + frequency) ──────────
        if self._loop:
            warning, hard_stop = self._loop._track_and_check(state, runtime)
            if hard_stop:
                return self._loop._apply(state, runtime)
            if warning:
                self._queue_warning(runtime, warning)
                return None

        # ── Layer 2: token budget ────────────────────────────────────
        if self._budget:
            result = self._budget._apply(state, runtime)
            if result is not None:
                return result

        return None

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        if self._loop:
            self._loop._clear_current_run_pending_warnings(runtime)
        if self._budget:
            self._budget._clear_run_state(self._budget._get_run_id(runtime))
        # Shared drain
        self._drain_warnings(runtime)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> None:
        self.after_agent(state, runtime)

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        """Inject queued warnings (loop + budget) before the model call."""
        warnings = self._drain_warnings(request.runtime)
        if not warnings:
            return request
        loop_warnings = [w for w in warnings if w.startswith("[LOOP") or w.startswith("[FORCED")]
        budget_warnings = [w for w in warnings if w.startswith("[TOKEN")]
        merged = "\n\n".join(loop_warnings + budget_warnings)
        new_messages = [
            *request.messages,
            HumanMessage(content=merged, name="resource_warning"),
        ]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._augment_request(request))

    def reset(self, thread_id: str | None = None) -> None:
        if self._loop:
            self._loop.reset(thread_id)
        if self._budget:
            self._budget.reset()
        with self._lock:
            if thread_id:
                for key in list(self._pending_warnings):
                    if key[0] == thread_id:
                        self._pending_warnings.pop(key, None)
            else:
                self._pending_warnings.clear()
