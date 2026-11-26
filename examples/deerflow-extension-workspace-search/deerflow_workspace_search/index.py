"""Rebuildable SQL projection of the host's visible transcript.

No checkpoint, filesystem conversation scan or streaming-token hook is needed.
Refresh jobs read through an explicitly owner-bound host capability. A request
waits briefly for its refresh, returning indexing=True while historical data is
backfilled. Partial refreshes are never reported as a complete empty result.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from deerflow_extension_api.search import SearchCorpus, SearchMessage, SearchPage, SearchThread
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, and_, delete, insert, or_, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

metadata = MetaData()
documents = Table(
    "extension_workspace_search_documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("owner", String(64), nullable=False, index=True),
    Column("thread_id", String(64), nullable=False, index=True),
    Column("message_id", Text, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("normalized", Text, nullable=False),
    Column("payload", Text, nullable=False),
)
revisions = Table(
    "extension_workspace_search_revisions",
    metadata,
    Column("owner", String(64), primary_key=True),
    Column("thread_id", String(64), primary_key=True),
    Column("revision", String(64), nullable=False),
)
fts_state = Table(
    "extension_workspace_search_fts_state",
    metadata,
    Column("key", String(32), primary_key=True),
    Column("value", String(16), nullable=False),
)
_FTS = "extension_workspace_search_fts"


class WorkspaceSearchIndex:
    def __init__(self, *, path: str = ".deer-flow/workspace-search.db", wait_seconds: float = 1.0):
        self.path = path
        self.wait_seconds = wait_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        self._engine = None
        self._owns_engine = False
        self._sf = None
        self._fts = False

    async def start(self, deps):
        self._sf = deps.session_factory
        if self._sf is None:
            await asyncio.to_thread(Path(self.path).absolute().parent.mkdir, parents=True, exist_ok=True)
            self._engine = create_async_engine(f"sqlite+aiosqlite:///{self.path}")
            self._sf = async_sessionmaker(self._engine, expire_on_commit=False)
            self._owns_engine = True
        else:
            self._engine = self._sf.kw["bind"]
        async with self._engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        if self._engine.dialect.name == "sqlite":
            # Older SQLite distributions may lack FTS5/trigram; literal matching
            # remains correct, including one/two-character Chinese queries.
            from sqlalchemy.exc import OperationalError

            try:
                async with self._engine.begin() as connection:
                    existed = await connection.scalar(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": _FTS})
                    state = await connection.scalar(select(fts_state.c.value).where(fts_state.c.key == "projection"))
                    await connection.execute(text(f"CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS} USING fts5(docid UNINDEXED, normalized, tokenize='trigram')"))
                    if not existed or state != "clean":
                        await connection.execute(text(f"DELETE FROM {_FTS}"))
                        await connection.execute(text(f"INSERT INTO {_FTS}(docid, normalized) SELECT id, normalized FROM {documents.name}"))
                    await connection.execute(text(f"INSERT INTO {fts_state.name} (key, value) VALUES ('projection', 'clean') ON CONFLICT(key) DO UPDATE SET value='clean'"))
                self._fts = True
            except OperationalError as exc:
                if "no such module" not in str(exc) and "no such tokenizer" not in str(exc):
                    raise
        elif self._engine.dialect.name == "postgresql":
            async with self._engine.begin() as connection:
                available = await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"))
                if available:
                    await connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_workspace_search_trgm ON {documents.name} USING gin (normalized gin_trgm_ops)"))

    async def stop(self):
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        if self._owns_engine and self._engine is not None:
            await self._engine.dispose()
        self._sf = None

    async def _replace(self, owner, thread, revision, messages):
        async with self._sf() as session, session.begin():
            if self._engine.dialect.name == "sqlite" and not self._fts:
                await session.execute(text(f"INSERT INTO {fts_state.name} (key, value) VALUES ('projection', 'dirty') ON CONFLICT(key) DO UPDATE SET value='dirty'"))
            where = and_(documents.c.owner == owner, documents.c.thread_id == thread.thread_id)
            if self._fts:
                await session.execute(text(f"DELETE FROM {_FTS} WHERE docid IN (SELECT id FROM {documents.name} WHERE owner=:owner AND thread_id=:thread_id)"), {"owner": owner, "thread_id": thread.thread_id})
            await session.execute(delete(documents).where(where))
            if messages:
                await session.execute(
                    insert(documents),
                    [dict(owner=owner, thread_id=thread.thread_id, message_id=m.message_id, seq=m.seq, updated_at=thread.updated_at, normalized=m.text.casefold(), payload=json.dumps(asdict(m), ensure_ascii=False)) for m in messages],
                )
                if self._fts:
                    await session.execute(text(f"INSERT INTO {_FTS}(docid, normalized) SELECT id, normalized FROM {documents.name} WHERE owner=:owner AND thread_id=:thread_id"), {"owner": owner, "thread_id": thread.thread_id})
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            upsert = pg_insert if self._engine.dialect.name == "postgresql" else sqlite_insert
            await session.execute(upsert(revisions).values(owner=owner, thread_id=thread.thread_id, revision=revision).on_conflict_do_update(index_elements=["owner", "thread_id"], set_={"revision": revision}))

    async def _refresh(self, corpus: SearchCorpus):
        threads = await corpus.threads()
        async with self._sf() as session:
            known = dict((await session.execute(select(revisions.c.thread_id, revisions.c.revision).where(revisions.c.owner == corpus.user_id))).all())
        for thread in threads:
            revision = await corpus.revision(thread)
            if revision is None or known.get(thread.thread_id) == revision:
                continue
            messages: dict[str, SearchMessage] = {}
            before = None
            while True:
                page = await corpus.messages(thread, before_seq=before)
                # Backward pages: keep the latest visible version of each ID.
                for message in reversed(page.items):
                    messages.setdefault(message.message_id, message)
                if page.before_seq is None:
                    break
                if before is not None and page.before_seq >= before:
                    raise RuntimeError("Search backfill cursor did not advance")
                before = page.before_seq
            if await corpus.revision(thread) != revision:
                # A concurrent run changed this thread; retry on the next request.
                return False
            await self._replace(corpus.user_id, thread, revision, messages.values())
        live = {thread.thread_id for thread in threads}
        for removed in set(known) - live:
            async with self._sf() as session, session.begin():
                if self._engine.dialect.name == "sqlite" and not self._fts:
                    await session.execute(text(f"INSERT INTO {fts_state.name} (key, value) VALUES ('projection', 'dirty') ON CONFLICT(key) DO UPDATE SET value='dirty'"))
                if self._fts:
                    await session.execute(text(f"DELETE FROM {_FTS} WHERE docid IN (SELECT id FROM {documents.name} WHERE owner=:owner AND thread_id=:thread_id)"), {"owner": corpus.user_id, "thread_id": removed})
                await session.execute(delete(documents).where(documents.c.owner == corpus.user_id, documents.c.thread_id == removed))
                await session.execute(delete(revisions).where(revisions.c.owner == corpus.user_id, revisions.c.thread_id == removed))
        return True

    async def search(self, corpus: SearchCorpus, *, query: str, threads: tuple[SearchThread, ...], limit: int, cursor: str | None = None) -> SearchPage:
        if self._sf is None:
            raise RuntimeError("Workspace search index is unavailable")
        task = self._tasks.get(corpus.user_id)
        if task is None:
            # Retain completed backfills for the next poll, but bound abandoned
            # users' task handles and consume background exceptions.
            for owner, previous in list(self._tasks.items()):
                if len(self._tasks) < 64:
                    break
                if previous.done():
                    del self._tasks[owner]
            task = asyncio.create_task(self._refresh(corpus))
            task.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
            self._tasks[corpus.user_id] = task
        try:
            complete = await asyncio.wait_for(asyncio.shield(task), timeout=self.wait_seconds)
        except TimeoutError:
            return SearchPage(indexing=True)
        finally:
            if task.done() and self._tasks.get(corpus.user_id) is task:
                del self._tasks[corpus.user_id]
        if not complete:
            return SearchPage(indexing=True)
        if not threads:
            return SearchPage()
        normalized = query.strip().casefold()
        # The host binds cursors to the filter set. Live thread membership may
        # change between pages without invalidating an otherwise valid cursor.
        scope = hashlib.sha256(json.dumps([corpus.user_id, normalized]).encode()).hexdigest()
        statement = select(documents).where(documents.c.owner == corpus.user_id, documents.c.normalized.contains(normalized, autoescape=True))
        if self._fts and len(normalized) >= 3:
            statement = statement.where(documents.c.id.in_(text(f"SELECT docid FROM {_FTS} WHERE {_FTS} MATCH :match"))).params(match='"' + normalized.replace('"', '""') + '"')
        if cursor:
            try:
                saved_scope, updated, thread_id, seq, message_id = json.loads(base64.urlsafe_b64decode(cursor))
                if saved_scope != scope or not isinstance(seq, int):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid search cursor") from exc
            statement = statement.where(
                or_(
                    documents.c.updated_at < updated,
                    and_(documents.c.updated_at == updated, documents.c.thread_id < thread_id),
                    and_(documents.c.updated_at == updated, documents.c.thread_id == thread_id, documents.c.seq < seq),
                    and_(documents.c.updated_at == updated, documents.c.thread_id == thread_id, documents.c.seq == seq, documents.c.message_id < message_id),
                )
            )
        statement = statement.order_by(documents.c.updated_at.desc(), documents.c.thread_id.desc(), documents.c.seq.desc(), documents.c.message_id.desc()).limit(limit + 1)
        async with self._sf() as session:
            rows = []
            ids = [thread.thread_id for thread in threads]
            # Keep SQL parameter counts below SQLite's portable limit. Each
            # batch contributes only its top page; merge by the same total order.
            for offset in range(0, len(ids), 250):
                batch = statement.where(documents.c.thread_id.in_(ids[offset : offset + 250]))
                rows.extend((await session.execute(batch)).mappings().all())
                rows.sort(key=lambda row: (row["updated_at"], row["thread_id"], row["seq"], row["message_id"]), reverse=True)
                rows = rows[: limit + 1]
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if more:
            last = rows[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps([scope, last["updated_at"], last["thread_id"], last["seq"], last["message_id"]]).encode()).decode()
        return SearchPage(tuple(SearchMessage(**json.loads(row["payload"])) for row in rows), next_cursor)
