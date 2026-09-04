"""Persist effective deferred-tool promotion decisions without sensitive payloads."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.middlewares.audit_context import TOOL_PROMOTION_RECORDER_CONTEXT_KEY
from deerflow.runtime.events.catalog import MIDDLEWARE_TOOL_PROMOTION_TAG

logger = logging.getLogger(__name__)

_TOOL_SEARCH_NAME = "tool_search"


def record_tool_promotion(
    runtime: Runtime | None,
    *,
    producer: str,
    hook: str,
    source: str,
    tool_names: Iterable[str],
) -> None:
    """Record one effective promotion decision, failing open on telemetry errors."""
    names = sorted(set(tool_names))
    if not names:
        return

    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return
    is_subagent = context.get("is_subagent") is True
    recorder = context.get(TOOL_PROMOTION_RECORDER_CONTEXT_KEY)
    if recorder is None:
        # Lead runs own a RunJournal. Ordinary task-tool subagents receive only
        # the narrow, loop-safe recorder key above.
        recorder = context.get("__run_journal")
    if recorder is None:
        return

    try:
        claim = getattr(recorder, "claim_tool_promotions", None)
        if callable(claim):
            names = claim(names)
        if not names:
            return
        recorder.record_middleware(
            tag=MIDDLEWARE_TOOL_PROMOTION_TAG,
            name=producer,
            hook=hook,
            action="promote",
            changes={
                "source": source,
                "tool_names": names,
                "count": len(names),
                "is_subagent": is_subagent,
                "agent_id": context.get("agent_id") if is_subagent else None,
            },
        )
    except Exception:  # noqa: BLE001
        # Observation must never alter the agent trajectory it describes.
        logger.warning("Failed to record middleware:tool_promotion event", exc_info=True)


class DeferredToolPromotionAuditMiddleware(AgentMiddleware[AgentState]):
    """Observe final ``tool_search`` Commands after policy filtering.

    This wrapper must remain outer of ``SkillToolPolicyMiddleware``. Tool-call
    wrappers unwind in reverse registration order, so observing the handler's
    final return value is what prevents denied schemas from being reported as
    effective promotions.
    """

    def __init__(self, deferred_names: frozenset[str], catalog_hash: str | None) -> None:
        super().__init__()
        self._deferred = deferred_names
        self._catalog_hash = catalog_hash

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "deferred_names": sorted(self._deferred),
            "catalog_hash": self._catalog_hash,
            "observation": "final_tool_search_command",
        }

    def _current_promoted(self, state: Mapping[str, Any] | None) -> set[str]:
        promoted = (state or {}).get("promoted")
        if not isinstance(promoted, Mapping) or promoted.get("catalog_hash") != self._catalog_hash:
            return set()
        names = promoted.get("names")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            return set()
        return set(names)

    def _new_promotions(self, request: ToolCallRequest, result: ToolMessage | Command) -> list[str]:
        if request.tool_call.get("name") != _TOOL_SEARCH_NAME:
            return []
        if not isinstance(result, Command) or not isinstance(result.update, dict):
            return []
        promoted = result.update.get("promoted")
        if not isinstance(promoted, dict) or promoted.get("catalog_hash") != self._catalog_hash:
            return []
        names = promoted.get("names")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            return []
        return sorted((set(names) & self._deferred) - self._current_promoted(request.state))

    def _record(self, request: ToolCallRequest, result: ToolMessage | Command) -> None:
        record_tool_promotion(
            request.runtime,
            producer=type(self).__name__,
            hook="wrap_tool_call",
            source="tool_search",
            tool_names=self._new_promotions(request, result),
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        self._record(request, result)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        self._record(request, result)
        return result
