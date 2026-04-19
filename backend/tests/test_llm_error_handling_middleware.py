from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
)


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
    middleware = LLMErrorHandlingMiddleware()
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

    middleware = LLMErrorHandlingMiddleware()
    middleware.circuit_failure_threshold = 3
    middleware.circuit_recovery_timeout_sec = 10
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

    middleware = LLMErrorHandlingMiddleware()
    middleware.circuit_failure_threshold = 3
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
    assert "temporarily unavailable" in result.content
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
    assert "temporarily unavailable" in result.content
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

    middleware = LLMErrorHandlingMiddleware()
    middleware.circuit_failure_threshold = 3
    middleware.circuit_recovery_timeout_sec = 10
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
