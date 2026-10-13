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
    """An ``OrderedDict`` that evicts the least-recently-used entry at ``maxsize``.

    Used for per-``run_id`` state (stop-reason flags, pending warnings, usage
    accumulators) so a long-lived middleware instance on the lead agent cannot
    leak memory across many runs. Every write - whether it inserts a new key or
    overwrites an existing one - refreshes recency via ``move_to_end``, so the
    least-recently-written key is evicted first (LRU). Without the
    ``move_to_end`` on update the class was insertion-FIFO and a reused
    ``run_id`` whose value was repeatedly overwritten could be evicted FIRST
    while a never-touched entry that just arrived was kept (D4 in the
    agent-core hunt).
    """

    def __init__(self, maxsize: int = 1000, *args: Any, **kwds: Any) -> None:
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key: Any, value: Any) -> None:
        if key in self:
            # Refresh recency so overwriting a value is treated as "use".
            # Mirrors the explicit ``move_to_end`` pattern already used by
            # ``LoopDetectionMiddleware._touch_pending_warning_key_locked``.
            self.move_to_end(key)
        else:
            if len(self) >= self.maxsize:
                self.popitem(last=False)
        super().__setitem__(key, value)
