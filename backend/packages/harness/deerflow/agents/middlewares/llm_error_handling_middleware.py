"""LLM error handling middleware with retry/backoff and user-facing fallbacks."""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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

# Provider burst-rate (``limit_burst_rate``) signals. This is a *rate-of-change*
# limit, not a quota limit: the provider throttles when request RPM ramps up too
# steeply (e.g. the 08:30 morning peak going 0 -> full throttle in seconds).
# Matched against both the error message and the error ``code``/``type``.
_BURST_PATTERNS = (
    "limit_burst_rate",
    "rate increased too quickly",
    "burst rate",
    "请求速率增长过快",
    "突发速率",
)

# Per-exception retry budget overrides.
#
# Some transient errors are retriable in principle but expensive to retry at
# the default budget. StreamChunkTimeoutError in particular fires after the
# upstream provider has already stalled for `stream_chunk_timeout` seconds
# (typically 120-240s); a full 3-attempt loop can therefore stack 6-12 minutes
# of dead air before surfacing the failure to the user. We keep exactly one
# retry (cheap reconnect that catches genuine transient TCP blips) and then
# fail fast — the same buffered payload is overwhelmingly likely to fail
# again at the upstream provider for the same reason.
#
# Keys are exception class *names* (not classes) so we don't introduce
# import-time coupling on optional dependencies like langchain-openai. The
# value is the absolute max attempt count, NOT additional retries — so a
# value of 2 means "1 first attempt + 1 retry" (the CR-requested
# "keep one retry" behavior).
_RETRY_BUDGET_OVERRIDES: dict[str, int] = {
    "StreamChunkTimeoutError": 2,
}

# Per-reason retry budget overrides, applied in addition to the per-exception
# overrides above; the tightest bound wins (so neither loosens the other) and
# the user-configured ``retry_max_attempts`` still caps everything.
#
# A burst-rate (``limit_burst_rate``) 429 gets a tight budget on purpose:
# retrying into the burst adds demand to the very request-rate slope being
# throttled, so we keep at most one retry (with a longer backoff) and then shed
# load rather than hammering the provider. Keys are ``_classify_error`` reasons.
_REASON_RETRY_BUDGETS: dict[str, int] = {
    "burst_rate": 2,
}

# Exception class names that indicate the upstream stream-chunk watchdog
# fired because the model stalled mid-flight. These deserve a more specific
# user-facing message than the generic "temporarily unavailable" copy,
# because the typical root cause is a long tool-call serialization stalling
# the upstream stream — and the most actionable advice we can give the user
# is "ask for a shorter / split output" rather than "wait and retry".
# Generic connection drops (httpx RemoteProtocolError / ReadError) are
# intentionally excluded: they routinely fire on transient network blips
# with normal payloads, where the "split the work" guidance is misleading.
_STREAM_DROP_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "StreamChunkTimeoutError",
    }
)


# Process-global LLM concurrency cap. A single ``asyncio.Semaphore`` shared
# across every ``LLMErrorHandlingMiddleware`` instance bounds the number of
# in-flight model calls process-wide. This is the lever for smoothing a
# provider burst-rate (``limit_burst_rate``) spike: that limit fires on the
# *slope* of the request rate, so capping aggregate concurrency caps that
# slope. Lazily (re)created per running event loop so it survives the
# loop-per-call pattern used by ``asyncio.run`` in tests; in production there
# is one long-lived loop, so the semaphore is created exactly once.


@dataclass
class _ConcurrencyState:
    """Mutable holder for the process-global LLM-call semaphore.

    Encapsulating (semaphore, loop, limit) in a single instance - instead of
    three bare module-level globals - keeps the recreate condition and the
    state it reads co-located. The semaphore is (re)created when the running
    event loop changes or the configured limit changes, so a fresh loop never
    reuses a semaphore bound to a closed loop.
    """

    semaphore: asyncio.Semaphore | None = None
    loop: asyncio.AbstractEventLoop | None = None
    limit: int = 0


_GLOBAL_CONCURRENCY_STATE = _ConcurrencyState()


def _get_global_concurrency_semaphore(limit: int) -> asyncio.Semaphore | None:
    """Return the process-global LLM-call semaphore, or ``None`` when disabled.

    ``limit <= 0`` disables the cap (callers run unbounded, preserving the
    default behavior). Otherwise the semaphore is (re)created when the running
    event loop changes or the configured limit changes, so a fresh loop (e.g. a
    new ``asyncio.run`` in tests) never reuses a semaphore bound to a closed
    loop.
    """
    if limit <= 0:
        return None
    loop = asyncio.get_running_loop()
    state = _GLOBAL_CONCURRENCY_STATE
    if state.semaphore is None or state.loop is not loop or state.limit != limit:
        state.semaphore = asyncio.Semaphore(limit)
        state.loop = loop
        state.limit = limit
    return state.semaphore


class LLMErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Retry transient LLM errors and surface graceful assistant messages."""

    retry_max_attempts: int = 3
    retry_base_delay_ms: int = 1000
    retry_cap_delay_ms: int = 8000
    # Longer backoff base used only for burst-rate (limit_burst_rate) 429s, so
    # the single burst retry lands after the throttle window subsides.
    burst_retry_base_delay_ms: int = 5000
    # Process-wide cap on concurrently in-flight LLM calls. 0 disables the cap
    # (default) so existing deployments see no behavior change; set to a
    # positive int to bound aggregate concurrency and smooth provider
    # burst-rate (limit_burst_rate) spikes. See _get_global_concurrency_semaphore.
    max_concurrent_llm_calls: int = 0

    def __init__(self, *, app_config: AppConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.circuit_failure_threshold = app_config.circuit_breaker.failure_threshold
        self.circuit_recovery_timeout_sec = app_config.circuit_breaker.recovery_timeout_sec

        # Retry / backoff / concurrency knobs are all configured via the
        # ``llm_call`` section of config.yaml; they override the class defaults
        # above so operators can tune them without code changes.
        llm_call = app_config.llm_call
        self.retry_max_attempts = llm_call.retry_max_attempts
        self.retry_base_delay_ms = llm_call.retry_base_delay_ms
        self.retry_cap_delay_ms = llm_call.retry_cap_delay_ms
        self.burst_retry_base_delay_ms = llm_call.burst_retry_base_delay_ms
        self.max_concurrent_llm_calls = llm_call.max_concurrent_calls

        # Circuit Breaker state
        self._circuit_lock = threading.Lock()
        self._circuit_failure_count = 0
        self._circuit_open_until = 0.0
        self._circuit_state = "closed"
        self._circuit_probe_in_flight = False

    def _max_attempts_for(self, exc: BaseException, reason: str = "transient") -> int:
        """Return the effective max attempt count for this exception.

        The user-configured ``retry_max_attempts`` is the ceiling; per-exception
        (``_RETRY_BUDGET_OVERRIDES``, keyed by class name) and per-reason
        (``_REASON_RETRY_BUDGETS``, keyed by ``_classify_error`` reason)
        overrides can only *tighten* it. The tightest bound wins, so a burst-rate
        429 never gets more attempts than its dedicated budget even if the
        operator raised the global cap.
        """
        candidates = [self.retry_max_attempts]
        class_override = _RETRY_BUDGET_OVERRIDES.get(type(exc).__name__)
        if class_override is not None:
            candidates.append(class_override)
        reason_override = _REASON_RETRY_BUDGETS.get(reason)
        if reason_override is not None:
            candidates.append(reason_override)
        return min(candidates)

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

    def _release_half_open_probe(self) -> None:
        """Release the in-flight half-open probe without recording a failure.

        Used when something other than a classified success/failure consumes the probe (a
        GraphBubbleUp control-flow signal, or a non-retriable error), so the circuit can admit
        the next probe instead of fast-failing forever.
        """
        with self._circuit_lock:
            if self._circuit_state == "half_open":
                self._circuit_probe_in_flight = False

    def _classify_error(self, exc: BaseException) -> tuple[bool, str]:
        detail = _extract_error_detail(exc)
        lowered = detail.lower()
        error_code = _extract_error_code(exc)
        status_code = _extract_status_code(exc)

        if _matches_any(lowered, _QUOTA_PATTERNS) or _matches_any(str(error_code).lower(), _QUOTA_PATTERNS):
            return False, "quota"
        if _matches_any(lowered, _AUTH_PATTERNS):
            return False, "auth"
        # Burst-rate (limit_burst_rate) 429 is retriable but needs its own
        # policy: a tight retry budget and a longer backoff base (see
        # _REASON_RETRY_BUDGETS / _build_retry_delay_ms). Detected before the
        # generic 429->transient mapping so it isn't lumped in with ordinary
        # transient errors.
        if _matches_any(lowered, _BURST_PATTERNS) or _matches_any(str(error_code).lower(), _BURST_PATTERNS):
            return True, "burst_rate"

        exc_name = exc.__class__.__name__
        if exc_name in {
            "APITimeoutError",
            "APIConnectionError",
            "InternalServerError",
            "ReadError",  # httpx.ReadError: connection dropped mid-stream
            "RemoteProtocolError",  # httpx: server closed connection unexpectedly
            "StreamChunkTimeoutError",  # langchain-openai: chunk gap exceeded stream_chunk_timeout
        }:
            return True, "transient"
        # Upstream sometimes returns ``200 OK`` with an empty
        # ``generations`` list (observed against Volces "coding" /
        # ark.cn-beijing.volces.com). ``langchain_core.language_models.
        # chat_models.ainvoke`` then crashes with
        # ``IndexError: list index out of range`` at
        # ``llm_result.generations[0][0].message``. That isn't really a
        # client bug — it's a transient upstream-payload glitch — so we
        # route it through the same retry/backoff path as other transient
        # provider failures rather than failing the whole run.
        if isinstance(exc, IndexError):
            return True, "transient"
        if status_code in _RETRIABLE_STATUS_CODES:
            return True, "transient"
        if _matches_any(lowered, _BUSY_PATTERNS):
            return True, "busy"

        return False, "generic"

    async def _bounded_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Run one model attempt under the process-global concurrency cap.

        The semaphore wraps a *single* attempt only, not the whole retry loop,
        so backoff sleeps release the slot for other callers - we bound
        in-flight requests, not waiting ones. When the cap is disabled
        (``max_concurrent_llm_calls <= 0``) this is a direct passthrough.
        """
        semaphore = _get_global_concurrency_semaphore(self.max_concurrent_llm_calls)
        if semaphore is None:
            return await handler(request)
        async with semaphore:
            return await handler(request)

    def _build_retry_delay_ms(self, prev_delay_ms: int, exc: BaseException, reason: str = "transient") -> int:
        """Compute the next retry delay (ms) using decorrelated jitter.

        An explicit ``Retry-After`` from the provider is honored as-is (no
        jitter) - the server told us exactly when to come back, and for a
        burst-rate 429 this is strongly preferred over any computed delay.
        Otherwise AWS-style "decorrelated jitter" is applied:
        ``delay = min(cap, random(base, prev * 3))``, seeded with the base on
        the first retry. ``reason="burst_rate"`` swaps in
        ``burst_retry_base_delay_ms`` (longer than the normal base) so the
        single burst retry lands after the throttle window subsides.

        Deterministic exponential backoff (``base * 2^(attempt-1)``) makes
        every concurrent retryer realign on the same backoff ticks; when a
        whole fleet fails at once (e.g. a provider burst-rate limit at the
        morning peak) that synchronized retry storm re-triggers the very limit
        we are backing off from. Decorrelated jitter spreads those retries
        across a random window so they don't re-peak in lockstep.
        """
        retry_after = _extract_retry_after_ms(exc)
        if retry_after is not None:
            return retry_after
        base = self.burst_retry_base_delay_ms if reason == "burst_rate" else self.retry_base_delay_ms
        cap = self.retry_cap_delay_ms
        high = max(base, prev_delay_ms * 3)
        delay = random.randint(base, high)
        return min(delay, cap)

    def _build_retry_message(self, attempt: int, wait_ms: int, reason: str) -> str:
        seconds = max(1, round(wait_ms / 1000))
        reason_text = {
            "busy": "provider is busy",
            "burst_rate": "provider is throttling request burst rate",
        }.get(reason, "provider request failed temporarily")
        return f"LLM request retry {attempt}/{self.retry_max_attempts}: {reason_text}. Retrying in {seconds}s."

    def _build_circuit_breaker_message(self) -> str:
        return "The configured LLM provider is currently unavailable due to continuous failures. Circuit breaker is engaged to protect the system. Please wait a moment before trying again."

    def _build_error_fallback_message(
        self,
        content: str,
        *,
        error_type: str,
        reason: str,
        detail: str,
    ) -> AIMessage:
        return AIMessage(
            content=content,
            additional_kwargs={
                "deerflow_error_fallback": True,
                "error_type": error_type,
                "error_reason": reason,
                "error_detail": detail,
            },
        )

    def _build_user_message(self, exc: BaseException, reason: str) -> str:
        detail = _extract_error_detail(exc)
        if reason == "quota":
            return "The configured LLM provider rejected the request because the account is out of quota, billing is unavailable, or usage is restricted. Please fix the provider account and try again."
        if reason == "auth":
            return "The configured LLM provider rejected the request because authentication or access is invalid. Please check the provider credentials and try again."
        if reason == "burst_rate":
            return "The configured LLM provider is temporarily throttling requests because the request rate increased too quickly (burst-rate limit). Please wait a moment and try again."
        if reason in {"busy", "transient"}:
            # Stream-drop failures (chunk-gap timeout, peer-closed connection,
            # raw read error) almost always point at a single oversized
            # tool-call payload — the model spent so long serializing JSON
            # arguments that the upstream provider buffered and the stream
            # gap exceeded `stream_chunk_timeout`. Surfacing this distinct
            # cause lets the user split or shorten their next request
            # instead of helplessly retrying the same prompt.
            if type(exc).__name__ in _STREAM_DROP_EXCEPTIONS:
                return (
                    "The model's streaming response was interrupted before it could "
                    "finish. This usually happens when a single response or tool call "
                    "is very large — please ask the assistant to split the work into "
                    "smaller steps, or shorten the requested output, and try again."
                )
            return "The configured LLM provider is temporarily unavailable after multiple retries. Please wait a moment and continue the conversation."
        return f"LLM request failed: {detail}"

    def _build_user_fallback_message(self, exc: BaseException, reason: str) -> AIMessage:
        return self._build_error_fallback_message(
            self._build_user_message(exc, reason),
            error_type=type(exc).__name__,
            reason=reason,
            detail=_extract_error_detail(exc),
        )

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
        if self._check_circuit():
            return self._build_error_fallback_message(
                self._build_circuit_breaker_message(),
                error_type="CircuitBreakerOpen",
                reason="circuit_open",
                detail="LLM circuit breaker is open",
            )

        attempt = 1
        prev_delay_ms = self.retry_base_delay_ms
        while True:
            try:
                response = handler(request)
                self._record_success()
                return response
            except GraphBubbleUp:
                # Preserve LangGraph control-flow signals (interrupt/pause/resume).
                self._release_half_open_probe()
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                max_attempts = self._max_attempts_for(exc, reason)
                if retriable and attempt < max_attempts:
                    wait_ms = self._build_retry_delay_ms(prev_delay_ms, exc, reason)
                    prev_delay_ms = wait_ms
                    logger.warning(
                        "Transient LLM error on attempt %d/%d; retrying in %dms: %s",
                        attempt,
                        self.retry_max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._emit_retry_event(attempt, wait_ms, reason)
                    time.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                else:
                    # Non-retriable: release the probe without recording a failure.
                    self._release_half_open_probe()
                return self._build_user_fallback_message(exc, reason)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        if self._check_circuit():
            return self._build_error_fallback_message(
                self._build_circuit_breaker_message(),
                error_type="CircuitBreakerOpen",
                reason="circuit_open",
                detail="LLM circuit breaker is open",
            )

        attempt = 1
        prev_delay_ms = self.retry_base_delay_ms
        while True:
            try:
                response = await self._bounded_model_call(request, handler)
                self._record_success()
                return response
            except GraphBubbleUp:
                # Preserve LangGraph control-flow signals (interrupt/pause/resume).
                self._release_half_open_probe()
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                max_attempts = self._max_attempts_for(exc, reason)
                if retriable and attempt < max_attempts:
                    wait_ms = self._build_retry_delay_ms(prev_delay_ms, exc, reason)
                    prev_delay_ms = wait_ms
                    logger.warning(
                        "Transient LLM error on attempt %d/%d; retrying in %dms: %s",
                        attempt,
                        self.retry_max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._emit_retry_event(attempt, wait_ms, reason)
                    await asyncio.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                else:
                    # Non-retriable: release the probe without recording a failure.
                    self._release_half_open_probe()
                return self._build_user_fallback_message(exc, reason)


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
