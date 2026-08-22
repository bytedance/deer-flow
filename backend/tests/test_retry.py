"""Tests for retry utilities."""

import asyncio

import pytest

from deerflow.exceptions import ModelAPICallError
from deerflow.utils.retry import (
    RetryContext,
    RetryError,
    calculate_delay,
    retry,
    retry_async,
    should_retry,
)


class TestCalculateDelay:
    """Tests for delay calculation."""

    def test_initial_delay(self):
        """Test first retry delay."""
        delay = calculate_delay(0, initial_delay=1.0, jitter=False)
        assert delay == 1.0

    def test_exponential_backoff(self):
        """Test exponential backoff."""
        delay_0 = calculate_delay(0, initial_delay=1.0, exponential_base=2.0, jitter=False)
        delay_1 = calculate_delay(1, initial_delay=1.0, exponential_base=2.0, jitter=False)
        delay_2 = calculate_delay(2, initial_delay=1.0, exponential_base=2.0, jitter=False)
        assert delay_0 == 1.0
        assert delay_1 == 2.0
        assert delay_2 == 4.0

    def test_max_delay(self):
        """Test maximum delay cap."""
        delay = calculate_delay(10, initial_delay=1.0, max_delay=30.0, jitter=False)
        assert delay == 30.0

    def test_jitter(self):
        """Test that jitter adds randomness."""
        delays = [calculate_delay(0, initial_delay=1.0, jitter=True) for _ in range(100)]
        # With jitter, delays should vary (0.5x to 1.5x)
        assert min(delays) < 1.0
        assert max(delays) > 1.0
        # Most should be around 1.0
        assert 0.4 < sum(delays) / len(delays) < 1.6


class TestShouldRetry:
    """Tests for retry decision logic."""

    def test_retry_on_connection_error(self):
        """Test retry on connection errors."""
        assert should_retry(ConnectionError("Network error"))
        assert should_retry(TimeoutError("Request timed out"))

    def test_retry_on_os_error(self):
        """Test retry on OS errors (includes network errors)."""
        assert should_retry(OSError("Network unreachable"))

    def test_no_retry_on_value_error(self):
        """Test no retry on value errors by default."""
        assert not should_retry(ValueError("Invalid input"))

    def test_custom_retry_on(self):
        """Test custom retry_on types."""
        assert should_retry(ValueError("test"), retry_on=(ValueError,))
        assert not should_retry(RuntimeError("test"), retry_on=(ValueError,))

    def test_retry_on_recoverable_deerflow_error(self):
        """Test retry on recoverable DeerFlow errors."""
        error = ModelAPICallError("gpt-4", "Rate limit", status_code=429)
        assert should_retry(error)

    def test_retry_on_status_codes(self):
        """Test retry on specific HTTP status codes."""
        error = ModelAPICallError("gpt-4", "Server error", status_code=500)
        assert should_retry(error, retry_on_status_codes={500, 502, 503})

        error_404 = ModelAPICallError("gpt-4", "Not found", status_code=404)
        assert not should_retry(error_404, retry_on_status_codes={500, 502, 503})


class TestRetryDecorator:
    """Tests for the retry decorator."""

    def test_retry_success_on_first_try(self):
        """Test function succeeds on first try."""
        call_count = 0

        @retry(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """Test function succeeds after failures."""
        call_count = 0

        @retry(max_retries=3, initial_delay=0.01)
        def eventually_successful_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        result = eventually_successful_func()
        assert result == "success"
        assert call_count == 3

    def test_retry_exhausted(self):
        """Test retry exhausted raises last exception."""
        call_count = 0

        @retry(max_retries=2, initial_delay=0.01)
        def always_failing_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError) as exc_info:
            always_failing_func()
        assert "Always fails" in str(exc_info.value)
        assert call_count == 3  # Initial + 2 retries

    def test_retry_non_retryable_error(self):
        """Test non-retryable errors are raised immediately."""
        call_count = 0

        @retry(max_retries=3)
        def non_retryable_error_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError):
            non_retryable_error_func()
        assert call_count == 1

    def test_retry_custom_retry_on(self):
        """Test custom retry_on types."""
        call_count = 0

        @retry(max_retries=2, initial_delay=0.01, retry_on=(ValueError,))
        def custom_retry_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retry this")
            return "success"

        result = custom_retry_func()
        assert result == "success"
        assert call_count == 2

    def test_retry_on_retry_callback(self):
        """Test on_retry callback is called."""
        retry_calls = []

        def on_retry_callback(exc, attempt, delay):
            retry_calls.append((type(exc).__name__, attempt, delay))

        @retry(max_retries=2, initial_delay=0.01, on_retry=on_retry_callback)
        def callback_func():
            if len(retry_calls) < 2:
                raise ConnectionError("Retry")
            return "success"

        result = callback_func()
        assert result == "success"
        assert len(retry_calls) == 2

    def test_retry_preserves_function_metadata(self):
        """Test that decorator preserves function metadata."""

        @retry()
        def documented_func():
            """This is a documented function."""
            pass

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "This is a documented function."


class TestRetryAsync:
    """Tests for async retry functionality."""

    @pytest.mark.anyio
    async def test_async_retry_success(self):
        """Test async function succeeds on retry."""
        call_count = 0

        @retry(max_retries=3, initial_delay=0.01)
        async def async_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Network error")
            return "success"

        result = await async_func()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.anyio
    async def test_async_retry_exhausted(self):
        """Test async retry exhausted."""
        call_count = 0

        @retry(max_retries=2, initial_delay=0.01)
        async def async_failing_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError):
            await async_failing_func()
        assert call_count == 3

    @pytest.mark.anyio
    async def test_retry_async_coroutine_factory(self):
        """Test retry_async with a coroutine factory."""
        call_count = 0

        async def my_coro():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Retry")
            return "success"

        # Use a factory function for proper retry behavior
        result = await retry_async(my_coro, max_retries=3, initial_delay=0.01)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.anyio
    async def test_retry_async_coroutine_direct_single_attempt(self):
        """Test retry_async with direct coroutine only allows single attempt."""
        call_count = 0

        async def my_coro():
            nonlocal call_count
            call_count += 1
            return "success"

        # Direct coroutine works for single successful attempt
        result = await retry_async(my_coro(), max_retries=3, initial_delay=0.01)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.anyio
    async def test_retry_async_coroutine_direct_retry_error(self):
        """Test retry_async with direct coroutine raises RetryError on failure."""
        call_count = 0

        async def my_coro():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Fail")

        # Direct coroutine with failure should raise RetryError
        with pytest.raises(RetryError) as exc_info:
            await retry_async(my_coro(), max_retries=3, initial_delay=0.01)
        assert "Cannot retry a coroutine" in str(exc_info.value)
        assert call_count == 1


class TestRetryContext:
    """Tests for RetryContext context manager."""

    def test_context_success(self):
        """Test RetryContext with successful operation."""
        with RetryContext(max_retries=3) as ctx:
            while ctx.should_retry():
                try:
                    result = "success"
                    break
                except Exception as e:
                    delay = ctx.handle_exception(e)

        assert result == "success"
        assert ctx.attempt == 0

    def test_context_retry(self):
        """Test RetryContext with retries."""
        call_count = 0
        result = None

        with RetryContext(max_retries=3, initial_delay=0.01) as ctx:
            while ctx.should_retry():
                try:
                    call_count += 1
                    if call_count < 3:
                        raise ConnectionError("Retry")
                    result = "success"
                    break
                except ConnectionError as e:
                    ctx.handle_exception(e)

        assert result == "success"
        assert call_count == 3
        assert ctx.attempt == 2

    def test_context_exhausted(self):
        """Test RetryContext with exhausted retries."""
        call_count = 0

        with pytest.raises(ConnectionError):
            with RetryContext(max_retries=2, initial_delay=0.01) as ctx:
                while ctx.should_retry():
                    call_count += 1
                    try:
                        raise ConnectionError("Always fails")
                    except ConnectionError as e:
                        ctx.handle_exception(e)

        assert call_count == 3  # Initial + 2 retries

    def test_context_get_delay(self):
        """Test RetryContext delay calculation."""
        with RetryContext(max_retries=3, initial_delay=1.0, jitter=False) as ctx:
            delay_0 = ctx.get_delay()
            ctx.attempt = 1
            delay_1 = ctx.get_delay()
            ctx.attempt = 2
            delay_2 = ctx.get_delay()

        assert delay_0 == 1.0
        assert delay_1 == 2.0
        assert delay_2 == 4.0


class TestRetryError:
    """Tests for RetryError."""

    def test_retry_error_basic(self):
        """Test basic RetryError."""
        error = RetryError("All retries failed")
        assert "All retries failed" in str(error)

    def test_retry_error_with_details(self):
        """Test RetryError with details."""
        last_exc = ValueError("Last error")
        error = RetryError("Failed", last_exception=last_exc, attempts=3)
        assert error.last_exception == last_exc
        assert error.attempts == 3
        assert "3 attempts" in str(error)
        assert "Last error" in str(error)