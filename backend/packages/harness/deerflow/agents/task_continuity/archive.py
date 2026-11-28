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
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, closing
from itertools import chain, islice
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.config import get_config

from deerflow.agents.human_input import read_human_input_response
from deerflow.agents.task_continuity.state import SOURCE_ID_PATTERN, normalize_task_history
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime
from deerflow.utils.file_io import run_file_io
from deerflow.utils.messages import message_content_to_text

logger = logging.getLogger(__name__)

_SEARCH_PAGE_SIZE = 8
_SEARCH_CURSOR = re.compile(r"1:([0-9]{1,9}):([0-9]{1,9}):([a-f0-9]{32}):([a-f0-9]{16})")


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


def _token_spans(folded: str):
    """Preserve indexed token positions in casefolded text without changing tokenization."""
    for match in re.finditer(r"[^\W_]+", folded):
        word = match.group()
        if re.search(r"[\u3400-\u9fff]", word):
            for index in range(max(1, len(word) - 1)):
                yield word[index : index + 2], match.start() + index, match.start() + min(index + 2, len(word))
        else:
            yield word, match.start(), match.end()


def _tokens(text: str) -> list[str]:
    return list(dict.fromkeys(word for word, _, _ in _token_spans(text.casefold())))


def terms(text: str) -> list[str]:
    return _tokens(text[:500])[:32]


def index_text(text: str) -> str:
    return " ".join(_tokens(text))


def _search_excerpt(text: str, keywords: list[str], *, substring: bool) -> dict:
    """Locate the first fitting casefolded keyword match in the readable source."""
    folded = text.casefold()
    if substring:
        hits = [(position, position + len(term)) for term in keywords if (position := folded.find(term)) >= 0]
    else:
        keyword_set = set(keywords)
        hits = [(left, right) for word, left, right in _token_spans(folded) if word in keyword_set]
    start = 0
    if hits:
        positions = [index for index, char in enumerate(text) for _ in char.casefold()]
        fitting_hits = []
        for left, right in hits:
            term = folded[left:right]
            while left >= 0:
                match_start, match_end = positions[left], positions[right - 1] + 1
                if match_end - match_start <= 600:
                    fitting_hits.append((match_start, match_end))
                    break
                if not substring:
                    break
                # A later occurrence can have a shorter original span even
                # though it casefolds to the same term. Preserve overlaps.
                left = folded.find(term, left + 1)
                right = left + len(term)
        hits = fitting_hits
    if hits:
        match_start, match_end = min(hits)
        start = max(0, min(match_start - (600 - (match_end - match_start)) // 2, len(text) - 600))
    end = min(len(text), start + 600)
    return {"excerpt": text[start:end], "excerpt_start": start, "excerpt_end": end, "excerpt_match": bool(hits)}


def reachable(state: dict, owner: str) -> list[str]:
    history = normalize_task_history(state.get("task_history"))
    if history.get("scope") != owner:
        return []
    return history.get("batches", [])


def capture(state: dict, runtime, messages, config) -> dict:
    """Publish a batch only via the returned checkpoint update; rollback stays isolated."""
    history = normalize_task_history(state.get("task_history"))
    try:
        path, owner = scope(runtime)
        old = reachable(state, owner)
        sources = records(messages, config.max_record_chars)
        omitted = max(0, len(sources) - config.max_records_per_batch)
        sources = sources[-config.max_records_per_batch :]
        batch = digest([owner, sources])
        batches = [*[previous for previous in old if previous != batch], batch][-config.max_batches :]
        placeholders = ",".join("?" for _ in batches)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path, timeout=5)) as db, db:
            db.execute("PRAGMA max_page_count=32768")  # 128 MiB at SQLite's default page size.
            db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, created INTEGER)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS sources USING fts5(batch UNINDEXED, id UNINDEXED, payload UNINDEXED, words)")
            # Lock before selecting victims, so concurrent captures cannot plan
            # against stale retention state. Rollback restores evicted rows if
            # the replacement still cannot fit within SQLite's page ceiling.
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM batches WHERE id=?", (batch,)).fetchone()
            created = db.execute("SELECT COALESCE(MAX(created) + 1, 1) FROM batches").fetchone()[0]
            # Retain the batches referenced by the next checkpoint first. An
            # earlier capture may have finished writing without publishing its checkpoint.
            expired = db.execute(
                f"SELECT id FROM batches WHERE id != ? ORDER BY (id IN ({placeholders})) DESC, created DESC LIMIT -1 OFFSET ?",
                [batch, *batches, config.max_batches - 1],
            ).fetchall()
            for (expired_id,) in expired:
                db.execute("DELETE FROM sources WHERE batch=?", (expired_id,))
                db.execute("DELETE FROM batches WHERE id=?", (expired_id,))
            if not exists:
                db.execute("INSERT INTO batches VALUES (?, ?)", (batch, created))
                db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?)", [(batch, r["id"], json.dumps(r, ensure_ascii=False), index_text(r["text"])) for r in sources])
        return {"scope": owner, "batches": batches, "omitted_records": omitted, "status": "available"}
    except (OSError, sqlite3.Error, ValueError):
        logger.warning("Task history capture unavailable; preserving ordinary compaction", exc_info=False)
        return {**history, "status": "unavailable"}


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


def _distinct_archived_sources(rows: Iterable[tuple[str, int]]) -> Iterator[tuple[str, int]]:
    seen = set()
    for source_id, rowid in rows:
        if not isinstance(source_id, str) or SOURCE_ID_PATTERN.fullmatch(source_id) is None:
            raise sqlite3.DatabaseError("Invalid source ID in archived history index")
        if source_id not in seen:
            seen.add(source_id)
            yield source_id, rowid


def _ordered_search_sources(rows: Iterable[tuple[str, int]], active_matches: dict, *, latest_first: bool) -> Iterator[tuple[str, int | None]]:
    archived = _distinct_archived_sources(rows)
    if latest_first:
        return chain(((source_id, None) for source_id in active_matches), (row for row in archived if row[0] not in active_matches))
    first_archived = list(islice(archived, _SEARCH_PAGE_SIZE))
    first_archived_ids = {source_id for source_id, _ in first_archived}
    active_only = {source_id: None for source_id in active_matches if source_id not in first_archived_ids}
    # Reserve space for active hits on the first page as before, then visit
    # all remaining hits without letting overlapping sources take two slots.
    first_archived_count = max(0, _SEARCH_PAGE_SIZE - len(active_only))
    return chain(
        first_archived[:first_archived_count],
        active_only.items(),
        first_archived[first_archived_count:],
        (row for row in archived if row[0] not in active_only),
    )


def _archived_page_records(db: sqlite3.Connection, batches: list[str], page: list[tuple[str, int | None]], active: dict, *, canonical: bool) -> dict:
    archived = [(source_id, rowid) for source_id, rowid in page if source_id not in active]
    if not archived:
        return {}
    placeholders = ",".join("?" for _ in archived)
    if canonical:
        # Use the first readable version, as history_read does, even if the
        # result ranked here through a different archived version.
        batch_placeholders = ",".join("?" for _ in batches)
        rows = db.execute(
            f"SELECT id, payload FROM sources WHERE batch IN ({batch_placeholders}) AND id IN ({placeholders}) ORDER BY rowid",
            [*batches, *(source_id for source_id, _ in archived)],
        )
    else:
        rows = db.execute(f"SELECT id, payload FROM sources WHERE rowid IN ({placeholders})", [rowid for _, rowid in archived])
    records_by_id = {}
    for source_id, payload in rows:
        if source_id in records_by_id:
            continue
        try:
            row = json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise sqlite3.DatabaseError("Invalid JSON in archived history payload") from exc
        if not isinstance(row, dict) or row.get("id") != source_id or not isinstance(row.get("text"), str) or row.get("role") not in ("human", "ai", "tool") or not isinstance(row.get("truncated"), bool):
            raise sqlite3.DatabaseError("Invalid archived history record")
        records_by_id[source_id] = row
    return records_by_id


def _search(state: dict, runtime: Runtime, query: str, role: str | None, excerpts: bool, cursor: str | None, *, latest_first: bool) -> dict:
    path, owner = scope(runtime)
    batches = reachable(state, owner)
    history = normalize_task_history(state.get("task_history"))
    status = "unavailable" if history.get("status") == "unavailable" else "available"
    if not batches and history.get("scope") is not None and history["scope"] != owner:
        status = "scope_unavailable"
    stale_cursor = {"results": [], "status": "stale_cursor"}
    messages = state.get("messages", [])
    offset, message_count = 0, len(messages)
    fingerprint, rank_fingerprint = None, None
    if cursor is not None:
        parsed = _SEARCH_CURSOR.fullmatch(cursor)
        if parsed is None:
            return {"results": [], "status": "invalid_cursor"}
        offset, message_count = map(int, parsed.group(1, 2))
        if offset == 0 or offset % _SEARCH_PAGE_SIZE:
            return {"results": [], "status": "invalid_cursor"}
        if message_count > len(messages):
            return stale_cursor
        fingerprint, rank_fingerprint = parsed.group(3, 4)

    keywords = terms(query)
    if not keywords:
        return stale_cursor if cursor is not None else {"results": [], "status": "empty_query"}
    # Search calls append their own messages. Keep the original prefix so
    # following a cursor neither invalidates it nor ranks the previous page.
    active_rows = records(messages[:message_count], 64000)
    if latest_first:
        active_rows.reverse()
    active = {row["id"]: row for row in active_rows}
    active_matches = {source_id: row for source_id, row in active.items() if (role is None or row["role"] == role) and any(term in row["text"].casefold() for term in keywords)}
    next_cursor = None
    try:
        with ExitStack() as stack:
            db = None
            stored_batches = []
            if batches:
                db = stack.enter_context(closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)))
                db.execute("BEGIN")
                stored_batches = db.execute("SELECT id, created FROM batches ORDER BY id").fetchall()
                if not set(batches).issubset(batch for batch, _ in stored_batches) and status != "unavailable":
                    status = "partially_expired"
            # FTS rank also depends on the currently stored corpus, including
            # batches not reachable from this checkpoint.
            snapshot = digest([owner, keywords, role, latest_first, batches, stored_batches, status, message_count, list(active)])
            if fingerprint is not None and fingerprint != digest([snapshot, offset])[:32]:
                return stale_cursor
            rows = ()
            if db is not None:
                placeholders = ",".join("?" for _ in batches)
                match = " OR ".join('"' + term.replace('"', '""') + '"' for term in keywords)
                role_filter = " AND json_extract(payload, '$.role') = ?" if role is not None else ""
                parameters = [match, *batches, *([role] if role is not None else [])]
                order_by = "rank"
                if latest_first:
                    # Recapture changes checkpoint batch order without rewriting row IDs.
                    batch_positions = " ".join(f"WHEN ? THEN {position}" for position in range(len(batches)))
                    order_by = f"CASE batch {batch_positions} END DESC, rowid DESC"
                    parameters.extend(batches)
                rows = db.execute(f"SELECT id, rowid FROM sources WHERE sources MATCH ? AND batch IN ({placeholders}){role_filter} ORDER BY {order_by}", parameters)
            ordered = _ordered_search_sources(rows, active_matches, latest_first=latest_first)
            # A rebuilt index can change unseen hits while leaving the first
            # page intact. Fingerprint every ranked ID in the read transaction.
            rank = hashlib.sha256()
            page = []
            for index, (source_id, rowid) in enumerate(ordered):
                rank.update(source_id.encode("ascii"))
                if offset <= index <= offset + _SEARCH_PAGE_SIZE:
                    page.append((source_id, rowid))
            current_rank = rank.hexdigest()[:16]
            if rank_fingerprint is not None and rank_fingerprint != current_rank:
                return stale_cursor
            if len(page) > _SEARCH_PAGE_SIZE:
                next_offset = offset + _SEARCH_PAGE_SIZE
                page.pop()
                next_cursor = f"1:{next_offset}:{message_count}:{digest([snapshot, next_offset])[:32]}:{current_rank}"
            # Rank against the original prefix, but use the current active text
            # for selected archive hits just as history_read does.
            if message_count < len(messages) and any(source_id not in active for source_id, _ in page):
                active.update((row["id"], row) for row in records(messages[message_count:], 64000))
            archived = _archived_page_records(db, batches, page, active, canonical=excerpts) if db is not None else {}
            if any(source_id not in active and source_id not in archived for source_id, _ in page):
                raise sqlite3.DatabaseError("Archived history source ID does not match its payload")
            results = [active.get(source_id) or archived[source_id] for source_id, _ in page]
    except (OSError, sqlite3.Error):
        if cursor is not None:
            return stale_cursor
        status = "unavailable"
        next_cursor = None
        results = list(islice(active_matches.values(), _SEARCH_PAGE_SIZE))

    if excerpts:
        excerpts_result = []
        for record in results:
            row = dict(record)
            row.update(_search_excerpt(row.pop("text"), keywords, substring=row["id"] in active))
            excerpts_result.append(row)
        results = excerpts_result
    result = {"results": results, "status": status}
    if next_cursor is not None:
        result["next_cursor"] = next_cursor
    return result


def lookup(
    state: dict,
    runtime: Runtime,
    *,
    query: str | None = None,
    source_id: str | None = None,
    role: str | None = None,
    excerpts: bool = False,
    latest_first: bool = False,
    cursor: str | None = None,
) -> dict:
    if query is not None:
        return _search(state, runtime, query, role, excerpts, cursor, latest_first=latest_first)

    path, owner = scope(runtime)
    batches = reachable(state, owner)
    active = records(state.get("messages", []), 64000)
    history = normalize_task_history(state.get("task_history"))
    status = "unavailable" if history.get("status") == "unavailable" else "available"
    archived = None
    if batches:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                placeholders = ",".join("?" for _ in batches)
                present = db.execute(f"SELECT count(*) FROM batches WHERE id IN ({placeholders})", batches).fetchone()[0]
                if present != len(batches) and status != "unavailable":
                    status = "partially_expired"
                if source_id:
                    row = db.execute(f"SELECT payload FROM sources WHERE batch IN ({placeholders}) AND id=? ORDER BY rowid LIMIT 1", [*batches, source_id]).fetchone()
                    if row:
                        archived = json.loads(row[0])
        except (OSError, sqlite3.Error):
            status = "unavailable"
    elif history.get("scope") is not None and history["scope"] != owner:
        status = "scope_unavailable"
    source = next((row for row in active if row["id"] == source_id), archived)
    return {"results": [source] if source else [], "status": status}
