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


def _fold_blocks(blocks: list[dict]) -> list[dict]:
    """Fold create/update/delete block events into their final visible state."""
    final_blocks: dict[str, dict] = {}

    for block in blocks:
        block_id = block.get("block_id")
        if not block_id:
            continue

        action = block.get("action", "create")
        if action == "delete":
            final_blocks.pop(block_id, None)
        elif action == "update":
            existing = final_blocks.get(block_id)
            if existing:
                final_blocks[block_id] = {
                    **existing,
                    **block,
                    "action": "create",
                    "props": {
                        **existing.get("props", {}),
                        **block.get("props", {}),
                    },
                }
            else:
                final_blocks[block_id] = {**block, "action": "create"}
        else:
            final_blocks[block_id] = {**block, "action": "create"}

    return list(final_blocks.values())


def _prune_and_get_valid_entries(thread_id: str) -> list[tuple[float, dict]]:
    now = time.time()
    entries = _store.get(thread_id, [])
    valid = [(ts, b) for ts, b in entries if now - ts < _BLOCK_TTL_SECONDS]
    _store[thread_id] = valid
    return valid


def resolve_create_block_id(thread_id: str, requested_block_id: str | None) -> str | None:
    """Return a thread-safe create block id that won't overwrite a visible block."""
    if not requested_block_id:
        return None

    with _lock:
        valid = _prune_and_get_valid_entries(thread_id)
        existing_ids = {
            block.get("block_id")
            for block in _fold_blocks([block for _, block in valid])
            if block.get("block_id")
        }

        if requested_block_id not in existing_ids:
            return requested_block_id

        suffix = 2
        candidate = f"{requested_block_id}-{suffix}"
        while candidate in existing_ids:
            suffix += 1
            candidate = f"{requested_block_id}-{suffix}"

        return candidate


def persist_block(thread_id: str, block: dict) -> None:
    """Store a UIBlock for later recovery."""
    with _lock:
        _store[thread_id].append((time.time(), block))


def get_persisted_blocks(thread_id: str) -> list[dict]:
    """Retrieve non-expired blocks for a thread."""
    with _lock:
        valid = _prune_and_get_valid_entries(thread_id)
        return _fold_blocks([b for _, b in valid])


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
    blocks: list[dict] = []

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

            blocks.append(block)

    return _fold_blocks(blocks)
