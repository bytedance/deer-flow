"""In-memory persistence for UIBlocks with TTL-based expiry and checkpoint recovery."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict

_BLOCK_TTL_SECONDS = 86400
_lock = threading.Lock()
_store: dict[str, list[tuple[float, dict]]] = defaultdict(list)
_last_checkpoint: dict[str, str] = {}

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


def clear_on_new_run(thread_id: str, checkpoint_id: str) -> None:
    """Clear persisted blocks when a new agent run starts.

    When the checkpoint changes (new turn), previously persisted create/update
    blocks from older turns are removed so that ui_blocks_folded events only
    carry the current turn's blocks.  Delete events are preserved so that
    blocks removed by clear_blocks_by_callback_id stay removed across turns.

    Block history for the recovery endpoint is served by
    extract_blocks_from_messages instead.
    """
    if not checkpoint_id or not thread_id:
        return
    with _lock:
        last = _last_checkpoint.get(thread_id)
        if last and last != checkpoint_id:
            entries = _store.get(thread_id, [])
            delete_events = [
                (ts, b) for ts, b in entries if b.get("action") == "delete"
            ]
            if delete_events:
                _store[thread_id] = delete_events
            else:
                _store.pop(thread_id, None)
        _last_checkpoint[thread_id] = checkpoint_id


def clear_blocks_by_callback_id(thread_id: str, callback_id: str) -> int:
    """Remove all blocks associated with a callback_id and return count of removed.

    Inserts a delete event so subsequent folds will remove the block.
    """
    removed = 0
    with _lock:
        valid = _prune_and_get_valid_entries(thread_id)
        folded = _fold_blocks([b for _, b in valid])
        for block in folded:
            if block.get("callback_id") == callback_id:
                _store[thread_id].append((time.time(), {"action": "delete", "block_id": block["block_id"]}))
                removed += 1
    return removed


def _get_message_key(msg) -> str:
    """Build a message identifier that mirrors the frontend's getHistoryMessageKey."""
    if hasattr(msg, "id") and msg.id:
        return msg.id
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        return msg.tool_call_id
    content = getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", "")
    msg_type = getattr(msg, "type", "") if not isinstance(msg, dict) else msg.get("type", "")
    if isinstance(content, str):
        return f"{msg_type}:{content[:50]}"
    return f"{msg_type}:{id(msg)}"


def _get_message_content(msg) -> str | None:
    """Extract string content from a message object."""
    content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
    if not content or not isinstance(content, str):
        return None
    return content


def extract_blocks_from_messages_with_metadata(messages: list) -> dict:
    """Extract UI blocks from messages with visibility metadata (for frontend history).

    Returns:
        {
            "blocks": list[dict],
            "blockIdsByMessageKey": dict[str, list[str]],
            "duplicatedRawBlockIds": list[str],
        }
    """
    create_counts: dict[str, int] = {}
    for msg in messages:
        content = _get_message_content(msg)
        if not content or "<!--ui_block:" not in content:
            continue
        for match in _UI_BLOCK_PATTERN.finditer(content):
            try:
                block = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            bid = block.get("block_id")
            if not bid:
                continue
            if block.get("action", "create") == "create":
                create_counts[bid] = create_counts.get(bid, 0) + 1

    duplicated_raw_block_ids = [bid for bid, count in create_counts.items() if count > 1]

    create_indices: dict[str, int] = {}
    latest_resolved_by_raw: dict[str, str] = {}
    blocks: dict[str, dict] = {}
    block_ids_by_message_key: dict[str, list[str]] = {}

    for msg in messages:
        content = _get_message_content(msg)
        if not content or "<!--ui_block:" not in content:
            continue

        resolved_block_ids: list[str] = []
        for match in _UI_BLOCK_PATTERN.finditer(content):
            try:
                block = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue

            raw_block_id = block.get("block_id")
            if not raw_block_id:
                continue

            action = block.get("action", "create")

            if action == "create":
                next_create_index = create_indices.get(raw_block_id, 0) + 1
                create_indices[raw_block_id] = next_create_index
                if create_counts.get(raw_block_id, 0) > 1:
                    resolved_block_id = f"{raw_block_id}__{next_create_index}"
                else:
                    resolved_block_id = raw_block_id

                latest_resolved_by_raw[raw_block_id] = resolved_block_id
                blocks[resolved_block_id] = {
                    **block,
                    "block_id": resolved_block_id,
                    "action": "create",
                    "metadata": {**(block.get("metadata") or {})},
                }
                resolved_block_ids.append(resolved_block_id)
                continue

            resolved_block_id = latest_resolved_by_raw.get(raw_block_id, raw_block_id)

            if action == "delete":
                blocks.pop(resolved_block_id, None)
                continue

            existing = blocks.get(resolved_block_id)
            if existing:
                blocks[resolved_block_id] = {
                    **existing,
                    **block,
                    "block_id": resolved_block_id,
                    "action": existing.get("action", "create"),
                    "props": {
                        **existing.get("props", {}),
                        **block.get("props", {}),
                    },
                    "metadata": {
                        **(existing.get("metadata") or {}),
                        **(block.get("metadata") or {}),
                    },
                }
            else:
                blocks[resolved_block_id] = {
                    **block,
                    "block_id": resolved_block_id,
                    "metadata": {**(block.get("metadata") or {})},
                }

            latest_resolved_by_raw[raw_block_id] = resolved_block_id
            resolved_block_ids.append(resolved_block_id)

        if resolved_block_ids:
            message_key = _get_message_key(msg)
            deduped = list(dict.fromkeys(resolved_block_ids))
            block_ids_by_message_key[message_key] = deduped

    return {
        "blocks": list(blocks.values()),
        "blockIdsByMessageKey": block_ids_by_message_key,
        "duplicatedRawBlockIds": duplicated_raw_block_ids,
    }


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
