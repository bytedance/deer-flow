import asyncio
import random
import time


class RateLimiter:
    """Async rate limiter with random delay between min and max seconds."""

    def __init__(self, delay_min: float = 2.0, delay_max: float = 5.0):
        self.delay_min = delay_min
        self.delay_max = delay_max
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        """Wait for the appropriate delay since last call."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            delay = random.uniform(self.delay_min, self.delay_max)
            remaining = delay - elapsed
            if remaining > 0 and self._last_call > 0:
                await asyncio.sleep(remaining)
            self._last_call = time.monotonic()
