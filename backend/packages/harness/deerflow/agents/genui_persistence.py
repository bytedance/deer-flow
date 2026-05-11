"""In-memory persistence for UIBlocks with TTL-based expiry."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_BLOCK_TTL_SECONDS = 3600
_lock = threading.Lock()
_store: dict[str, list[tuple[float, dict]]] = defaultdict(list)


def persist_block(thread_id: str, block: dict) -> None:
    """Store a UIBlock for later recovery."""
    with _lock:
        _store[thread_id].append((time.time(), block))


def get_persisted_blocks(thread_id: str) -> list[dict]:
    """Retrieve non-expired blocks for a thread."""
    now = time.time()
    with _lock:
        entries = _store.get(thread_id, [])
        valid = [(ts, b) for ts, b in entries if now - ts < _BLOCK_TTL_SECONDS]
        _store[thread_id] = valid
        return [b for _, b in valid]


def clear_thread_blocks(thread_id: str) -> None:
    """Remove all blocks for a thread."""
    with _lock:
        _store.pop(thread_id, None)
