"""Tool error handling middleware and shared runtime middleware builders."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"
_ERROR_PREFIX = "Error:"


def _classify_tool_error(text: str) -> dict[str, Any]:
    """Classify a tool-returned ``Error:`` string without parsing display text downstream."""
    normalized = text.lower()
    if any(token in normalized for token in ("401", "unauthorized", "authentication", "invalid api key", "api key")):
        return {"error_type": "auth", "retryable": False, "recoverable_by_model": False}
    if any(token in normalized for token in ("429", "rate limit", "rate limited", "timeout", "timed out", "connection", "network", "temporarily", "unavailable")):
        return {"error_type": "transient", "retryable": True, "recoverable_by_model": False}
    if any(token in normalized for token in ("not configured", "not installed", "missing required", "disabled", "configuration")):
        return {"error_type": "config", "retryable": False, "recoverable_by_model": False}
    if any(token in normalized for token in ("permission denied", "access denied", "path traversal", "not allowed", "forbidden")):
        return {"error_type": "permission", "retryable": False, "recoverable_by_model": True}
    if any(token in normalized for token in ("no results found", "no content found", "no images found")):
        return {"error_type": "no_results", "retryable": False, "recoverable_by_model": True}
    if any(token in normalized for token in ("not found", "no such file", "does not exist")):
        return {"error_type": "not_found", "retryable": False, "recoverable_by_model": True}
    if "unexpected" in normalized:
        return {"error_type": "internal", "retryable": False, "recoverable_by_model": False}
    return {"error_type": "unknown", "retryable": False, "recoverable_by_model": True}


def _normalizable_error_text(message: ToolMessage) -> str | None:
    content = message.content
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text.startswith(_ERROR_PREFIX):
        return None
    return text


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Convert tool exceptions into error ToolMessages so the run can continue."""

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. Continue with available context, or choose an alternative tool."
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    def _normalize_tool_message(self, message: ToolMessage) -> ToolMessage:
        text = _normalizable_error_text(message)
        if text is None:
            return message

        additional_kwargs = dict(message.additional_kwargs or {})
        additional_kwargs.setdefault(
            "deerflow_tool_error",
            {
                "source": "tool_return",
                **_classify_tool_error(text),
            },
        )
        return message.model_copy(
            update={
                "status": "error",
                "additional_kwargs": additional_kwargs,
            }
        )

    def _normalize_tool_result(self, result: ToolMessage | Command) -> ToolMessage | Command:
        if isinstance(result, ToolMessage):
            return self._normalize_tool_message(result)
        if not isinstance(result.update, dict):
            return result

        messages = result.update.get("messages")
        if not isinstance(messages, list):
            return result

        normalized_messages = [
            self._normalize_tool_message(message) if isinstance(message, ToolMessage) else message
            for message in messages
        ]
        if normalized_messages == messages:
            return result

        update = dict(result.update)
        update["messages"] = normalized_messages
        return replace(result, update=update)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return self._normalize_tool_result(handler(request))
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (sync): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return self._normalize_tool_result(await handler(request))
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (async): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)


def _build_runtime_middlewares(
    *,
    app_config: AppConfig,
    include_uploads: bool,
    include_dangling_tool_call_patch: bool,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    """Build shared base middlewares for agent execution."""
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.sandbox.middleware import SandboxMiddleware

    middlewares: list[AgentMiddleware] = [
        ThreadDataMiddleware(lazy_init=lazy_init),
        SandboxMiddleware(lazy_init=lazy_init),
    ]

    if include_uploads:
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

        middlewares.insert(1, UploadsMiddleware())

    if include_dangling_tool_call_patch:
        from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        middlewares.append(DanglingToolCallMiddleware())

    middlewares.append(LLMErrorHandlingMiddleware(app_config=app_config))

    # Guardrail middleware (if configured)
    guardrails_config = app_config.guardrails
    if guardrails_config.enabled and guardrails_config.provider:
        import inspect

        from deerflow.guardrails.middleware import GuardrailMiddleware
        from deerflow.reflection import resolve_variable

        provider_cls = resolve_variable(guardrails_config.provider.use)
        provider_kwargs = dict(guardrails_config.provider.config) if guardrails_config.provider.config else {}
        # Pass framework hint if the provider accepts it (e.g. for config discovery).
        # Built-in providers like AllowlistProvider don't need it, so only inject
        # when the constructor accepts 'framework' or '**kwargs'.
        if "framework" not in provider_kwargs:
            try:
                sig = inspect.signature(provider_cls.__init__)
                if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    provider_kwargs["framework"] = "deerflow"
            except (ValueError, TypeError):
                pass
        provider = provider_cls(**provider_kwargs)
        middlewares.append(GuardrailMiddleware(provider, fail_closed=guardrails_config.fail_closed, passport=guardrails_config.passport))

    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    middlewares.append(SandboxAuditMiddleware())
    middlewares.append(ToolErrorHandlingMiddleware())
    return middlewares


def build_lead_runtime_middlewares(*, app_config: AppConfig, lazy_init: bool = True) -> list[AgentMiddleware]:
    """Middlewares shared by lead agent runtime before lead-only middlewares."""
    return _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=True,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )


def build_subagent_runtime_middlewares(
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    """Middlewares shared by subagent runtime before subagent-only middlewares."""
    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()

    middlewares = _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=False,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )

    if model_name is None and app_config.models:
        model_name = app_config.models[0].name

    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        middlewares.append(ViewImageMiddleware())

    # Same provider safety-termination guard the lead agent uses — subagents
    # are equally exposed to truncated tool_calls returned with
    # finish_reason=content_filter (and friends), and the bad call would then
    # propagate back to the lead agent via the task tool result.
    safety_config = app_config.safety_finish_reason
    if safety_config.enabled:
        from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    return middlewares
