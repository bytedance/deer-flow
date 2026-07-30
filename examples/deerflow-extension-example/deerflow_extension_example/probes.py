"""Four middlewares, declared at four placements.

They are paired on purpose, because the pairs are what make the placement
contract visible in the output:

* ``MODEL_LOGICAL`` vs ``MODEL_PHYSICAL`` -- one logical decision may cost
  several physical provider calls. The difference in ``/stats`` *is* the host's
  retry behaviour, observed rather than assumed.
* ``TOOL_RAW`` vs ``TOOL_VISIBLE`` -- the host truncates and sanitizes tool
  output before the model sees it. The difference in characters is that
  processing, measured from both ends of the same call.

``Placement.STANDARD`` is deliberately unused here. Reach for it only when your
middleware has no before/after-processing requirement at all; declaring a real
placement you do not need over-constrains the host for nothing.

Every probe degrades to a plain pass-through when there is no task store: a
subagent invoked directly has no complete parent-task identity, so the host
gives it no task scope. That is a documented state, not an error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    MiddlewarePlacement,
    Placement,
    task_store_from_runtime,
)
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow_extension_example.stats import StatsAccess, TaskRecord

#: Only the async hooks are implemented. Both the Gateway runtime and the
#: subagent executor drive the graph asynchronously, and the host's isolation
#: wrapper mirrors exactly the hooks a middleware overrides -- adding unused
#: sync variants would bolt no-op nodes onto the graph for nothing.


def _record(request: Any) -> TaskRecord | None:
    """The current task's record, or None when there is no live task scope."""
    task_store = task_store_from_runtime(getattr(request, "runtime", None))
    if task_store is None:
        return None
    return task_store.get(TaskRecord)


def _tool_name(request: ToolCallRequest) -> str:
    tool_call = getattr(request, "tool_call", None) or {}
    name = tool_call.get("name") if isinstance(tool_call, dict) else None
    return name or "<unknown>"


def _content_chars(message: Any) -> int:
    """Length of one message's text content, whatever shape the content takes."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(part) if isinstance(part, str) else len(str(part.get("text", ""))) if isinstance(part, dict) else 0 for part in content)
    return 0


def _result_chars(result: ToolMessage | Command) -> int:
    """Length of a tool result's text content.

    **A tool result is not always a ToolMessage by the time you see it.** The
    contract types this return as ``ToolMessage | Command``, and which one you
    actually get depends on your placement: the host's ``SandboxMiddleware``
    sits in the middle of the tool chain and rewraps a ``ToolMessage`` into
    ``Command(update={"sandbox": ..., "messages": [msg]})`` so the sandbox id
    reaches state. Anything placed *outer* of it — including ``TOOL_VISIBLE`` —
    therefore observes a ``Command`` carrying the real result inside, while
    ``TOOL_RAW`` still sees the bare ``ToolMessage``.

    So the wrapper has to be unwrapped, or the two ends of the tool axis
    silently measure different things and the pair stops being comparable. A
    ``Command`` with no messages really is pure control flow and measures zero.
    """
    content = getattr(result, "content", None)
    if isinstance(content, str | list):
        return _content_chars(result)
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages")
        if isinstance(messages, list):
            return sum(_content_chars(message) for message in messages)
    return 0


class LogicalModelProbe(AgentMiddleware):
    """Counts model *decisions*, outer of the host's retry and error handling."""

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        record = _record(request)
        if record is not None:
            # Counted before the call: a decision the provider ultimately failed
            # to serve is still a decision the agent made.
            record.note_logical_model_call()
        return await handler(request)


class PhysicalModelProbe(AgentMiddleware):
    """Counts and times *provider calls*, inner of every request transform."""

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        record = _record(request)
        started = perf_counter()
        try:
            return await handler(request)
        finally:
            # `finally`, so a failed attempt still counts as an attempt -- and so
            # the exception keeps propagating untouched. Observation must never
            # change the run's outcome.
            if record is not None:
                record.note_physical_model_call(perf_counter() - started)


class VisibleToolProbe(AgentMiddleware):
    """Observes what the model finally sees, outer of truncation/sanitization."""

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        result = await handler(request)
        record = _record(request)
        if record is not None:
            record.note_visible_tool_result(_tool_name(request), _result_chars(result))
        return result


class RawToolProbe(AgentMiddleware):
    """Observes the tool's own return, adjacent to the callable boundary."""

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        result = await handler(request)
        record = _record(request)
        if record is not None:
            record.note_raw_tool_result(_result_chars(result))
        return result


def _scope_label(scope: AgentScope) -> str:
    return scope.name.lower() if scope.name else str(scope)


@dataclass(frozen=True)
class ProbeContributor:
    """Decides what to contribute to one agent build.

    Note what this does *not* do: it never checks ``ctx.scope`` to decide
    whether to return the tool probes. Scope is declared on the contribution
    and the host filters -- hand-filtering here would duplicate the host's rule
    and drift from it.
    """

    access: StatsAccess

    def contribute_middlewares(self, app_store: ExtensionData, ctx: AgentBuildContext) -> Sequence[MiddlewarePlacement]:
        self.access.of(app_store).note_agent_build(
            _scope_label(ctx.scope),
            ctx.model_name,
            ctx.policy.max_subagents_per_run,
        )
        return (
            MiddlewarePlacement(LogicalModelProbe(), Placement.MODEL_LOGICAL, AgentScope.BOTH),
            MiddlewarePlacement(PhysicalModelProbe(), Placement.MODEL_PHYSICAL, AgentScope.BOTH),
            # Tool observation is scoped to the lead agent: subagents run their
            # own tool loops, and folding those into the same totals would make
            # "what the model saw" ambiguous about *which* model.
            MiddlewarePlacement(VisibleToolProbe(), Placement.TOOL_VISIBLE, AgentScope.LEAD),
            MiddlewarePlacement(RawToolProbe(), Placement.TOOL_RAW, AgentScope.LEAD),
        )
