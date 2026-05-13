"""In-memory persistence for UIBlocks with TTL-based expiry and checkpoint recovery."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict

_BLOCK_TTL_SECONDS = 3600
_lock = threading.Lock()
_store: dict[str, list[tuple[float, dict]]] = defaultdict(list)

_UI_BLOCK_PATTERN = re.compile(r"<!--ui_block:(.+?)-->")


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


def extract_blocks_from_messages(messages: list) -> list[dict]:
    """Extract UI blocks embedded in tool message content (checkpoint recovery).

    Scans ToolMessage content for <!--ui_block:{json}--> markers and reconstructs
    the block list. Applies create/update/delete actions in order to produce the
    final state.
    """
    blocks: dict[str, dict] = {}

    for msg in messages:
        content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        if not content or not isinstance(content, str):
            continue
        if "<!--ui_block:" not in content:
            continue

        for match in _UI_BLOCK_PATTERN.finditer(content):
            try:
                block = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue

            block_id = block.get("block_id")
            if not block_id:
                continue

            action = block.get("action", "create")
            if action == "delete":
                blocks.pop(block_id, None)
            elif action == "update":
                existing = blocks.get(block_id)
                if existing:
                    existing["props"] = {**existing.get("props", {}), **block.get("props", {})}
                else:
                    blocks[block_id] = block
            else:
                blocks[block_id] = block

    return list(blocks.values())
