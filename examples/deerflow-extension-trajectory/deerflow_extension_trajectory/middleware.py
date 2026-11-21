"""Observe full model responses and independent tool invocations."""

import asyncio
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter_ns
from uuid import uuid4

from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from .timing import KEY

logger = logging.getLogger(__name__)
_tool_failure = ContextVar("trajectory_tool_failure", default=None)


def failure_kind(error):
    from httpx import TimeoutException
    from langgraph.errors import GraphBubbleUp

    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, GraphBubbleUp):
        return "interrupted"
    current, seen = error, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, TimeoutException)):
            return "timeout"
        current = current.__cause__ or current.__context__
    return "failed"


def messages_in(result):
    if isinstance(result, (AIMessage, ToolMessage)):
        return [result]
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages", [])
        return [messages] if isinstance(messages, ToolMessage) else list(messages)
    response = getattr(result, "model_response", result)
    return list(getattr(response, "result", []))


class ToolFailureObserver(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except BaseException as error:
            if (failure := _tool_failure.get()) is not None:
                failure.update(
                    outcome=failure_kind(error), error_type=type(error).__name__
                )
            raise

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except BaseException as error:
            if (failure := _tool_failure.get()) is not None:
                failure.update(
                    outcome=failure_kind(error), error_type=type(error).__name__
                )
            raise


class TimingMiddleware(AgentMiddleware):
    def __init__(
        self,
        repository,
        operation,
        model_name=None,
        clock=perf_counter_ns,
        is_subagent=False,
    ):
        self.repository = repository
        self.operation = operation
        self.model_name = model_name
        self.clock = clock
        self.is_subagent = is_subagent

    def _begin(self, request):
        from .gateway import timing_identity

        name = (
            request.tool_call.get("name")
            if self.operation == "tool"
            else self.model_name
        )
        record = {
            **timing_identity(request),
            "span_id": str(uuid4()),
            "operation": self.operation,
            "name": name or self.operation,
            "outcome": "completed",
            "error_type": None,
            "started_at": datetime.now(UTC).isoformat(),
            "measurement": "logical_response"
            if self.operation == "model"
            else "tool_visible",
        }
        # A child without persisted execution identity must not be mistaken
        # for a lead failure in the same thread.
        if self.is_subagent and not record.get("execution_id"):
            record["thread_id"] = None
        return record, self.clock()

    def _finish(self, record, start, result, error, failure):
        record["duration_ms"] = max(0, self.clock() - start) / 1_000_000
        record["ended_at"] = datetime.now(UTC).isoformat()
        messages = [
            message
            for message in messages_in(result)
            if isinstance(
                message, AIMessage if self.operation == "model" else ToolMessage
            )
        ]
        if error is not None:
            record.update(outcome=failure_kind(error), error_type=type(error).__name__)
        elif self.operation == "model":
            for message in messages:
                if message.additional_kwargs.get("deerflow_error_fallback") is True:
                    record.update(
                        outcome="failed",
                        error_type=message.additional_kwargs.get("error_type"),
                    )
                    break
        elif any(
            getattr(message, "status", None) == "error"
            or (message.additional_kwargs.get("deerflow_tool_meta") or {}).get("status")
            == "error"
            for message in messages
        ):
            record.update({"outcome": "failed", **(failure or {})})
        record["message_id"] = None
        record["has_output"] = bool(messages)
        for message in messages:
            record["message_id"] = record["message_id"] or message.id
            message.additional_kwargs = {
                **message.additional_kwargs,
                KEY: self.repository.options.project(record),
            }

    def _sync(self, request, handler):
        record, start = self._begin(request)
        result = error = None
        failure = {} if self.operation == "tool" else None
        token = _tool_failure.set(failure) if failure is not None else None
        try:
            result = handler(request)
            return result
        except BaseException as exc:
            error = exc
            raise
        finally:
            self._finish(record, start, result, error, failure)
            if token is not None:
                _tool_failure.reset(token)
            try:
                if record.get("thread_id"):
                    self.repository.append(record)
            except Exception:
                logger.warning("Could not persist trajectory timing", exc_info=True)

    async def _async(self, request, handler):
        record, start = self._begin(request)
        result = error = None
        failure = {} if self.operation == "tool" else None
        token = _tool_failure.set(failure) if failure is not None else None
        try:
            result = await handler(request)
            return result
        except BaseException as exc:
            error = exc
            raise
        finally:
            self._finish(record, start, result, error, failure)
            if token is not None:
                _tool_failure.reset(token)
            try:
                if record.get("thread_id"):
                    await self.repository.aappend(record)
            except Exception:
                logger.warning("Could not persist trajectory timing", exc_info=True)

    def wrap_model_call(self, request, handler):
        return self._sync(request, handler)

    async def awrap_model_call(self, request, handler):
        return await self._async(request, handler)

    def wrap_tool_call(self, request, handler):
        return self._sync(request, handler)

    async def awrap_tool_call(self, request, handler):
        return await self._async(request, handler)


class TimingContributor:
    def __init__(self, repository):
        self.repository = repository

    def contribute_middlewares(self, app_store, ctx):
        # Separate subclasses expose only the hook axis each placement permits.
        class ModelTiming(TimingMiddleware):
            wrap_tool_call = AgentMiddleware.wrap_tool_call
            awrap_tool_call = AgentMiddleware.awrap_tool_call

        class ToolTiming(TimingMiddleware):
            wrap_model_call = AgentMiddleware.wrap_model_call
            awrap_model_call = AgentMiddleware.awrap_model_call

        return (
            MiddlewarePlacement(
                ModelTiming(
                    self.repository,
                    "model",
                    ctx.model_name,
                    is_subagent=bool(ctx.scope & AgentScope.SUBAGENT),
                ),
                Placement.MODEL_LOGICAL,
                AgentScope.BOTH,
            ),
            MiddlewarePlacement(
                ToolTiming(
                    self.repository,
                    "tool",
                    is_subagent=bool(ctx.scope & AgentScope.SUBAGENT),
                ),
                Placement.TOOL_VISIBLE,
                AgentScope.BOTH,
            ),
            MiddlewarePlacement(
                ToolFailureObserver(), Placement.TOOL_RAW, AgentScope.BOTH
            ),
        )
