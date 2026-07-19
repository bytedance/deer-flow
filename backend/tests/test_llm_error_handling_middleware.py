from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
)
from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture(autouse=True)
def _reset_process_limiter() -> Iterator[None]:
    """Reset the module-global limiter between tests.

    The limiter is a process singleton shared across all middleware instances,
    so cap / in-flight state from one test would otherwise bleed into the next
    (notably the limit-change test, which asserts the singleton is reused).
    """
    from deerflow.agents.middlewares import llm_error_handling_middleware as mod

    mod._PROCESS_LIMITER = None
    yield
    mod._PROCESS_LIMITER = None


def _make_app_config() -> AppConfig:
    """Minimal AppConfig for middleware tests; circuit_breaker uses defaults."""
    return AppConfig(sandbox=SandboxConfig(use="test"))


class FakeError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.body = body
        self.response = SimpleNamespace(status_code=status_code, headers=headers or {}) if status_code is not None or headers else None


def _build_middleware(**attrs: int) -> LLMErrorHandlingMiddleware:
    middleware = LLMErrorHandlingMiddleware(app_config=_make_app_config())
    for key, value in attrs.items():
        setattr(middleware, key, value)
    return middleware


def test_async_model_call_retries_busy_provider_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=25, retry_cap_delay_ms=25)
    attempts = 0
    waits: list[float] = []
    events: list[dict] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    def fake_writer():
        return events.append

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeError("当前服务集群负载较高，请稍后重试，感谢您的耐心等待。 (2064)")
        return AIMessage(content="ok")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "langgraph.config.get_stream_writer",
        fake_writer,
    )

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert attempts == 3
    assert waits == [0.025, 0.025]
    assert [event["type"] for event in events] == ["llm_retry", "llm_retry"]


def test_async_model_call_returns_user_message_for_quota_errors() -> None:
    middleware = _build_middleware(retry_max_attempts=3)

    async def handler(_request) -> AIMessage:
        raise FakeError(
            "insufficient_quota: account balance is empty",
            status_code=429,
            code="insufficient_quota",
        )

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert "out of quota" in str(result.content)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "quota"
    assert result.additional_kwargs["error_type"] == "FakeError"


def test_async_model_call_marks_transient_retry_exhaustion_as_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=25, retry_cap_delay_ms=25)

    async def fake_sleep(_delay: float) -> None:
        return None

    async def handler(_request) -> AIMessage:
        raise FakeError("Connection error.", status_code=503)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert "temporarily unavailable" in str(result.content)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "transient"
    assert result.additional_kwargs["error_detail"] == "Connection error."


def test_sync_model_call_uses_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    waits: list[float] = []
    attempts = 0

    def fake_sleep(delay: float) -> None:
        waits.append(delay)

    def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeError(
                "server busy",
                status_code=503,
                headers={"Retry-After": "2"},
            )
        return AIMessage(content="ok")

    monkeypatch.setattr("time.sleep", fake_sleep)

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert waits == [2.0]


def test_sync_model_call_propagates_graph_bubble_up() -> None:
    middleware = _build_middleware()

    def handler(_request) -> AIMessage:
        raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        middleware.wrap_model_call(SimpleNamespace(), handler)


def test_async_model_call_propagates_graph_bubble_up() -> None:
    middleware = _build_middleware()

    async def handler(_request) -> AIMessage:
        raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))


def test_circuit_half_open_graph_bubble_up_resets_probe() -> None:
    """Verify that GraphBubbleUp in half_open state resets probe_in_flight."""
    middleware = _build_middleware()

    # Step 1: Manually set state to half_open and check_circuit() to set probe_in_flight=True
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    # Call _check_circuit() once to simulate the probe being allowed through
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    # Step 2: Now trigger handler that raises GraphBubbleUp
    def handler(_request) -> AIMessage:
        raise GraphBubbleUp()

    # Mock _check_circuit() to return False (since we already did the probe check)
    import unittest.mock

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with pytest.raises(GraphBubbleUp):
            middleware.wrap_model_call(SimpleNamespace(), handler)

    # Verify probe_in_flight was reset, state should remain half_open
    assert middleware._circuit_probe_in_flight is False
    assert middleware._circuit_state == "half_open"


@pytest.mark.anyio
async def test_async_circuit_half_open_graph_bubble_up_resets_probe() -> None:
    """Verify that GraphBubbleUp in half_open state resets probe_in_flight (async version)."""
    middleware = _build_middleware()

    # Step 1: Manually set state to half_open and check_circuit() to set probe_in_flight=True
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    # Call _check_circuit() once to simulate the probe being allowed through
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    # Step 2: Now trigger handler that raises GraphBubbleUp
    async def handler(_request) -> AIMessage:
        raise GraphBubbleUp()

    # Mock _check_circuit() to return False (since we already did the probe check)
    import unittest.mock

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with pytest.raises(GraphBubbleUp):
            await middleware.awrap_model_call(SimpleNamespace(), handler)

    # Verify probe_in_flight was reset, state should remain half_open
    assert middleware._circuit_probe_in_flight is False
    assert middleware._circuit_state == "half_open"


def test_circuit_half_open_non_retriable_error_resets_probe() -> None:
    """A non-retriable error during a half-open probe must release the probe.

    Regression: the non-retriable branch neither recorded a failure (correct —
    business errors like quota/auth must not trip the breaker) nor reset
    ``_circuit_probe_in_flight``. So one non-retriable probe left the circuit
    stuck at half_open with probe_in_flight=True, and every subsequent call
    fast-failed forever because no later call could ever run the handler to
    reach ``_record_success`` / ``_record_failure``.
    """
    import unittest.mock

    middleware = _build_middleware()

    # Enter half_open and let one probe through (probe_in_flight -> True).
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    def handler(_request) -> AIMessage:
        raise FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    # _check_circuit already admitted the probe above; keep it False here so the
    # top-of-call gate does not fast-fail before the handler runs. Force the
    # error to classify as non-retriable regardless of heuristics.
    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with unittest.mock.patch.object(middleware, "_classify_error", return_value=(False, "quota")):
            result = middleware.wrap_model_call(SimpleNamespace(), handler)

    # Non-retriable errors still surface a graceful fallback (not a raise) and
    # must NOT trip the breaker.
    assert isinstance(result, AIMessage)
    assert middleware._circuit_state == "half_open"
    # The probe was released, so the real gate re-admits the next probe instead
    # of fast-failing forever.
    assert middleware._circuit_probe_in_flight is False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True


@pytest.mark.anyio
async def test_async_circuit_half_open_non_retriable_error_resets_probe() -> None:
    """Async mirror: a non-retriable error during a half-open probe releases it."""
    import unittest.mock

    middleware = _build_middleware()

    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    async def handler(_request) -> AIMessage:
        raise FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with unittest.mock.patch.object(middleware, "_classify_error", return_value=(False, "quota")):
            result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert middleware._circuit_state == "half_open"
    assert middleware._circuit_probe_in_flight is False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True


# ---------- Circuit Breaker Tests ----------


def transient_failing_handler(request: Any) -> Any:
    raise FakeError("Server Error", status_code=502)  # Used for transient error


def quota_failing_handler(request: Any) -> Any:
    raise FakeError("Quota exceeded", body={"error": {"code": "insufficient_quota"}})  # Used for quota error


def success_handler(request: Any) -> Any:
    return AIMessage(content="Success")


def mock_classify_retriable(exc: BaseException) -> tuple[bool, str]:
    return True, "transient"


def mock_classify_non_retriable(exc: BaseException) -> tuple[bool, str]:
    return False, "quota"


def test_circuit_breaker_trips_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that circuit breaker trips, fast fails, correctly transitions to Half-Open, and recovers or re-opens."""

    # Mock time.sleep to avoid slow tests during retry loops (Speed up from ~4s to 0.1s)
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    # Mock time.time to decouple from private implementation details and enable time travel
    current_time = 1000.0
    monkeypatch.setattr("time.time", lambda: current_time)

    middleware = _build_middleware(circuit_failure_threshold=3, circuit_recovery_timeout_sec=10)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_retriable)

    request: Any = {"messages": []}

    # --- 0. Test initial state & Success ---
    # Success handler does not increase count. If it's already 0, it stays 0.
    middleware.wrap_model_call(request, success_handler)
    assert middleware._circuit_failure_count == 0
    assert middleware._check_circuit() is False

    # --- 1. Trip the circuit ---
    # Fails 3 overall calls. Threshold (3) is reached.
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 1
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 2
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 3
    assert middleware._check_circuit() is True  # Circuit is OPEN

    # --- 2. Fast Fail ---
    # 2nd call: fast fail immediately without calling handler.
    # Count should not increase during OPEN state.
    result = middleware.wrap_model_call(request, success_handler)
    assert result.content == middleware._build_circuit_breaker_message()
    assert middleware._circuit_failure_count == 3

    # --- 3. Half-Open -> Fail -> Re-Open ---
    # Time travel 11 seconds (timeout is 10s). Current time becomes 1011.0
    current_time += 11.0

    # Verify that the timeout was set EXACTLY relative to current_time + timeout_sec
    assert middleware._circuit_open_until == current_time - 11.0 + middleware.circuit_recovery_timeout_sec

    # Fails again! The request will go through the 3-attempt retry loop again.
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == middleware.circuit_failure_threshold
    assert middleware._circuit_state == "open"  # Re-OPENed

    # --- 4. Half-Open -> Success -> Reset ---
    # Time travel another 11 seconds
    current_time += 11.0

    # Succeeds this time! Should completely reset.
    result = middleware.wrap_model_call(request, success_handler)
    assert result.content == "Success"
    assert middleware._circuit_failure_count == 0  # Fully RESET!
    assert middleware._check_circuit() is False


def test_circuit_breaker_does_not_trip_on_non_retriable_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that circuit breaker ignores business errors like Quota or Auth."""
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    middleware = _build_middleware(circuit_failure_threshold=3)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_non_retriable)

    request: Any = {"messages": []}

    for _ in range(3):
        middleware.wrap_model_call(request, quota_failing_handler)

    assert middleware._circuit_failure_count == 0
    assert middleware._check_circuit() is False


# ---------- ReadError / RemoteProtocolError retriable classification ----------


class _ReadError(Exception):
    """Local stand-in for httpx.ReadError — same class name, no httpx dependency."""


class _RemoteProtocolError(Exception):
    """Local stand-in for httpx.RemoteProtocolError — same class name, no httpx dependency."""


_ReadError.__name__ = "ReadError"
_RemoteProtocolError.__name__ = "RemoteProtocolError"


def test_classify_error_read_error_is_retriable() -> None:
    middleware = _build_middleware()
    exc = _ReadError("Connection dropped mid-stream")
    exc.__class__.__name__ = "ReadError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_classify_error_remote_protocol_error_is_retriable() -> None:
    middleware = _build_middleware()
    exc = _RemoteProtocolError("Server closed connection unexpectedly")
    exc.__class__.__name__ = "RemoteProtocolError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_sync_read_error_triggers_retry_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        raise _ReadError("Connection dropped mid-stream")

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    # ReadError is a generic connection drop, not a chunk-gap timeout, so
    # it must fall back to the legacy transient copy rather than the
    # specialized "split the work into smaller steps" guidance (#3195 CR).
    assert "temporarily unavailable" in result.content
    assert "streaming response was interrupted" not in result.content
    assert attempts == 3  # exhausted all retries
    assert len(waits) == 2  # slept between attempts 1→2 and 2→3


@pytest.mark.anyio
async def test_async_read_error_triggers_retry_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        raise _ReadError("Connection dropped mid-stream")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    # ReadError is a generic connection drop, not a chunk-gap timeout, so
    # it must fall back to the legacy transient copy rather than the
    # specialized "split the work into smaller steps" guidance (#3195 CR).
    assert "temporarily unavailable" in result.content
    assert "streaming response was interrupted" not in result.content
    assert attempts == 3  # exhausted all retries
    assert len(waits) == 2  # slept between attempts 1→2 and 2→3


@pytest.mark.anyio
async def test_async_circuit_breaker_trips_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify async version of circuit breaker correctly handles state transitions."""
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    current_time = 1000.0
    monkeypatch.setattr("time.time", lambda: current_time)

    middleware = _build_middleware(circuit_failure_threshold=3, circuit_recovery_timeout_sec=10)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_retriable)

    async def async_failing_handler(request: Any) -> Any:
        raise FakeError("Server Error", status_code=502)

    request: Any = {"messages": []}

    # --- 1. Trip the circuit ---
    # Fails 3 overall calls. Threshold (3) is reached.
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 1
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 2
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 3
    assert middleware._check_circuit() is True

    # --- 2. Fast Fail ---
    # 2nd call: fast fail immediately without calling handler
    async def async_success_handler(request: Any) -> Any:
        return AIMessage(content="Success")

    result = await middleware.awrap_model_call(request, async_success_handler)
    assert result.content == middleware._build_circuit_breaker_message()
    assert middleware._circuit_failure_count == 3  # Unchanged

    # --- 3. Half-Open -> Fail -> Re-Open ---
    # Time travel 11 seconds
    current_time += 11.0

    # Verify timeout formula
    assert middleware._circuit_open_until == current_time - 11.0 + middleware.circuit_recovery_timeout_sec

    # Fails again! The request goes through the 3-attempt retry loop.
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == middleware.circuit_failure_threshold
    assert middleware._circuit_state == "open"  # Re-OPENed

    # --- 4. Half-Open -> Success -> Reset ---
    # Time travel another 11 seconds
    current_time += 11.0

    result = await middleware.awrap_model_call(request, async_success_handler)
    assert result.content == "Success"
    assert middleware._circuit_failure_count == 0  # RESET
    assert middleware._check_circuit() is False


class _StreamChunkTimeoutError(Exception):
    """Local stand-in for langchain_openai's StreamChunkTimeoutError —
    matched by class name, no langchain-openai import needed (mirrors
    how this file already stubs httpx.ReadError / RemoteProtocolError).
    """


_StreamChunkTimeoutError.__name__ = "StreamChunkTimeoutError"


def test_classify_error_stream_chunk_timeout_is_retriable() -> None:
    """StreamChunkTimeoutError must be classified as transient/retriable."""
    middleware = _build_middleware()
    exc = _StreamChunkTimeoutError("No streaming chunk received for 120.0s (model=mimo-v2.5, chunks_received=58).")
    exc.__class__.__name__ = "StreamChunkTimeoutError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_sync_stream_chunk_timeout_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync handler raising StreamChunkTimeoutError is retried exactly once —
    the per-exception override caps it at 2 total attempts (1 first call + 1
    retry) even when retry_max_attempts=3.
    Same-payload retry on a chunk-gap timeout buffers the same way upstream;
    a full 3-attempt loop would stack 6-12 minutes of dead air before
    surfacing failure. We keep one cheap reconnect for genuine transient TCP
    blips, then surface the failure so the model can re-plan on its next turn.
    """
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=10,
        retry_cap_delay_ms=10,
    )
    attempts = 0
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        raise _StreamChunkTimeoutError("No streaming chunk received for 120.0s")

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert "streaming response was interrupted" in result.content
    # Override caps StreamChunkTimeoutError at 2 attempts (1 first call + 1 retry).
    assert attempts == 2
    # Exactly one sleep between the first attempt and the single retry.
    assert len(waits) == 1


@pytest.mark.anyio
async def test_async_stream_chunk_timeout_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async mirror of the sync test: StreamChunkTimeoutError is capped at
    2 attempts (1 first call + 1 retry) so we don't stack 6-12 minutes of
    dead air on a same-payload buffering failure.
    """
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=10,
        retry_cap_delay_ms=10,
    )
    attempts = 0
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        raise _StreamChunkTimeoutError("No streaming chunk received for 120.0s")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert "streaming response was interrupted" in result.content
    assert attempts == 2
    # Exactly one sleep between the first attempt and the single retry.
    assert len(waits) == 1


def test_max_attempts_for_returns_override_for_stream_chunk_timeout() -> None:
    """StreamChunkTimeoutError must use the tightened budget (2 = "keep one retry"),
    not the default of 3."""
    middleware = _build_middleware(retry_max_attempts=3)
    exc = _StreamChunkTimeoutError("upstream stalled")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    assert middleware._max_attempts_for(exc) == 2


def test_max_attempts_for_falls_back_to_default_for_unlisted_exception() -> None:
    """ReadError / RemoteProtocolError keep the full retry budget — only
    StreamChunkTimeoutError pays for stalling upstream for `stream_chunk_timeout`
    seconds per attempt, so only it gets the tighter cap.
    """
    middleware = _build_middleware(retry_max_attempts=3)

    read_err = _ReadError("conn reset")
    read_err.__class__.__name__ = "ReadError"
    proto_err = _RemoteProtocolError("peer closed")
    proto_err.__class__.__name__ = "RemoteProtocolError"

    assert middleware._max_attempts_for(read_err) == 3
    assert middleware._max_attempts_for(proto_err) == 3
    assert middleware._max_attempts_for(FakeError("boom")) == 3


def test_max_attempts_for_override_never_exceeds_user_cap() -> None:
    """If the operator lowered retry_max_attempts below the override default,
    the user-configured cap wins — overrides only ever *tighten*, never loosen.
    """
    middleware = _build_middleware(retry_max_attempts=1)
    exc = _StreamChunkTimeoutError("upstream stalled")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    assert middleware._max_attempts_for(exc) == 1


def test_user_message_for_stream_chunk_timeout_mentions_split_or_shorten() -> None:
    """When the retry budget for StreamChunkTimeoutError is exhausted, the user
    message must guide the user toward splitting / shortening the request
    instead of suggesting a generic retry. This is the actionable advice
    Reviewer B asked for in the follow-up CR (issue #3189).
    """
    middleware = _build_middleware()
    exc = _StreamChunkTimeoutError("No streaming chunk received for 120.0s")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "streaming response was interrupted" in message
    assert "split" in message or "shorten" in message
    # The old generic "streaming response was interrupted" wording must NOT appear here,
    # otherwise the actionable guidance is buried.
    assert "temporarily unavailable" not in message


def test_user_message_for_remote_protocol_error_uses_generic_transient_copy() -> None:
    """RemoteProtocolError is a generic connection drop that can fire on
    transient network blips with perfectly normal payloads. The
    "split the work into smaller steps" guidance only applies when the
    upstream chunk-gap watchdog fires (StreamChunkTimeoutError), so
    RemoteProtocolError must fall back to the legacy transient copy.
    Regression guard for the #3195 CR feedback.
    """
    middleware = _build_middleware()
    exc = _RemoteProtocolError("Server closed connection unexpectedly")
    exc.__class__.__name__ = "RemoteProtocolError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_read_error_uses_generic_transient_copy() -> None:
    """httpx.ReadError is symmetric to RemoteProtocolError: a generic
    connection drop that must NOT receive the "split the work" guidance.
    Regression guard for the #3195 CR feedback.
    """
    middleware = _build_middleware()
    exc = FakeError("connection dropped mid-stream")
    exc.__class__.__name__ = "ReadError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_generic_transient_keeps_legacy_copy() -> None:
    """Generic transient errors (HTTP 503, 'cluster busy', etc.) must keep
    the original 'streaming response was interrupted' message — only stream-drop
    exceptions get the new specialized copy. This prevents regression on
    callers who already rely on the legacy wording.
    """
    middleware = _build_middleware()
    exc = FakeError("server busy", status_code=503)

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_quota_unchanged() -> None:
    """Sanity check: the quota / auth branches must remain untouched by the
    stream-drop refactor.
    """
    middleware = _build_middleware()
    exc = FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    message = middleware._build_user_message(exc, reason="quota")

    assert "out of quota" in message
    assert "streaming response was interrupted" not in message


def test_classify_error_index_error_is_retriable_transient() -> None:
    """``langchain_core.language_models.chat_models.ainvoke`` crashes with
    ``IndexError: list index out of range`` when the upstream provider
    returns ``200 OK`` with ``generations == []`` (observed against the
    Volces "coding" endpoint at ark.cn-beijing.volces.com). That's an
    upstream-payload glitch we don't want killing the entire run, so it
    must classify as retriable/transient and go through the normal
    retry/backoff path.
    """
    middleware = _build_middleware()
    exc = IndexError("list index out of range")
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_async_index_error_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty-``generations`` payloads from the upstream provider must not
    abort the run on the first failure. Confirm that the retry loop kicks
    in and the next attempt's successful AIMessage is returned to the
    caller instead of an error fallback.
    """
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0

    async def fake_sleep(_delay: float) -> None:
        return None

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise IndexError("list index out of range")
        return AIMessage(content="ok")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert attempts == 2


def test_async_index_error_exhausted_returns_user_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every retry hits the same empty-``generations`` IndexError, the
    middleware must still produce a user-facing fallback AIMessage (with
    ``deerflow_error_fallback=True``) instead of letting the IndexError
    propagate out of the agent loop and ending the run in ``error``
    status with no GitHub-side reply.
    """
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=10, retry_cap_delay_ms=10)

    async def fake_sleep(_delay: float) -> None:
        return None

    async def handler(_request) -> AIMessage:
        raise IndexError("list index out of range")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "transient"
    assert result.additional_kwargs["error_type"] == "IndexError"
    assert "temporarily unavailable" in str(result.content)


# ---------- Process-wide concurrency limiter ----------


async def _run_concurrent(
    middleware: LLMErrorHandlingMiddleware,
    count: int,
    event: asyncio.Event,
) -> tuple[int, int]:
    """Fire ``count`` concurrent awrap_model_call tasks whose handlers park on
    ``event`` until the test releases them.

    Returns ``(max_in_flight, in_flight_at_steady_state)`` so callers can assert
    the concurrency cap. Handlers increment a shared counter on entry and
    decrement on exit, so the counter reflects only calls that got past the
    semaphore - parked-on-semaphore tasks do not count as in-flight.
    """
    in_flight = 0
    max_in_flight = 0

    async def handler(_request) -> AIMessage:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        if in_flight > max_in_flight:
            max_in_flight = in_flight
        try:
            await event.wait()
        finally:
            in_flight -= 1
        return AIMessage(content="ok")

    tasks = [asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler)) for _ in range(count)]

    # Yield until the steady state is reached: the cap is hit (capped case), or
    # every task has been admitted (uncapped case).
    limit = middleware.max_concurrent_llm_calls
    target = count if limit <= 0 else min(count, limit)
    for _ in range(100):
        if max_in_flight >= target:
            break
        await asyncio.sleep(0)
    steady_in_flight = in_flight

    event.set()
    await asyncio.gather(*tasks)
    return max_in_flight, steady_in_flight


@pytest.mark.anyio
async def test_limiter_caps_concurrent_llm_calls() -> None:
    """With max_concurrent_llm_calls=2, five concurrent calls must never exceed
    two in-flight at once - the rest park on the process-global semaphore.
    """
    middleware = _build_middleware(max_concurrent_llm_calls=2)
    event = asyncio.Event()

    max_in_flight, steady_in_flight = await _run_concurrent(middleware, 5, event)

    assert max_in_flight == 2
    # At steady state exactly two handlers are parked on the event; the other
    # three are blocked on the semaphore and have not entered the handler.
    assert steady_in_flight == 2


@pytest.mark.anyio
async def test_limiter_disabled_by_default() -> None:
    """max_concurrent_llm_calls defaults to 0 (disabled): no cap, so all five
    concurrent calls run at once. Guards against the semaphore accidentally
    engaging for existing deployments that never opted in.
    """
    middleware = _build_middleware()  # default max_concurrent_llm_calls=0
    event = asyncio.Event()

    max_in_flight, _ = await _run_concurrent(middleware, 5, event)

    assert max_in_flight == 5


@pytest.mark.anyio
async def test_limiter_is_shared_across_instances() -> None:
    """The semaphore is process-global, not per-middleware-instance: two
    middlewares with the same limit share one cap, so four calls spread across
    them still never exceed two in-flight.
    """
    mw_a = _build_middleware(max_concurrent_llm_calls=2)
    mw_b = _build_middleware(max_concurrent_llm_calls=2)
    event = asyncio.Event()

    in_flight = 0
    max_in_flight = 0

    async def handler(_request) -> AIMessage:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        if in_flight > max_in_flight:
            max_in_flight = in_flight
        try:
            await event.wait()
        finally:
            in_flight -= 1
        return AIMessage(content="ok")

    tasks = [
        asyncio.create_task(mw_a.awrap_model_call(SimpleNamespace(), handler)),
        asyncio.create_task(mw_b.awrap_model_call(SimpleNamespace(), handler)),
        asyncio.create_task(mw_a.awrap_model_call(SimpleNamespace(), handler)),
        asyncio.create_task(mw_b.awrap_model_call(SimpleNamespace(), handler)),
    ]
    for _ in range(100):
        if max_in_flight >= 2:
            break
        await asyncio.sleep(0)

    assert max_in_flight == 2  # shared global cap, not 2+2 per instance
    event.set()
    await asyncio.gather(*tasks)


@pytest.mark.anyio
async def test_limiter_releases_slot_during_backoff_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The semaphore wraps a single attempt only, not the retry loop. A call in
    its backoff sleep must release its slot so another caller can proceed -
    otherwise backoff would waste concurrency slots and worsen the burst we are
    trying to smooth.

    ``fake_sleep`` parks call A in backoff on ``backoff_gate`` so the test has a
    deterministic window in which to observe call B being admitted to the freed
    slot. ``asyncio.Event.wait`` / ``asyncio.wait_for`` do not route through
    ``asyncio.sleep``, so the monkeypatch does not disturb test orchestration.
    """
    middleware = _build_middleware(
        max_concurrent_llm_calls=1,
        retry_max_attempts=2,
        retry_base_delay_ms=10000,
        retry_cap_delay_ms=10000,
    )
    a_entered_backoff = asyncio.Event()
    backoff_gate = asyncio.Event()
    b_admitted = asyncio.Event()
    attempts_a = 0

    async def fake_sleep(_delay: float) -> None:
        a_entered_backoff.set()
        # Park call A in backoff until the test releases it.
        await backoff_gate.wait()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def handler_a(_request) -> AIMessage:
        nonlocal attempts_a
        attempts_a += 1
        # Always fails -> call A enters backoff after attempt 1, exhausts after 2.
        raise FakeError("server busy", status_code=503)

    async def handler_b(_request) -> AIMessage:
        b_admitted.set()
        return AIMessage(content="b-ok")

    task_a = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler_a))
    # Wait until call A has failed attempt 1 and parked in its backoff sleep -
    # at which point its semaphore slot has been released.
    await asyncio.wait_for(a_entered_backoff.wait(), timeout=2.0)

    task_b = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler_b))
    # Call B must be admitted to the single slot while A is still parked in
    # backoff (A has not retried yet).
    await asyncio.wait_for(b_admitted.wait(), timeout=2.0)
    assert attempts_a == 1

    # Release A: it retries once more, fails again, and exhausts its budget.
    backoff_gate.set()
    result_a = await task_a
    result_b = await task_b
    assert result_b.content == "b-ok"
    assert result_a.additional_kwargs.get("deerflow_error_fallback") is True


# ---------- Decorrelated jitter ----------


def test_retry_delay_decorrelated_jitter_within_bounds() -> None:
    """First retry seeds from base: high = max(base, base*3) = base*3, so the
    delay lands in [base, base*3].
    """
    middleware = _build_middleware(retry_base_delay_ms=100, retry_cap_delay_ms=10000)
    delay = middleware._build_retry_delay_ms(100, FakeError("server busy", status_code=503))
    assert 100 <= delay <= 300


def test_retry_delay_grows_from_previous_delay() -> None:
    """Decorrelated jitter grows off the previous delay, not a fixed schedule:
    prev=1000 -> high = max(100, 3000) = 3000 -> delay in [100, 3000].
    """
    middleware = _build_middleware(retry_base_delay_ms=100, retry_cap_delay_ms=10000)
    delay = middleware._build_retry_delay_ms(1000, FakeError("server busy", status_code=503))
    assert 100 <= delay <= 3000


def test_retry_delay_respects_cap() -> None:
    """The cap always bounds the jittered delay, even when prev*3 would exceed it."""
    middleware = _build_middleware(retry_base_delay_ms=100, retry_cap_delay_ms=200)
    delay = middleware._build_retry_delay_ms(1000, FakeError("server busy", status_code=503))
    assert delay <= 200


def test_retry_delay_base_equals_cap_is_deterministic() -> None:
    """When base == cap the jittered delay collapses to exactly cap regardless
    of the RNG draw - this is what keeps the fast/retry-budget tests stable.
    """
    middleware = _build_middleware(retry_base_delay_ms=25, retry_cap_delay_ms=25)
    for _ in range(20):
        delay = middleware._build_retry_delay_ms(25, FakeError("server busy", status_code=503))
        assert delay == 25


def test_retry_delay_honors_retry_after_without_jitter() -> None:
    """An explicit Retry-After is honored verbatim - the server said exactly
    when to come back, so jitter must not perturb it.
    """
    middleware = _build_middleware(retry_base_delay_ms=100, retry_cap_delay_ms=10000)
    exc = FakeError("rate limited", status_code=429, headers={"retry-after-ms": "5000"})
    delay = middleware._build_retry_delay_ms(100, exc)
    assert delay == 5000


@pytest.mark.anyio
async def test_async_retry_loop_emits_jittered_delays_within_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the async retry loop emits decorrelated-jitter delays, each
    within [base, cap], and prev_delay threads through so the second delay can
    grow off the first.
    """
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=100,
        retry_cap_delay_ms=10000,
    )
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeError("server busy", status_code=503)
        return AIMessage(content="ok")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert result.content == "ok"
    assert attempts == 3
    assert len(waits) == 2
    for w in waits:
        assert 0.1 <= w <= 10.0


# ---------- Config wiring ----------


def test_max_concurrent_llm_calls_defaults_to_disabled() -> None:
    """With no llm_call config, the cap defaults to 0 (disabled) - existing
    deployments see no behavior change.
    """
    middleware = LLMErrorHandlingMiddleware(app_config=_make_app_config())
    assert middleware.max_concurrent_llm_calls == 0


def test_max_concurrent_llm_calls_wired_from_config() -> None:
    """llm_call.max_concurrent_calls flows through AppConfig into the middleware
    attribute that _get_process_limiter reads.
    """
    app_config = AppConfig(
        sandbox=SandboxConfig(use="test"),
        llm_call=LlmCallConfig(max_concurrent_calls=8),
    )
    middleware = LLMErrorHandlingMiddleware(app_config=app_config)
    assert middleware.max_concurrent_llm_calls == 8


@pytest.mark.anyio
async def test_configured_cap_bounds_concurrency_end_to_end() -> None:
    """A cap set via config.yaml (not via setattr) actually bounds in-flight
    calls end-to-end: AppConfig -> middleware -> process-wide limiter.
    """
    app_config = AppConfig(
        sandbox=SandboxConfig(use="test"),
        llm_call=LlmCallConfig(max_concurrent_calls=2),
    )
    middleware = LLMErrorHandlingMiddleware(app_config=app_config)
    event = asyncio.Event()

    max_in_flight, steady_in_flight = await _run_concurrent(middleware, 5, event)

    assert max_in_flight == 2
    assert steady_in_flight == 2


# ---------- Burst-rate (limit_burst_rate) classification ----------


def test_classify_error_limit_burst_rate_by_code() -> None:
    """A 429 with error code ``limit_burst_rate`` classifies as burst_rate,
    not generic transient - so it gets the tight budget + longer backoff.
    """
    middleware = _build_middleware()
    exc = FakeError("Request rate increased too quickly", status_code=429, code="limit_burst_rate")
    assert middleware._classify_error(exc) == (True, "burst_rate")


def test_classify_error_limit_burst_rate_by_message() -> None:
    """Burst-rate is also detectable from the message alone (no code field),
    matching how Volcano Engine phrases the error.
    """
    middleware = _build_middleware()
    exc = FakeError("Request rate increased too quickly. To ensure system stability, please adjust your client logic.", status_code=429)
    assert middleware._classify_error(exc) == (True, "burst_rate")


def test_classify_error_normal_429_stays_transient() -> None:
    """A non-burst 429 (generic 'too many requests') must NOT be classified as
    burst_rate - it keeps the full retry budget and normal backoff.
    """
    middleware = _build_middleware()
    exc = FakeError("Too many requests", status_code=429)
    assert middleware._classify_error(exc) == (True, "transient")


def test_classify_error_burst_takes_precedence_over_transient_status() -> None:
    """Burst-rate detection runs before the generic 429->transient mapping."""
    middleware = _build_middleware()
    exc = FakeError("limit_burst_rate triggered", status_code=429, code="limit_burst_rate")
    assert middleware._classify_error(exc) == (True, "burst_rate")


def test_max_attempts_for_burst_rate_is_tight() -> None:
    """burst_rate gets a 2-attempt budget (1 + 1 retry) even when the global
    cap is higher - retrying into the burst adds demand to the throttled slope.
    """
    middleware = _build_middleware(retry_max_attempts=3)
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    assert middleware._max_attempts_for(exc, "burst_rate") == 2


def test_max_attempts_for_burst_rate_respects_user_cap() -> None:
    """If the operator lowered retry_max_attempts below the burst budget, the
    user cap wins - overrides only ever tighten, never loosen."""
    middleware = _build_middleware(retry_max_attempts=1)
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    assert middleware._max_attempts_for(exc, "burst_rate") == 1


def test_burst_rate_delay_uses_longer_base() -> None:
    """burst_rate backoff uses burst_retry_base_delay_ms (not the normal base),
    so the single retry lands after the throttle window subsides."""
    middleware = _build_middleware(
        retry_base_delay_ms=10,
        retry_cap_delay_ms=200,
        burst_retry_base_delay_ms=100,
    )
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    # prev = burst base (100) -> high = max(100, 300) = 300 -> delay in [100, 200] (capped)
    delay = middleware._build_retry_delay_ms(100, exc, reason="burst_rate")
    assert 100 <= delay <= 200


def test_normal_transient_delay_uses_normal_base_not_burst() -> None:
    """Non-burst transient errors keep using the normal base - the burst base
    only applies to reason='burst_rate'."""
    middleware = _build_middleware(
        retry_base_delay_ms=10,
        retry_cap_delay_ms=200,
        burst_retry_base_delay_ms=100,
    )
    exc = FakeError("server busy", status_code=503)
    # prev = 10 -> high = max(10, 30) = 30 -> delay in [10, 30]
    delay = middleware._build_retry_delay_ms(10, exc, reason="transient")
    assert 10 <= delay <= 30


def test_burst_rate_delay_prefers_retry_after() -> None:
    """An explicit Retry-After is honored verbatim for burst-rate errors - the
    server said exactly when to come back, so no jitter / longer base applies."""
    middleware = _build_middleware(
        retry_base_delay_ms=10,
        retry_cap_delay_ms=200,
        burst_retry_base_delay_ms=100,
    )
    exc = FakeError(
        "rate increased too quickly",
        status_code=429,
        code="limit_burst_rate",
        headers={"retry-after-ms": "5000"},
    )
    assert middleware._build_retry_delay_ms(100, exc, reason="burst_rate") == 5000


def test_burst_rate_exhausted_returns_distinct_message() -> None:
    """When the burst retry budget is exhausted, the user-facing message names
    the burst-rate throttle rather than the generic 'temporarily unavailable'."""
    middleware = _build_middleware()
    exc = FakeError("Request rate increased too quickly", status_code=429, code="limit_burst_rate")
    message = middleware._build_user_message(exc, reason="burst_rate")
    assert "burst-rate" in message
    assert "temporarily unavailable" not in message


@pytest.mark.anyio
async def test_async_burst_rate_uses_tight_budget_and_longer_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a handler raising limit_burst_rate retries at most once
    (budget 2) with a delay drawn from the burst base, then surfaces a fallback.
    """
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=10,
        retry_cap_delay_ms=200,
        burst_retry_base_delay_ms=100,
    )
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    async def handler(_request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        raise FakeError("Request rate increased too quickly", status_code=429, code="limit_burst_rate")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert attempts == 2  # tight budget: 1 first attempt + 1 retry
    assert len(waits) == 1
    # Longer burst base: delay in [burst_base, cap] = [0.1s, 0.2s]
    assert 0.1 <= waits[0] <= 0.2
    assert result.additional_kwargs.get("deerflow_error_fallback") is True
    assert result.additional_kwargs.get("error_reason") == "burst_rate"


# ---------- Retry params config wiring ----------


def test_retry_params_default_values() -> None:
    """With no llm_call config, retry params fall back to their documented
    defaults (matching the previous hard-coded class attributes)."""
    middleware = LLMErrorHandlingMiddleware(app_config=_make_app_config())
    assert middleware.retry_max_attempts == 3
    assert middleware.retry_base_delay_ms == 1000
    assert middleware.retry_cap_delay_ms == 8000
    assert middleware.burst_retry_base_delay_ms == 5000
    assert middleware.max_concurrent_llm_calls == 0


def test_retry_params_wired_from_config() -> None:
    """All retry/backoff knobs flow from config.yaml -> AppConfig -> middleware."""
    app_config = AppConfig(
        sandbox=SandboxConfig(use="test"),
        llm_call=LlmCallConfig(
            retry_max_attempts=7,
            retry_base_delay_ms=123,
            retry_cap_delay_ms=999,
            burst_retry_base_delay_ms=777,
            max_concurrent_calls=4,
        ),
    )
    middleware = LLMErrorHandlingMiddleware(app_config=app_config)
    assert middleware.retry_max_attempts == 7
    assert middleware.retry_base_delay_ms == 123
    assert middleware.retry_cap_delay_ms == 999
    assert middleware.burst_retry_base_delay_ms == 777
    assert middleware.max_concurrent_llm_calls == 4


def test_burst_retry_base_delay_is_configurable_end_to_end() -> None:
    """A burst base set via config actually drives the burst retry delay."""
    app_config = AppConfig(
        sandbox=SandboxConfig(use="test"),
        llm_call=LlmCallConfig(burst_retry_base_delay_ms=100, retry_cap_delay_ms=200),
    )
    middleware = LLMErrorHandlingMiddleware(app_config=app_config)
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    delay = middleware._build_retry_delay_ms(100, exc, reason="burst_rate")
    assert 100 <= delay <= 200


# ---------- Process-wide limiter across call paths (review P1) ----------


def _run_on_isolated_loop(coro_factory: Any) -> concurrent.futures.Future:
    """Run ``coro_factory()`` on a freshly-created event loop in a worker thread.

    Mirrors how ``subagents/executor.py`` runs subagent calls on an isolated
    persistent loop separate from the lead agent's loop. Returns a
    ``concurrent.futures.Future`` holding the result/exception.
    """
    done: concurrent.futures.Future = concurrent.futures.Future()

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            done.set_result(loop.run_until_complete(coro_factory()))
        except Exception as exc:  # propagate to the awaiting test
            done.set_exception(exc)
        finally:
            loop.close()

    threading.Thread(target=runner, daemon=True).start()
    return done


@pytest.mark.anyio
async def test_limiter_is_process_wide_across_event_loops() -> None:
    """A lead-agent call (main loop) and a subagent call (isolated loop) share
    one process-wide cap - the limiter is NOT loop-bound (unlike
    asyncio.Semaphore). With cap=1, two concurrent calls on different loops must
    never both be in-flight. Regression for the per-loop cap the reviewer found.
    """
    middleware = _build_middleware(max_concurrent_llm_calls=1)
    gate = threading.Event()  # cross-loop-safe block
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    async def handler(_request) -> AIMessage:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            await asyncio.to_thread(gate.wait)
        finally:
            with lock:
                in_flight -= 1
        return AIMessage(content="ok")

    # Call A on the test (main) loop; call B on a separate event loop / thread.
    task_a = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler))
    fut_b = _run_on_isolated_loop(lambda: middleware.awrap_model_call(SimpleNamespace(), handler))

    # Let both loops run; with cap=1 only one handler may be in-flight at a time
    # across BOTH loops.
    for _ in range(100):
        await asyncio.sleep(0)
        with lock:
            if max_in_flight >= 1:
                break
    with lock:
        assert max_in_flight == 1

    gate.set()
    await task_a
    await asyncio.wait_for(asyncio.wrap_future(fut_b), timeout=5)
    with lock:
        assert in_flight == 0  # both calls completed; no handler left in-flight


def test_limiter_caps_concurrent_sync_calls() -> None:
    """The sync graph path now acquires the limiter too (previously bypassed it
    entirely). With cap=1, two concurrent sync calls must never both be
    in-flight. Regression for the sync-wrapper bypass the reviewer found.
    """
    middleware = _build_middleware(max_concurrent_llm_calls=1)
    gate = threading.Event()
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def handler(_request) -> AIMessage:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        gate.wait()
        with lock:
            in_flight -= 1
        return AIMessage(content="ok")

    results: list[AIMessage] = []

    def run_one() -> None:
        results.append(middleware.wrap_model_call(SimpleNamespace(), handler))

    t1 = threading.Thread(target=run_one)
    t2 = threading.Thread(target=run_one)
    t1.start()
    t2.start()
    # Wait until one handler is in-flight; the other blocks on the limiter.
    for _ in range(400):
        with lock:
            if max_in_flight >= 1:
                break
        time.sleep(0.005)
    with lock:
        assert max_in_flight == 1

    gate.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()
    assert len(results) == 2


def test_limit_change_does_not_recreate_limiter_or_abandon_permits() -> None:
    """Changing the configured cap updates the limiter in place - same instance,
    in-flight permit preserved (not abandoned). In-flight never exceeds the
    effective cap during the transition. Regression for the recreate-on-change
    permit-abandonment the reviewer found.
    """
    from deerflow.agents.middlewares.llm_error_handling_middleware import _get_process_limiter

    middleware = _build_middleware(max_concurrent_llm_calls=1)
    limiter_at_cap1 = _get_process_limiter(1)
    assert limiter_at_cap1 is not None

    gate = threading.Event()
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def handler(_request) -> AIMessage:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        gate.wait()
        with lock:
            in_flight -= 1
        return AIMessage(content="ok")

    holder = threading.Thread(target=lambda: middleware.wrap_model_call(SimpleNamespace(), handler))
    holder.start()
    # Wait until the holder has taken the single permit (cap=1).
    for _ in range(400):
        with lock:
            if max_in_flight >= 1:
                break
        time.sleep(0.005)
    with lock:
        assert max_in_flight == 1

    # Simulate a config reload raising the cap: the next limiter lookup with a
    # new limit updates the cap in place (a fresh middleware instance would do
    # the same on its first model call).
    limiter_at_cap3 = _get_process_limiter(3)
    # Same instance, cap updated in place - NOT recreated.
    assert limiter_at_cap3 is limiter_at_cap1
    assert limiter_at_cap3.limit == 3
    # The holder's permit is still counted against the new cap (not abandoned).
    assert limiter_at_cap3._in_flight == 1

    # Release the holder; it returns its permit to the SAME limiter.
    gate.set()
    holder.join(timeout=5)
    assert not holder.is_alive()
    assert limiter_at_cap3._in_flight == 0  # permit returned, not leaked


@pytest.mark.anyio
async def test_limiter_cancellation_does_not_leak_capacity() -> None:
    """A caller cancelled while waiting on the limiter must not leak a permit:
    after it's cancelled and the in-flight call releases, a fresh call is still
    admitted to the same cap. Regression for the cancellation-capacity-leak
    concern the reviewer raised.
    """
    middleware = _build_middleware(max_concurrent_llm_calls=1)
    gate = threading.Event()
    a_started = asyncio.Event()

    async def handler_a(_request) -> AIMessage:
        a_started.set()
        await asyncio.to_thread(gate.wait)
        return AIMessage(content="a-ok")

    async def handler_b(_request) -> AIMessage:
        return AIMessage(content="b-ok")

    # A acquires the single permit and blocks.
    task_a = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler_a))
    await asyncio.wait_for(a_started.wait(), timeout=2)

    # B queues on the limiter (no permit available).
    task_b = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler_b))
    await asyncio.sleep(0.05)
    assert not task_b.done()  # B is waiting, not admitted

    # Cancel B while it waits on the limiter.
    task_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_b

    # Release A; its permit returns. B's cancellation must not have consumed it.
    gate.set()
    result_a = await task_a
    assert result_a.content == "a-ok"

    # A fresh call C must be admitted immediately - proving B's cancellation
    # didn't leak capacity (in_flight back to 0, not stuck at 1).
    task_c = asyncio.create_task(middleware.awrap_model_call(SimpleNamespace(), handler_b))
    result_c = await asyncio.wait_for(task_c, timeout=2)
    assert result_c.content == "b-ok"


# ---------- Burst-rate first-retry jitter (review P1) ----------


def test_burst_first_retry_is_non_degenerate_with_default_config() -> None:
    """With shipped defaults (burst_base=5000, cap=8000, normal_base=1000), the
    first burst retry must be drawn from a NON-degenerate window [5000, 8000],
    not fixed at 5000ms. Regression for the deterministic-herd bug (prev was
    seeded from the 1000ms normal base, collapsing the window to a point).
    """
    middleware = _build_middleware()  # defaults
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    # prev_delay_ms=None simulates the first retry (loops now init it to None).
    delays = {middleware._build_retry_delay_ms(None, exc, reason="burst_rate") for _ in range(20)}
    assert all(5000 <= d <= 8000 for d in delays)
    assert len(delays) > 1  # non-degenerate: more than one distinct value observed


def test_burst_first_retry_uses_jitter_not_fixed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controlled RNG: forcing randint to an upper-window value yields that
    value (capped), proving the first burst retry is jittered rather than a
    constant 5000ms."""
    middleware = _build_middleware()  # defaults
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    monkeypatch.setattr(
        "deerflow.agents.middlewares.llm_error_handling_middleware.random.randint",
        lambda lo, hi: 7000,
    )
    assert middleware._build_retry_delay_ms(None, exc, reason="burst_rate") == 7000


@pytest.mark.anyio
async def test_async_burst_first_retry_non_degenerate_default_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end on the real async wrapper with default burst config: the
    first (and only) burst retry lands at a jittered value, not fixed at 5s."""
    middleware = _build_middleware()  # defaults: burst_base=5000, cap=8000
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.llm_error_handling_middleware.random.randint",
        lambda lo, hi: 7000,
    )

    async def handler(_request) -> AIMessage:
        raise FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)
    assert len(waits) == 1
    assert waits[0] == 7.0  # 7000ms, jittered - not the fixed 5.0s
    assert result.additional_kwargs.get("error_reason") == "burst_rate"


def test_concurrent_burst_failures_get_distinct_jittered_delays() -> None:
    """De-synchronization invariant: concurrent burst-rate failures get distinct
    retry delays, so a fleet that failed together does not realign on one tick.

    Uses a seeded real RNG (not a monkeypatch) so the window computation still
    runs - on the old code the window collapsed to ``randint(5000, 5000)`` and
    every delay was 5000ms (``len(set) == 1``); the jittered window yields many
    distinct values.
    """
    import random as _random

    middleware = _build_middleware()  # defaults
    exc = FakeError("rate increased too quickly", status_code=429, code="limit_burst_rate")
    saved_state = _random.getstate()
    _random.seed(42)
    try:
        delays = [middleware._build_retry_delay_ms(None, exc, reason="burst_rate") for _ in range(50)]
    finally:
        _random.setstate(saved_state)
    assert all(5000 <= d <= 8000 for d in delays)
    assert len(set(delays)) > 1  # de-synchronized, not a single 5000ms tick
