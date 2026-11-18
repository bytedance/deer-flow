"""A small bounded ``OrderedDict`` shared by guard middlewares.

Guard middlewares (``TokenBudgetMiddleware``, ``LoopDetectionMiddleware``) keep
per-``run_id`` state that must not grow without bound on abandoned or reused
runs. This module provides the single shared implementation so both middlewares
cap identically and a future guard does not reinvent it.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class BoundedDict(OrderedDict):
    """An ``OrderedDict`` that evicts the oldest entry once ``maxsize`` is reached.

    Used for per-``run_id`` state (stop-reason flags, pending warnings, usage
    accumulators) so a long-lived middleware instance on the lead agent cannot
    leak memory across many runs. Insertion order is preserved, so the
    least-recently-inserted key is evicted first.
    """

    def __init__(self, maxsize: int = 1000, *args: Any, **kwds: Any) -> None:
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key: Any, value: Any) -> None:
        if key not in self:
            if len(self) >= self.maxsize:
                self.popitem(last=False)
        super().__setitem__(key, value)
