import asyncio
import time
import pytest

from tg_intel_crawler.utils.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_delays_between_calls():
    """Rate limiter should enforce minimum delay between calls."""
    limiter = RateLimiter(delay_min=0.1, delay_max=0.1)
    start = time.monotonic()
    await limiter.wait()
    await limiter.wait()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.1


@pytest.mark.asyncio
async def test_rate_limiter_random_delay_in_range():
    """Delay should be between min and max."""
    limiter = RateLimiter(delay_min=0.1, delay_max=0.3)
    start = time.monotonic()
    await limiter.wait()
    await limiter.wait()
    elapsed = time.monotonic() - start
    assert 0.1 <= elapsed <= 0.5
