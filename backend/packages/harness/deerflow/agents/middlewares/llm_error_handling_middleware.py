"""LLM error handling middleware with retry/backoff and user-facing fallbacks."""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections import deque
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
from deerflow.utils.custom_events import aemit_custom_event, emit_custom_event

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


# Process-global LLM call concurrency cap. ONE limiter is shared across every
# ``LLMErrorHandlingMiddleware`` instance and every call path: the lead agent
# (main event loop), subagents (the isolated persistent loop in
# subagents/executor.py), ``asyncio.run`` tests, and the sync graph path. That
# matters because a provider burst-rate (``limit_burst_rate``) limit fires on
# the *slope* of the request rate, so the cap must bound aggregate in-flight
# calls process-wide - a per-loop cap (which is what asyncio.Semaphore would
# give) is defeated the moment subagent fan-out runs on a second loop.
#
# Correctness invariants the design below preserves:
#   * Lossless waiter handoff: a permit handed to a waiter is *reserved* for
#     that waiter at dequeue time (``granted=True``). If the waiter is
#     cancelled before it wakes, the reserved permit is re-handed to the next
#     waiter (or freed) - so a cancellation in the post-dequeue/pre-reacquire
#     window never strands the next waiter with capacity idle.
#   * Startup-only cap: the cap is resolved ONCE, at the first middleware
#     construction (``_apply_configured_cap``), and frozen thereafter. Later
#     ``__init__`` calls never touch the cap - whether they hold a newer or an
#     older ``AppConfig`` snapshot. This removes the pseudo-generation path
#     entirely: with no cap mutation at runtime there is no downscale that
#     could hand excess permits to queued waiters (keeping ``in_flight`` pegged
#     at the old cap), and no construction-order race where a stale config
#     constructed after a fresher one could restore a higher cap. Per-attempt
#     callers only acquire/release. Changing the cap requires a gateway
#     restart (see ``LlmCallConfig.max_concurrent_calls``).


class _AsyncWaiter:
    """A parked async caller awaiting a transferred permit.

    ``granted`` is flipped to ``True`` (under the limiter lock) at the exact
    moment a permit is reserved for this waiter - by ``release`` handing off a
    returning permit, or by another cancelling waiter handing off its reserved
    permit. The reservation is atomic with the dequeue, so the invariant
    ``granted is True  <=>  not in _async_waiters`` always holds: once granted,
    the permit is already counted in ``_in_flight`` and the waiter need only
    wake and return. A cancelled waiter therefore knows from ``granted``
    whether it owes a handoff (granted) or is merely unregistering (not yet
    granted).
    """

    __slots__ = ("loop", "event", "granted")

    def __init__(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        self.loop = loop
        self.event = event
        self.granted = False


class _ProcessWideLimiter:
    """In-flight call limiter shared across event loops and sync/async wrappers.

    ``asyncio.Semaphore`` binds to the first event loop that uses it and raises
    if acquired from another, so it cannot cap lead-agent and subagent calls
    together (they run on different loops), nor the sync graph path. This
    limiter is built on ``threading`` primitives (not loop-bound): every call
    path shares one in-flight counter and one cap.

    The cap is **immutable**: it is set once at construction (by
    ``_apply_configured_cap`` on the first middleware ``__init__``) and never
    mutated afterwards. Because the cap never changes at runtime there is no
    downscale race (a lowered cap could otherwise keep admitting queued
    waiters until ``in_flight`` drains) and no config-freshness race (a stale
    snapshot constructed later could otherwise restore a higher cap). Per-
    attempt callers (``acquire_sync``/``acquire_async``/``release``) never
    touch the cap. Permits are released in a ``finally`` and an async waiter
    that is cancelled after its permit was reserved hands the reservation to
    the next waiter, so capacity never leaks and a cancellation never strands
    a later waiter.
    """

    def __init__(self, limit: int) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._in_flight = 0
        self._limit = max(0, limit)
        # FIFO of async callers waiting on capacity. Each waiter lives on its
        # caller's loop; release/handoff wakes one across loops via
        # call_soon_threadsafe so the wakeup runs on the right loop.
        self._async_waiters: deque[_AsyncWaiter] = deque()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def acquire_sync(self) -> None:
        """Block the calling thread until a permit is available, then take one."""
        with self._cond:
            while not self._try_acquire_locked():
                self._cond.wait()

    def release(self) -> None:
        """Return one permit, handing it to a waiter if one is queued.

        If an async waiter is queued, the returning permit *transfers* to it
        (ownership moves; ``_in_flight`` is unchanged) and its event is set so
        it wakes already owning a permit. Otherwise the permit returns to the
        free pool (``_in_flight -= 1``) and one sync waiter is notified to grab
        it on its next ``_try_acquire_locked`` re-check.
        """
        with self._cond:
            if self._async_waiters:
                waiter = self._async_waiters.popleft()
                waiter.granted = True
                if not self._wake_locked(waiter):
                    # Owner loop closed: the transferred permit is stranded;
                    # hand it to the next waiter or free it.
                    self._handoff_granted_permit_locked()
                return
            if self._in_flight > 0:
                self._in_flight -= 1
            self._cond.notify()

    async def acquire_async(self) -> None:
        """Acquire a permit without blocking the event loop.

        Free capacity -> take one immediately. Otherwise park on an
        ``asyncio.Event``; ``release`` / a cap-raise transfers a permit to us
        (``granted=True``) and sets the event. On cancellation, if a permit was
        already reserved for us, hand it to the next waiter (or free it) so the
        reservation is never lost; if we were still queued (not yet granted),
        just unregister - no permit was reserved for us, so there is nothing to
        release.
        """
        loop = asyncio.get_running_loop()
        while True:
            waiter = _AsyncWaiter(loop=loop, event=asyncio.Event())
            with self._cond:
                if self._try_acquire_locked():
                    return
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "LLM call parking on process-wide limiter (in_flight=%d, limit=%d, queued=%d)",
                        self._in_flight,
                        self._limit,
                        len(self._async_waiters) + 1,
                    )
                self._async_waiters.append(waiter)
            try:
                await waiter.event.wait()
            except asyncio.CancelledError:
                with self._cond:
                    if waiter.granted:
                        # A permit was reserved for us but we're cancelling
                        # before waking. Pass the reservation to the next
                        # waiter (or free it) so it is not stranded.
                        self._handoff_granted_permit_locked()
                    else:
                        # Still queued, never granted (granted is set only when
                        # dequeued, under the lock): just unregister.
                        self._async_waiters.remove(waiter)
                raise
            return  # woken => granted => we own a permit (already in _in_flight)

    def _try_acquire_locked(self) -> bool:
        if self._in_flight < self._limit:
            self._in_flight += 1
            return True
        return False

    def _handoff_granted_permit_locked(self) -> None:
        """Transfer an already-reserved permit to the next queued waiter, or free it.

        Used when a waiter that had a permit reserved cancels before waking, or
        when a reservation target's loop is dead. The permit is already counted
        in ``_in_flight``; transferring keeps it counted (ownership moves to the
        next waiter), freeing returns it to the pool. Either way ``_in_flight``
        stays correct and the reservation is never lost.
        """
        while self._async_waiters:
            waiter = self._async_waiters.popleft()
            waiter.granted = True
            if self._wake_locked(waiter):
                return  # ownership transferred; _in_flight unchanged
            # dead loop; try the next waiter
        # No async waiter to take it: free the permit and wake a sync waiter.
        if self._in_flight > 0:
            self._in_flight -= 1
        self._cond.notify()

    def _wake_locked(self, waiter: _AsyncWaiter) -> bool:
        """Schedule ``event.set`` on the waiter's loop. False if the loop is dead."""
        try:
            waiter.loop.call_soon_threadsafe(waiter.event.set)
            return True
        except RuntimeError:
            return False  # owner loop closed: the wakeup cannot land


_LIMITER_LOCK = threading.Lock()
_PROCESS_LIMITER: _ProcessWideLimiter | None = None

# Whether the process-wide cap has been resolved yet. The cap is startup-only:
# the first ``LLMErrorHandlingMiddleware`` ``__init__`` resolves it (creating a
# limiter for a positive cap, or leaving it ``None`` for a disabled cap) and
# every subsequent ``__init__`` is a no-op - regardless of whether its
# ``AppConfig`` snapshot is newer or older than the first. This is the single
# owner of the cap; per-attempt callers only acquire/release.
_CAP_RESOLVED: bool = False


def _get_process_limiter() -> _ProcessWideLimiter | None:
    """Return the process-wide LLM-call limiter, or ``None`` when the cap is
    disabled (or before the first middleware construction resolves it).

    Per-attempt callers use this to acquire/release only - it never changes the
    cap. ``limiter is None`` is the sole gate for "cap disabled": a per-call
    short-circuit on the instance's configured value would let a later
    (reloaded) instance with ``max_concurrent_calls=0`` silently drop the cap
    mid-process, which is exactly the hot-reload churn the startup-only design
    removes.
    """
    return _PROCESS_LIMITER


def _apply_configured_cap(limit: int) -> None:
    """Resolve the process-wide cap from the first middleware ``__init__``.

    Startup-only: the very first call wins and freezes the cap. A positive
    ``limit`` creates the limiter at that cap; ``limit <= 0`` resolves the cap
    as disabled (limiter stays ``None``, callers short-circuit on
    ``limiter is None``). Every later call - whether it carries a newer or an
    older ``AppConfig`` snapshot, and whether it would raise or lower the cap -
    is ignored, so the cap can never be mutated at runtime. Changing it requires
    a gateway restart.
    """
    global _PROCESS_LIMITER, _CAP_RESOLVED
    if _CAP_RESOLVED:
        return  # cap already frozen at first construction; this instance is a no-op
    with _LIMITER_LOCK:
        if _CAP_RESOLVED:
            return
        _CAP_RESOLVED = True
        if limit > 0:
            _PROCESS_LIMITER = _ProcessWideLimiter(limit)


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
    # burst-rate (limit_burst_rate) spikes. See _get_process_limiter.
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

        # Resolve the process-wide cap (startup-only: the first ``__init__`` in
        # the process wins and freezes it; later instances - newer or older
        # config - are no-ops). Per-attempt callers only acquire/release, so the
        # cap can never be mutated at runtime and there is no downscale or
        # config-freshness race to admit waiters above the live cap.
        _apply_configured_cap(self.max_concurrent_llm_calls)

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

    def _bounded_model_call_sync(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Run one sync model attempt under the process-global concurrency cap.

        The limiter wraps a *single* attempt only (not the retry loop), so
        backoff sleeps release the slot for other callers. ``limiter is None``
        (cap disabled at startup) is a direct passthrough; a non-``None``
        limiter is always consulted - the cap is frozen at the first
        ``__init__``, so a later instance whose ``max_concurrent_llm_calls`` is
        0 cannot silently drop it. Permits release on any exit (return or
        raise) via ``finally`` so a raised handler never leaks a slot.
        """
        limiter = _get_process_limiter()
        if limiter is None:
            return handler(request)
        limiter.acquire_sync()
        try:
            return handler(request)
        finally:
            limiter.release()

    async def _bounded_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Run one async model attempt under the process-global concurrency cap.

        The limiter wraps a *single* attempt only (not the retry loop), so
        backoff sleeps release the slot for other callers - we bound in-flight
        requests, not waiting ones. ``limiter is None`` (cap disabled at
        startup) is a direct passthrough; a non-``None`` limiter is always
        consulted (cap frozen at first ``__init__``). Permits release on any
        exit (return, raise, or cancellation) via ``finally``;
        ``acquire_async`` separately cleans up if cancelled while waiting, so
        capacity never leaks.
        """
        limiter = _get_process_limiter()
        if limiter is None:
            return await handler(request)
        await limiter.acquire_async()
        try:
            return await handler(request)
        finally:
            limiter.release()

    def _build_retry_delay_ms(self, prev_delay_ms: int | None, exc: BaseException, reason: str = "transient") -> int:
        """Compute the next retry delay (ms) using decorrelated jitter.

        An explicit ``Retry-After`` from the provider is honored as-is (no
        jitter) - the server told us exactly when to come back, and for a
        burst-rate 429 this is strongly preferred over any computed delay.
        Otherwise AWS-style "decorrelated jitter" is applied:
        ``delay = random(base, min(cap, max(base, seed * 3)))`` where ``seed``
        is the previous delay, or the reason-specific base on the first retry
        (``prev_delay_ms is None``). The window is clamped to the cap *before*
        drawing (not after) so the distribution stays uniform up to the cap
        rather than piling up at it. ``reason="burst_rate"`` swaps in
        ``burst_retry_base_delay_ms`` (longer than the normal base) so the
        single burst retry lands after the throttle window subsides.

        Seeding the first retry from the *reason-specific* base (not always the
        normal base) is what keeps the first-and-only burst retry
        non-degenerate: with the normal base (1000ms) the burst window would
        collapse to ``randint(5000, max(5000, 1000*3)) = randint(5000, 5000)``
        and every concurrent burst failure would realign on the same 5s tick.
        Seeding from 5000ms gives ``randint(5000, min(8000, 15000)) =
        randint(5000, 8000)`` with defaults, so a fleet that failed together
        spreads out across the whole window.

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
        seed = base if prev_delay_ms is None else prev_delay_ms
        # Clamp the window to the cap *before* drawing so the jitter spreads
        # uniformly across [base, min(cap, seed*3)] instead of concentrating at
        # the cap: with defaults seed*3 (=15000) >> cap (=8000), drawing
        # randint(base, seed*3) then min(delay, cap) would put ~70% of draws at
        # exactly cap, re-clustering a fleet that the jitter is meant to spread.
        high = min(cap, max(base, seed * 3))
        if high < base:
            return cap  # base exceeds cap (misconfiguration): the cap wins
        return random.randint(base, high)

    def _build_retry_message(
        self,
        attempt: int,
        wait_ms: int,
        reason: str,
        *,
        max_attempts: int,
    ) -> str:
        seconds = max(1, round(wait_ms / 1000))
        reason_text = {
            "busy": "provider is busy",
            "burst_rate": "provider is throttling request burst rate",
        }.get(reason, "provider request failed temporarily")
        # ``max_attempts`` is the *effective* budget for this call (from
        # ``_max_attempts_for``), not the configured ceiling: a burst-rate call
        # is capped at 2 attempts, so its message must read ``1/2`` not ``1/3``
        # even when ``retry_max_attempts`` is the default 3 - otherwise the UI
        # promises a retry that will never happen.
        return f"LLM request retry {attempt}/{max_attempts}: {reason_text}. Retrying in {seconds}s."

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

    def _build_retry_event(
        self,
        attempt: int,
        wait_ms: int,
        reason: str,
        *,
        max_attempts: int,
    ) -> dict[str, Any]:
        return {
            "type": "llm_retry",
            "attempt": attempt,
            # Effective budget for this call (burst-rate == 2), not the
            # configured ceiling - the frontend renders this and the
            # ``message`` below, so both must describe the loop that runs.
            "max_attempts": max_attempts,
            "wait_ms": wait_ms,
            "reason": reason,
            "message": self._build_retry_message(attempt, wait_ms, reason, max_attempts=max_attempts),
        }

    def _emit_retry_event(
        self,
        attempt: int,
        wait_ms: int,
        reason: str,
        *,
        max_attempts: int,
    ) -> None:
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
            emit_custom_event(
                self._build_retry_event(attempt, wait_ms, reason, max_attempts=max_attempts),
                writer=writer,
            )
        except GraphBubbleUp:
            raise
        except Exception:
            logger.debug("Failed to emit llm_retry event", exc_info=True)

    async def _aemit_retry_event(
        self,
        attempt: int,
        wait_ms: int,
        reason: str,
        *,
        max_attempts: int,
    ) -> None:
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
            await aemit_custom_event(
                self._build_retry_event(attempt, wait_ms, reason, max_attempts=max_attempts),
                writer=writer,
            )
        except GraphBubbleUp:
            raise
        except Exception:
            logger.debug("Failed to emit async llm_retry event", exc_info=True)

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
        prev_delay_ms: int | None = None
        while True:
            try:
                response = self._bounded_model_call_sync(request, handler)
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
                        max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._emit_retry_event(attempt, wait_ms, reason, max_attempts=max_attempts)
                    time.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable and reason != "burst_rate":
                    self._record_failure()
                else:
                    # Non-retriable, OR burst_rate (a transient provider
                    # slope-throttle, not "provider down"): release the half-open
                    # probe without recording a failure so the circuit doesn't
                    # trip and fast-fail ALL calls for the recovery window - the
                    # exact self-inflicted outage #4290 is trying to prevent.
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
        prev_delay_ms: int | None = None
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
                        max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    await self._aemit_retry_event(attempt, wait_ms, reason, max_attempts=max_attempts)
                    await asyncio.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable and reason != "burst_rate":
                    self._record_failure()
                else:
                    # Non-retriable, OR burst_rate (a transient provider
                    # slope-throttle, not "provider down"): release the half-open
                    # probe without recording a failure so the circuit doesn't
                    # trip and fast-fail ALL calls for the recovery window - the
                    # exact self-inflicted outage #4290 is trying to prevent.
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
