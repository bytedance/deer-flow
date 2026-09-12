"""Immutable, checkpoint-reachable source batches in a thread-local SQLite file.

Only visible text and tool-call arguments enter the archive. Message envelopes,
reasoning, artifacts and binary blocks are deliberately not serialized.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.config import get_config

from deerflow.agents.human_input import read_human_input_response
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.utils.file_io import run_file_io
from deerflow.utils.messages import message_content_to_text

logger = logging.getLogger(__name__)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def scope(runtime) -> tuple[Path, str]:
    context = getattr(runtime, "context", None) or {}
    thread_id = context.get("thread_id")
    if not thread_id:
        config = getattr(runtime, "config", None)
        if config is None:
            try:
                config = get_config()
            except RuntimeError:
                config = {}
        thread_id = config.get("configurable", {}).get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("Task history requires a thread ID")
    user_id = resolve_runtime_user_id(runtime)
    path = get_paths().thread_dir(thread_id, user_id=user_id) / "task-history" / "history.sqlite"
    return path, digest([user_id, thread_id])


def records(messages, cap: int = 16000) -> list[dict]:
    result = []
    for message in messages:
        if not isinstance(message, (HumanMessage, AIMessage, ToolMessage)):
            continue
        # Framework injections are data for the current call, not source history.
        hidden_injection = message.additional_kwargs.get("hide_from_ui") and not (isinstance(message, HumanMessage) and read_human_input_response(message.additional_kwargs) is not None)
        if hidden_injection or any(message.additional_kwargs.get(key) for key in ("deerflow_content_kind", "dynamic_context_reminder")) or (message.name or "").startswith("__"):
            continue
        content = message.content
        # Mixed LangChain content may contain plain strings. Filter typed blocks
        # before normalization so a reasoning/image/unknown block's text field
        # cannot enter the archive through the broader shared text extractor.
        if isinstance(content, list):
            content = [block for block in content if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")]
        text = message_content_to_text(content)
        calls = getattr(message, "tool_calls", None)
        if calls:
            text += "\nTool calls: " + json.dumps([{k: c.get(k) for k in ("name", "args", "id")} for c in calls], ensure_ascii=False, default=str)
        if not text:
            continue
        source = {"role": message.type, "message_id": message.id, "name": message.name, "text": text}
        source_id = "r" + digest(source)[:32]
        result.append({**source, "id": source_id, "text": text[:cap], "truncated": len(text) > cap})
    return result


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", text.casefold())
    tokens = []
    for word in words:
        if re.search(r"[\u3400-\u9fff]", word):
            tokens.extend(word[i : i + 2] for i in range(max(1, len(word) - 1)))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))


def terms(text: str) -> list[str]:
    return _tokens(text[:500])[:32]


def index_text(text: str) -> str:
    return " ".join(_tokens(text))


def reachable(state: dict, owner: str) -> list[str]:
    history = state.get("task_history") or {}
    if history.get("scope") != owner:
        return []
    return [b for b in history.get("batches", [])[-64:] if isinstance(b, str) and re.fullmatch(r"[a-f0-9]{64}", b)]


def capture(state: dict, runtime, messages, config) -> dict:
    """Publish a batch only via the returned checkpoint update; rollback stays isolated."""
    try:
        path, owner = scope(runtime)
        old = reachable(state, owner)
        sources = records(messages, config.max_record_chars)
        omitted = max(0, len(sources) - config.max_records_per_batch)
        sources = sources[-config.max_records_per_batch :]
        batch = digest([owner, sources])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path, timeout=5)) as db, db:
            db.execute("PRAGMA max_page_count=32768")  # 128 MiB at SQLite's default page size.
            db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, created INTEGER)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS sources USING fts5(batch UNINDEXED, id UNINDEXED, payload UNINDEXED, words)")
            if not db.execute("SELECT 1 FROM batches WHERE id=?", (batch,)).fetchone():
                db.execute("INSERT INTO batches VALUES (?, COALESCE((SELECT MAX(created) + 1 FROM batches), 1))", (batch,))
                db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?)", [(batch, r["id"], json.dumps(r, ensure_ascii=False), index_text(r["text"])) for r in sources])
            expired = db.execute("SELECT id FROM batches ORDER BY created DESC LIMIT -1 OFFSET ?", (config.max_batches,)).fetchall()
            for (expired_id,) in expired:
                db.execute("DELETE FROM sources WHERE batch=?", (expired_id,))
                db.execute("DELETE FROM batches WHERE id=?", (expired_id,))
        batches = list(dict.fromkeys([*old, batch]))[-config.max_batches :]
        return {"scope": owner, "batches": batches, "omitted_records": omitted, "status": "available"}
    except (OSError, sqlite3.Error, ValueError):
        logger.warning("Task history capture unavailable; preserving ordinary compaction", exc_info=False)
        return {**(state.get("task_history") or {}), "status": "unavailable"}


async def acapture(*args) -> dict:
    # Drain a started filesystem write before cancellation can release thread resources.
    task = asyncio.create_task(run_file_io(capture, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        raise


def lookup(state: dict, runtime, *, query: str | None = None, source_id: str | None = None) -> dict:
    path, owner = scope(runtime)
    batches = reachable(state, owner)
    active = records(state.get("messages", []), 64000)
    keywords = terms(query or "")
    if query is not None and not keywords:
        return {"results": [], "status": "empty_query"}
    found = {}
    history = state.get("task_history") or {}
    status = "unavailable" if history.get("status") == "unavailable" else "available"
    if batches:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                placeholders = ",".join("?" for _ in batches)
                present = db.execute(f"SELECT count(*) FROM batches WHERE id IN ({placeholders})", batches).fetchone()[0]
                if present != len(batches) and status != "unavailable":
                    status = "partially_expired"
                if source_id:
                    rows = db.execute(f"SELECT payload FROM sources WHERE batch IN ({placeholders}) AND id=? LIMIT 1", [*batches, source_id])
                else:
                    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in keywords)
                    rows = db.execute(f"SELECT payload FROM sources WHERE sources MATCH ? AND batch IN ({placeholders}) ORDER BY rank LIMIT 8", [match, *batches])
                for (payload,) in rows:
                    row = json.loads(payload)
                    found[row["id"]] = row
        except (OSError, sqlite3.Error):
            status = "unavailable"
    elif history.get("scope") is not None and history["scope"] != owner:
        status = "scope_unavailable"
    for row in active:
        if (source_id and row["id"] == source_id) or (query is not None and any(t in row["text"].casefold() for t in keywords)):
            found[row["id"]] = row
    return {"results": list(found.values())[:8], "status": status}
