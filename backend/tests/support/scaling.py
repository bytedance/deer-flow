"""Growth-rate check for scans that must stay linear on adversarial input.

A fixed time limit passes on a fast machine and fails on a loaded runner, so
``growth`` compares the same call on a small and a large input instead. Time is
the CPU time of the calling thread, which does not count while other processes
hold the core, and each size is the best of several samples that repeat the
call for a few milliseconds. Over a 16x larger input a linear scan grows about
16x (less when fixed costs dominate the small input) and a quadratic one about
256x.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

SCALE = 16
# Four times the linear growth and a quarter of the quadratic one.
LINEAR_LIMIT = 64


def _best_time(call: Callable[[], object], *, samples: int, sample_seconds: float = 0.005) -> float:
    repeats = 1
    while True:
        started = time.thread_time()
        for _ in range(repeats):
            call()
        if time.thread_time() - started >= sample_seconds or repeats >= 1 << 12:
            break
        repeats *= 4
    best = float("inf")
    for _ in range(samples):
        gc.collect()
        started = time.thread_time()
        for _ in range(repeats):
            call()
        best = min(best, (time.thread_time() - started) / repeats)
    return best


def growth(run: Callable[[int], object], size: int) -> float:
    """Return how much more CPU time ``run(size * SCALE)`` takes than ``run(size)``."""
    small = _best_time(lambda: run(size), samples=5)
    large = _best_time(lambda: run(size * SCALE), samples=3)
    return large / small
