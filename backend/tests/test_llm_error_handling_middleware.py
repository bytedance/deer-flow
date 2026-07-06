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
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


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
