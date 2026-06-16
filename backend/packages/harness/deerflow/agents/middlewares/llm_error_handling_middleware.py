"""LLM error handling middleware with retry/backoff and user-facing fallbacks."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_RETRIABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_BUSY_PATTERNS = (
    "server busy",
    "temporarily unavailable",
    "try again later",
    "please retry",
    "please try again",
    "overloaded",
    "high demand",
    "rate limit",
    "负载较高",
    "服务繁忙",
    "稍后重试",
    "请稍后重试",
)
_QUOTA_PATTERNS = (
    "insufficient_quota",
    "quota",
    "billing",
    "credit",
    "payment",
    "余额不足",
    "超出限额",
    "额度不足",
    "欠费",
)
_AUTH_PATTERNS = (
    "authentication",
    "unauthorized",
    "invalid api key",
    "invalid_api_key",
    "permission",
    "forbidden",
    "access denied",
    "无权",
    "未授权",
)


def _request_log_context(request: ModelRequest) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    runtime_context = getattr(runtime, "context", None)
    runtime_context = runtime_context if isinstance(runtime_context, dict) else {}
    config = getattr(request, "config", None)
    config = config if isinstance(config, dict) else {}
    configurable = config.get("configurable", {})
    configurable = configurable if isinstance(configurable, dict) else {}
    model = getattr(request, "model", None)
    tools = getattr(request, "tools", None)
    messages = getattr(request, "messages", None)
    return {
        "pid": os.getpid(),
        "run_id": runtime_context.get("run_id") or configurable.get("run_id") or "-",
        "thread_id": runtime_context.get("thread_id") or configurable.get("thread_id") or "-",
        "agent_name": runtime_context.get("agent_name") or configurable.get("agent_name") or "-",
        "model_type": type(model).__name__ if model is not None else "-",
        "tools_count": len(tools) if isinstance(tools, list) else 0,
        "messages_count": len(messages) if isinstance(messages, list) else 0,
    }


class LLMErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Retry transient LLM errors and surface graceful assistant messages."""

    retry_max_attempts: int = 3
    retry_base_delay_ms: int = 1000
    retry_cap_delay_ms: int = 8000

    def __init__(self, *, app_config: AppConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.circuit_failure_threshold = app_config.circuit_breaker.failure_threshold
        self.circuit_recovery_timeout_sec = app_config.circuit_breaker.recovery_timeout_sec

        # Circuit Breaker state
        self._circuit_lock = threading.Lock()
        self._circuit_failure_count = 0
        self._circuit_open_until = 0.0
        self._circuit_state = "closed"
        self._circuit_probe_in_flight = False

    def _check_circuit(self) -> bool:
        """Returns True if circuit is OPEN (fast fail), False otherwise."""
        with self._circuit_lock:
            now = time.time()

            if self._circuit_state == "open":
                if now < self._circuit_open_until:
                    return True
                self._circuit_state = "half_open"
                self._circuit_probe_in_flight = False

            if self._circuit_state == "half_open":
                if self._circuit_probe_in_flight:
                    return True
                self._circuit_probe_in_flight = True
                return False

            return False

    def _record_success(self) -> None:
        with self._circuit_lock:
            if self._circuit_state != "closed" or self._circuit_failure_count > 0:
                logger.info("Circuit breaker reset (Closed). LLM service recovered.")
            self._circuit_failure_count = 0
            self._circuit_open_until = 0.0
            self._circuit_state = "closed"
            self._circuit_probe_in_flight = False

    def _record_failure(self) -> None:
        with self._circuit_lock:
            if self._circuit_state == "half_open":
                self._circuit_open_until = time.time() + self.circuit_recovery_timeout_sec
                self._circuit_state = "open"
                self._circuit_probe_in_flight = False
                logger.error(
                    "Circuit breaker probe failed (Open). Will probe again after %ds.",
                    self.circuit_recovery_timeout_sec,
                )
                return

            self._circuit_failure_count += 1
            if self._circuit_failure_count >= self.circuit_failure_threshold:
                self._circuit_open_until = time.time() + self.circuit_recovery_timeout_sec
                if self._circuit_state != "open":
                    self._circuit_state = "open"
                    self._circuit_probe_in_flight = False
                    logger.error(
                        "Circuit breaker tripped (Open). Threshold reached (%d). Will probe after %ds.",
                        self.circuit_failure_threshold,
                        self.circuit_recovery_timeout_sec,
                    )

    def _classify_error(self, exc: BaseException) -> tuple[bool, str]:
        detail = _extract_error_detail(exc)
        lowered = detail.lower()
        error_code = _extract_error_code(exc)
        status_code = _extract_status_code(exc)

        if _matches_any(lowered, _QUOTA_PATTERNS) or _matches_any(str(error_code).lower(), _QUOTA_PATTERNS):
            return False, "quota"
        if _matches_any(lowered, _AUTH_PATTERNS):
            return False, "auth"

        exc_name = exc.__class__.__name__
        if exc_name in {
            "APITimeoutError",
            "APIConnectionError",
            "InternalServerError",
            "ReadError",  # httpx.ReadError: connection dropped mid-stream
            "RemoteProtocolError",  # httpx: server closed connection unexpectedly
        }:
            return True, "transient"
        if status_code in _RETRIABLE_STATUS_CODES:
            return True, "transient"
        if _matches_any(lowered, _BUSY_PATTERNS):
            return True, "busy"

        return False, "generic"

    def _build_retry_delay_ms(self, attempt: int, exc: BaseException) -> int:
        retry_after = _extract_retry_after_ms(exc)
        if retry_after is not None:
            return retry_after
        backoff = self.retry_base_delay_ms * (2 ** max(0, attempt - 1))
        return min(backoff, self.retry_cap_delay_ms)

    def _build_retry_message(self, attempt: int, wait_ms: int, reason: str) -> str:
        seconds = max(1, round(wait_ms / 1000))
        reason_text = "provider is busy" if reason == "busy" else "provider request failed temporarily"
        return f"LLM request retry {attempt}/{self.retry_max_attempts}: {reason_text}. Retrying in {seconds}s."

    def _build_circuit_breaker_message(self) -> str:
        return "The configured LLM provider is currently unavailable due to continuous failures. Circuit breaker is engaged to protect the system. Please wait a moment before trying again."

    def _build_user_message(self, exc: BaseException, reason: str) -> str:
        detail = _extract_error_detail(exc)
        if reason == "quota":
            return "The configured LLM provider rejected the request because the account is out of quota, billing is unavailable, or usage is restricted. Please fix the provider account and try again."
        if reason == "auth":
            return "The configured LLM provider rejected the request because authentication or access is invalid. Please check the provider credentials and try again."
        if reason in {"busy", "transient"}:
            return "The configured LLM provider is temporarily unavailable after multiple retries. Please wait a moment and continue the conversation."
        return f"LLM request failed: {detail}"

    def _emit_retry_event(self, attempt: int, wait_ms: int, reason: str) -> None:
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
            writer(
                {
                    "type": "llm_retry",
                    "attempt": attempt,
                    "max_attempts": self.retry_max_attempts,
                    "wait_ms": wait_ms,
                    "reason": reason,
                    "message": self._build_retry_message(attempt, wait_ms, reason),
                }
            )
        except Exception:
            logger.debug("Failed to emit llm_retry event", exc_info=True)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        log_ctx = _request_log_context(request)
        if self._check_circuit():
            logger.warning(
                "LLM call circuit-open: pid=%s run_id=%s thread_id=%s agent=%s model=%s tools=%s messages=%s",
                log_ctx["pid"],
                log_ctx["run_id"],
                log_ctx["thread_id"],
                log_ctx["agent_name"],
                log_ctx["model_type"],
                log_ctx["tools_count"],
                log_ctx["messages_count"],
            )
            return AIMessage(content=self._build_circuit_breaker_message())

        attempt = 1
        while True:
            attempt_start = time.monotonic()
            logger.info(
                "LLM call start attempt %d/%d: pid=%s run_id=%s thread_id=%s agent=%s model=%s tools=%s messages=%s",
                attempt,
                self.retry_max_attempts,
                log_ctx["pid"],
                log_ctx["run_id"],
                log_ctx["thread_id"],
                log_ctx["agent_name"],
                log_ctx["model_type"],
                log_ctx["tools_count"],
                log_ctx["messages_count"],
            )
            try:
                response = handler(request)
                self._record_success()
                logger.info(
                    "LLM call success attempt %d/%d: pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d",
                    attempt,
                    self.retry_max_attempts,
                    log_ctx["pid"],
                    log_ctx["run_id"],
                    log_ctx["thread_id"],
                    log_ctx["model_type"],
                    int((time.monotonic() - attempt_start) * 1000),
                )
                return response
            except GraphBubbleUp:
                # Preserve LangGraph control-flow signals (interrupt/pause/resume).
                with self._circuit_lock:
                    if self._circuit_state == "half_open":
                        self._circuit_probe_in_flight = False
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                if retriable and attempt < self.retry_max_attempts:
                    wait_ms = self._build_retry_delay_ms(attempt, exc)
                    logger.warning(
                        "Transient LLM error on attempt %d/%d: pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d; retrying in %dms: %s",
                        attempt,
                        self.retry_max_attempts,
                        log_ctx["pid"],
                        log_ctx["run_id"],
                        log_ctx["thread_id"],
                        log_ctx["model_type"],
                        int((time.monotonic() - attempt_start) * 1000),
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._emit_retry_event(attempt, wait_ms, reason)
                    time.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d error=%s",
                    attempt,
                    log_ctx["pid"],
                    log_ctx["run_id"],
                    log_ctx["thread_id"],
                    log_ctx["model_type"],
                    int((time.monotonic() - attempt_start) * 1000),
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                return AIMessage(content=self._build_user_message(exc, reason))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        log_ctx = _request_log_context(request)
        if self._check_circuit():
            logger.warning(
                "LLM call circuit-open: pid=%s run_id=%s thread_id=%s agent=%s model=%s tools=%s messages=%s",
                log_ctx["pid"],
                log_ctx["run_id"],
                log_ctx["thread_id"],
                log_ctx["agent_name"],
                log_ctx["model_type"],
                log_ctx["tools_count"],
                log_ctx["messages_count"],
            )
            return AIMessage(content=self._build_circuit_breaker_message())

        attempt = 1
        while True:
            attempt_start = time.monotonic()
            logger.info(
                "LLM call start attempt %d/%d: pid=%s run_id=%s thread_id=%s agent=%s model=%s tools=%s messages=%s",
                attempt,
                self.retry_max_attempts,
                log_ctx["pid"],
                log_ctx["run_id"],
                log_ctx["thread_id"],
                log_ctx["agent_name"],
                log_ctx["model_type"],
                log_ctx["tools_count"],
                log_ctx["messages_count"],
            )
            try:
                response = await handler(request)
                self._record_success()
                logger.info(
                    "LLM call success attempt %d/%d: pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d",
                    attempt,
                    self.retry_max_attempts,
                    log_ctx["pid"],
                    log_ctx["run_id"],
                    log_ctx["thread_id"],
                    log_ctx["model_type"],
                    int((time.monotonic() - attempt_start) * 1000),
                )
                return response
            except GraphBubbleUp:
                # Preserve LangGraph control-flow signals (interrupt/pause/resume).
                with self._circuit_lock:
                    if self._circuit_state == "half_open":
                        self._circuit_probe_in_flight = False
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                if retriable and attempt < self.retry_max_attempts:
                    wait_ms = self._build_retry_delay_ms(attempt, exc)
                    logger.warning(
                        "Transient LLM error on attempt %d/%d: pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d; retrying in %dms: %s",
                        attempt,
                        self.retry_max_attempts,
                        log_ctx["pid"],
                        log_ctx["run_id"],
                        log_ctx["thread_id"],
                        log_ctx["model_type"],
                        int((time.monotonic() - attempt_start) * 1000),
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._emit_retry_event(attempt, wait_ms, reason)
                    await asyncio.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): pid=%s run_id=%s thread_id=%s model=%s duration_ms=%d error=%s",
                    attempt,
                    log_ctx["pid"],
                    log_ctx["run_id"],
                    log_ctx["thread_id"],
                    log_ctx["model_type"],
                    int((time.monotonic() - attempt_start) * 1000),
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                return AIMessage(content=self._build_user_message(exc, reason))


def _matches_any(detail: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in detail for pattern in patterns)


def _extract_error_code(exc: BaseException) -> Any:
    for attr in ("code", "error_code"):
        value = getattr(exc, attr, None)
        if value not in (None, ""):
            return value

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("code", "type"):
                value = error.get(key)
                if value not in (None, ""):
                    return value
    return None


def _extract_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _extract_retry_after_ms(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    raw = None
    header_name = ""
    for key in ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After"):
        header_name = key
        if hasattr(headers, "get"):
            raw = headers.get(key)
        if raw:
            break
    if not raw:
        return None

    try:
        multiplier = 1 if "ms" in header_name.lower() else 1000
        return max(0, int(float(raw) * multiplier))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(raw))
            delta = target.timestamp() - time.time()
            return max(0, int(delta * 1000))
        except (TypeError, ValueError, OverflowError):
            return None


def _extract_error_detail(exc: BaseException) -> str:
    detail = str(exc).strip()
    if detail:
        return detail
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return exc.__class__.__name__
