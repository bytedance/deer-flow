"""In-process :class:`ThreadMappingStore` (no persistence)."""

from __future__ import annotations

import asyncio
import time
import json
from typing import Any

from deerflow.runtime._db_utils import _COLL_OK,_PREFIX_OK,validate_postgres_identifier,_matches_filter,validate_redis_key_prefix
from deerflow.runtime.thread_mapping.ns import parse_user_threads_namespace, user_id_from_search_prefix
from deerflow.runtime.thread_mapping.types import ThreadMappingItem, ThreadMappingStore


def _mapping_title(value: dict[str, Any]) -> str:
    t = value.get("title")
    return str(t).strip() if t is not None else ""


def _value_with_title(payload: dict[str, Any], title_col: str | None) -> dict[str, Any]:
    val = dict(payload)
    if title_col is not None and str(title_col).strip():
        val["title"] = str(title_col).strip()
    return val


class MemoryThreadMappingStore(ThreadMappingStore):
    """Ephemeral in-process backend."""

    __slots__ = ("_lock", "_rows")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        async with self._lock:
            row = self._rows.get((uid, tid))
        if row is None:
            return None
        return ThreadMappingItem(key=tid, value=dict(row))

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        payload = dict(value)
        payload.setdefault("updated_at", time.time())
        async with self._lock:
            self._rows[(uid, tid)] = payload

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        async with self._lock:
            candidates = [(tid, dict(v)) for (u, tid), v in self._rows.items() if u == uid and _matches_filter(v, filter)]
        candidates.sort(key=lambda x: float(x[1].get("updated_at") or 0), reverse=True)
        slice_ = candidates[offset : offset + limit]
        return [ThreadMappingItem(key=tid, value=val) for tid, val in slice_]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        async with self._lock:
            self._rows.pop((uid, tid), None)

class MongoThreadMappingStore(ThreadMappingStore):
    """One document per mapping: ``user_id``, ``thread_id``, ``payload`` (full mapping dict)."""

    __slots__ = ("_coll",)

    def __init__(self, coll: Any) -> None:
        self._coll = coll

    async def _ensure_indexes(self) -> None:
        await self._coll.create_index([("user_id", 1), ("updated_at", -1)], name="deerflow_utm_user_updated")

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        _ = refresh_ttl
        uid, tid = parse_user_threads_namespace(namespace, key)
        doc = await self._coll.find_one({"user_id": uid, "thread_id": tid})
        if doc is None:
            return None
        payload = doc.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        title_top = doc.get("title")
        title_str = str(title_top).strip() if title_top is not None else ""
        val = _value_with_title(payload, title_str if title_str else None)
        return ThreadMappingItem(key=tid, value=val)

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        _ = index
        uid, tid = parse_user_threads_namespace(namespace, key)
        payload = dict(value)
        payload.setdefault("updated_at", time.time())
        ts = float(payload.get("updated_at") or time.time())
        title_top = _mapping_title(payload)
        await self._coll.replace_one(
            {"user_id": uid, "thread_id": tid},
            {
                "user_id": uid,
                "thread_id": tid,
                "title": title_top,
                "payload": payload,
                "updated_at": ts,
            },
            upsert=True,
        )

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        qfilter: dict[str, Any] = {"user_id": uid}
        if filter:
            for k, v in filter.items():
                qfilter[f"payload.{k}"] = v
        cursor = (
            self._coll.find(qfilter).sort("updated_at", -1).skip(offset).limit(limit)
        )
        out: list[ThreadMappingItem] = []
        async for doc in cursor:
            tid = str(doc.get("thread_id", ""))
            payload = doc.get("payload")
            val = dict(payload) if isinstance(payload, dict) else {}
            title_top = doc.get("title")
            title_str = str(title_top).strip() if title_top is not None else ""
            if title_str:
                val = _value_with_title(val, title_str)
            out.append(ThreadMappingItem(key=tid, value=val))
        return out

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        await self._coll.delete_one({"user_id": uid, "thread_id": tid})

class PostgresThreadMappingStore(ThreadMappingStore):
    """Postgres table layout: (user_id, thread_id, payload JSONB, updated_at)."""

    # No __slots__: parent ThreadMappingStore uses empty slots; omitting __slots__ here
    # gives a normal __dict__ so instance attrs (_sql, _Json, etc.) cannot drift out of sync.

    # from psycopg import sql
    # from psycopg.types.json import Json

    def __init__(self, conn: Any, *, schema: str | None, table: str) -> None:
        try:
            # import psycopg
            from psycopg import sql
            from psycopg.types.json import Json
        except ImportError as e:
            raise ImportError(
                "PostgresMemoryStorage requires psycopg. Install with: uv add 'psycopg[binary]' "
                "or use optional dependency deerflow-harness[memory-db]."
            ) from e

        # self._psycopg = psycopg
        self._sql = sql
        self._Json = Json
        
        tname = validate_postgres_identifier(table, kind="table")
        if schema and str(schema).strip():
            sch = validate_postgres_identifier(schema, kind="schema")
            self._table_sql = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tname))
        else:
            self._table_sql = sql.Identifier(tname)
        self._conn = conn
        self._schema = schema.strip() if schema and str(schema).strip() else None

    async def _ensure_table(self) -> None:
        if self._schema:
            sch_id = self._sql.Identifier(validate_postgres_identifier(self._schema, kind="schema"))
            async with self._conn.cursor() as cur:
                await cur.execute(self._sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sch_id))
            await self._conn.commit()
        ddl = self._sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " user_id TEXT NOT NULL,"
            " thread_id TEXT NOT NULL,"
            " title TEXT NOT NULL DEFAULT '',"
            " payload JSONB NOT NULL,"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
            " PRIMARY KEY (user_id, thread_id)"
            ")"
        ).format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(ddl)
            await cur.execute(
                self._sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''").format(
                    self._table_sql
                )
            )
        await self._conn.commit()

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        _ = refresh_ttl
        uid, tid = parse_user_threads_namespace(namespace, key)
        q = self._sql.SQL("SELECT title, payload FROM {} WHERE user_id = %s AND thread_id = %s").format(
            self._table_sql
        )
        async with self._conn.cursor() as cur:
            await cur.execute(q, (uid, tid))
            row = await cur.fetchone()
        if row is None:
            return None
        title_col, payload = row[0], row[1]
        title_str = str(title_col).strip() if title_col is not None else ""
        if isinstance(payload, dict):
            base = payload
        else:
            base = dict(payload) if payload is not None else {}
        val = _value_with_title(base, title_str if title_str else None)
        return ThreadMappingItem(key=tid, value=val)

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        _ = index
        uid, tid = parse_user_threads_namespace(namespace, key)
        payload = dict(value)
        payload.setdefault("updated_at", time.time())
        title_text = _mapping_title(payload)
        q = self._sql.SQL(
            "INSERT INTO {} (user_id, thread_id, title, payload, updated_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON CONFLICT (user_id, thread_id) "
            "DO UPDATE SET title = EXCLUDED.title, payload = EXCLUDED.payload, updated_at = NOW()"
        ).format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(q, (uid, tid, title_text, self._Json(payload)))
        await self._conn.commit()

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        if filter:
            q = self._sql.SQL(
                "SELECT thread_id, title, payload FROM {} WHERE user_id = %s AND payload @> %s::jsonb "
                "ORDER BY updated_at DESC LIMIT %s OFFSET %s"
            ).format(self._table_sql)
            flt_json = json.dumps(filter, ensure_ascii=False)
            params = (uid, flt_json, limit, offset)
        else:
            q = self._sql.SQL(
                "SELECT thread_id, title, payload FROM {} WHERE user_id = %s "
                "ORDER BY updated_at DESC LIMIT %s OFFSET %s"
            ).format(self._table_sql)
            params = (uid, limit, offset)
        async with self._conn.cursor() as cur:
            await cur.execute(q, params)
            rows = await cur.fetchall()
        out: list[ThreadMappingItem] = []
        for row in rows:
            tid, title_col, payload = row[0], row[1], row[2]
            base = payload if isinstance(payload, dict) else dict(payload or {})
            title_str = str(title_col).strip() if title_col is not None else ""
            val = _value_with_title(base, title_str if title_str else None)
            out.append(ThreadMappingItem(key=str(tid), value=val))
        return out

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        q = self._sql.SQL("DELETE FROM {} WHERE user_id = %s AND thread_id = %s").format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(q, (uid, tid))
        await self._conn.commit()

class RedisThreadMappingStore(ThreadMappingStore):
    """Hash key ``{prefix}:user:{user_id}`` — fields are ``thread_id``, values JSON objects."""

    __slots__ = ("_r", "_prefix")

    def __init__(self, r: Any, *, key_prefix: str) -> None:
        self._r = r
        self._prefix = validate_redis_key_prefix(key_prefix)

    def _user_key(self, user_id: str) -> str:
        return f"{self._prefix}:user:{user_id}"

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        _ = refresh_ttl
        uid, tid = parse_user_threads_namespace(namespace, key)
        raw = await self._r.hget(self._user_key(uid), tid)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        val = json.loads(raw)
        if not isinstance(val, dict):
            val = {}
        return ThreadMappingItem(key=tid, value=val)

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        _ = index
        uid, tid = parse_user_threads_namespace(namespace, key)
        payload = dict(value)
        payload.setdefault("updated_at", time.time())
        await self._r.hset(
            self._user_key(uid),
            tid,
            json.dumps(payload, ensure_ascii=False),
        )

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        data = await self._r.hgetall(self._user_key(uid))
        items: list[tuple[str, dict[str, Any], float]] = []
        for fk, raw in data.items():
            tid = fk.decode("utf-8") if isinstance(fk, bytes) else str(fk)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                val = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(val, dict):
                continue
            if not _matches_filter(val, filter):
                continue
            ts = float(val.get("updated_at") or 0)
            items.append((tid, val, ts))
        items.sort(key=lambda x: x[2], reverse=True)
        slice_ = items[offset : offset + limit]
        return [ThreadMappingItem(key=tid, value=dict(v)) for tid, v, _ in slice_]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        await self._r.hdel(self._user_key(uid), tid)

class SqliteThreadMappingStore(ThreadMappingStore):
    """SQLite via aiosqlite."""

    __slots__ = ("_conn", "_table")

    def __init__(self, conn: Any, *, table: str) -> None:
        self._conn = conn
        self._table = validate_postgres_identifier(table, kind="sqlite table")

    async def _ensure_table(self) -> None:
        await self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{self._table}" (
                user_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, thread_id)
            )
            """
        )
        cur = await self._conn.execute(f'PRAGMA table_info("{self._table}")')
        info = await cur.fetchall()
        await cur.close()
        colnames = {row[1] for row in info}
        if "title" not in colnames:
            await self._conn.execute(
                f'ALTER TABLE "{self._table}" ADD COLUMN title TEXT NOT NULL DEFAULT \'\''
            )
        await self._conn.commit()

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        _ = refresh_ttl
        uid, tid = parse_user_threads_namespace(namespace, key)
        cur = await self._conn.execute(
            f'SELECT title, payload FROM "{self._table}" WHERE user_id = ? AND thread_id = ?',
            (uid, tid),
        )
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            return None
        title_col, raw = row[0], row[1]
        title_str = str(title_col).strip() if title_col is not None else ""
        base = json.loads(raw)
        if not isinstance(base, dict):
            base = {}
        val = _value_with_title(base, title_str if title_str else None)
        return ThreadMappingItem(key=tid, value=val)

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        _ = index
        uid, tid = parse_user_threads_namespace(namespace, key)
        payload = dict(value)
        payload.setdefault("updated_at", time.time())
        title_text = _mapping_title(payload)
        body = json.dumps(payload, ensure_ascii=False)
        now = float(payload.get("updated_at") or time.time())
        await self._conn.execute(
            f'''
            INSERT INTO "{self._table}" (user_id, thread_id, title, payload, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, thread_id) DO UPDATE SET
              title = excluded.title,
              payload = excluded.payload,
              updated_at = excluded.updated_at
            ''',
            (uid, tid, title_text, body, now),
        )
        await self._conn.commit()

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        cur = await self._conn.execute(
            f'SELECT thread_id, title, payload, updated_at FROM "{self._table}" WHERE user_id = ? ORDER BY updated_at DESC',
            (uid,),
        )
        rows = await cur.fetchall()
        await cur.close()
        out: list[ThreadMappingItem] = []
        for tid, title_col, raw, _ts in rows:
            base = json.loads(raw)
            if not isinstance(base, dict):
                base = {}
            title_str = str(title_col).strip() if title_col is not None else ""
            val = _value_with_title(base, title_str if title_str else None)
            if _matches_filter(val, filter):
                out.append(ThreadMappingItem(key=str(tid), value=val))
        return out[offset : offset + limit]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        await self._conn.execute(
            f'DELETE FROM "{self._table}" WHERE user_id = ? AND thread_id = ?',
            (uid, tid),
        )
        await self._conn.commit()