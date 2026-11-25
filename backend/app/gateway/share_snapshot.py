"""Build a portable transcript under the caller's exclusive thread reservation."""

import json
import mimetypes
from pathlib import PurePosixPath

from fastapi import HTTPException, Request

from app.gateway.conversation_access import _visible_text
from app.gateway.conversation_reader import read_visible_message_page
from app.gateway.deps import get_run_event_store, get_run_manager, get_thread_store
from app.gateway.extension_artifacts import read_snapshot
from app.gateway.services import build_thread_checkpoint_state_accessor
from deerflow.runtime import serialize_channel_values_for_api
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import run_file_io

MAX_SHARE_MESSAGES = 10_000
MAX_SHARE_JSON_BYTES = 10 * 1024 * 1024
MAX_SHARE_ARTIFACTS = 64
MAX_SHARE_FILE_BYTES = 20 * 1024 * 1024
MAX_SHARE_TOTAL_BYTES = 100 * 1024 * 1024
OUTPUT_PREFIX = "/mnt/user-data/outputs/"


def artifact_path(value: str) -> str:
    """Only canonical relative output paths are ever persisted or imported."""
    path = value.removeprefix(OUTPUT_PREFIX)
    if not path or len(path) > 1024 or path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path) or any(p in {"", ".", ".."} for p in path.split("/")) or str(PurePosixPath(path)) != path:
        raise HTTPException(422, "Invalid shared artifact path")
    return path


def project_message(message: dict, index: int) -> dict | None:
    """Share visible text, not execution metadata, prompts or private attachments."""
    extra = message.get("additional_kwargs") or {}
    if not isinstance(extra, dict) or extra.get("hide_from_ui") or message.get("name") == "summary":
        return None
    visible = _visible_text({"content": message})
    identity = str(message.get("id") or f"message-{index}")
    if visible:
        role, content = visible
        return {"id": identity, "type": "human" if role == "user" else "ai", "content": content}
    if message.get("type") == "tool":
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return {"id": identity, "type": "tool", "name": str(message.get("name") or "tool"), "content": content}
    return None


def project_transcript(messages: list[dict]) -> list[dict]:
    projected: list[dict] = []
    positions: dict[str, int] = {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        item = project_message(message, index)
        if item is None:
            continue
        identity = item["id"].removesuffix("__user") if item["type"] == "human" else item["id"]
        if identity in positions:
            projected[positions[identity]] = item
        else:
            positions[identity] = len(projected)
            projected.append(item)
    return projected


async def capture_share(request: Request, thread_id: str, expected_checkpoint: str | None) -> dict:
    owner = get_effective_user_id()
    record = await get_thread_store(request).get(thread_id, user_id=owner)
    if record is None:
        raise HTTPException(404, "Thread not found")
    accessor, config = await build_thread_checkpoint_state_accessor(request, thread_id=thread_id, fail_closed=True)
    state = await accessor.aget(config)
    checkpoint_id = (state.config or {}).get("configurable", {}).get("checkpoint_id")
    if not checkpoint_id or state.next:
        raise HTTPException(409, "Finish the current turn before sharing")
    if expected_checkpoint is not None and checkpoint_id != expected_checkpoint:
        raise HTTPException(409, "Thread changed; refresh before sharing")
    rows: list[dict] = []
    cursor = None
    while True:
        page, more = await read_visible_message_page(event_store=get_run_event_store(request), run_manager=get_run_manager(request), thread_id=thread_id, user_id=owner, limit=200, before_seq=cursor)
        rows = page + rows
        if len(rows) > MAX_SHARE_MESSAGES:
            raise HTTPException(413, "Conversation exceeds the share limit")
        if not more:
            break
        if not page or (cursor is not None and page[0]["seq"] >= cursor):
            raise HTTPException(500, "Unable to capture complete conversation history")
        cursor = page[0]["seq"]
    values = serialize_channel_values_for_api(state.values)
    source_messages = [row["content"] for row in rows] if rows else values.get("messages", [])
    if len(source_messages) > MAX_SHARE_MESSAGES:
        raise HTTPException(413, "Conversation exceeds the share limit")
    messages = await run_file_io(project_transcript, source_messages)
    if not messages:
        raise HTTPException(409, "There are no visible messages to share")
    snapshot = {"title": record.get("display_name") or values.get("title") or "Shared conversation", "messages": messages}
    if len(json.dumps(snapshot, ensure_ascii=False).encode()) > MAX_SHARE_JSON_BYTES:
        raise HTTPException(413, "Conversation exceeds the share limit")
    paths = list(dict.fromkeys(values.get("artifacts") or []))
    if len(paths) > MAX_SHARE_ARTIFACTS:
        raise HTTPException(413, "Too many artifacts to share")
    artifacts: list[dict] = []
    total = 0
    for path in paths:
        if not isinstance(path, str) or not path.startswith(OUTPUT_PREFIX):
            raise HTTPException(422, "Only output artifacts can be shared")
        relative = artifact_path(path)
        content = await read_snapshot(request, owner, thread_id, path, max_bytes=MAX_SHARE_FILE_BYTES)
        total += len(content)
        if total > MAX_SHARE_TOTAL_BYTES:
            raise HTTPException(413, "Artifacts exceed the total share limit")
        mime = await run_file_io(lambda: mimetypes.guess_type(relative)[0] or "application/octet-stream")
        artifacts.append({"path": relative, "content": content, "mime_type": mime})
    return {"thread_id": thread_id, "owner_id": owner, "incarnation": record.get("incarnation"), "checkpoint_id": checkpoint_id, "seq": max((row["seq"] for row in rows), default=0), "snapshot": snapshot, "artifacts": artifacts}
