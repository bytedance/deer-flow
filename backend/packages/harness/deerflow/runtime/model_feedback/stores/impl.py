"""Concrete :class:`ModelFeedbackStore` backends."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from deerflow.runtime._db_utils import validate_postgres_identifier
from deerflow.runtime.model_feedback.names import normalize_feedback_model_name
from deerflow.runtime.model_feedback.types import ModelFeedbackRow

_ZERO = {
    "call_count": 0,
    "success_count": 0,
    "failure_count": 0,
    "positive_feedback_count": 0,
    "negative_feedback_count": 0,
}


def _nonneg(name: str, v: int) -> int:
    if v < 0:
        raise ValueError(f"{name} must be non-negative")
    return v


class MemoryModelFeedbackStore:
    """In-process counters (lost on restart)."""

    __slots__ = ("_lock", "_rows")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: dict[str, dict[str, int | float]] = {}

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        name = normalize_feedback_model_name(model_name)
        _nonneg("call_count", call_count)
        _nonneg("success_count", success_count)
        _nonneg("failure_count", failure_count)
        _nonneg("positive_feedback_count", positive_feedback_count)
        _nonneg("negative_feedback_count", negative_feedback_count)
        now = time.time()
        async with self._lock:
            row = self._rows.setdefault(name, {**_ZERO, "updated_at": now})
            row["call_count"] = int(row["call_count"]) + call_count
            row["success_count"] = int(row["success_count"]) + success_count
            row["failure_count"] = int(row["failure_count"]) + failure_count
            row["positive_feedback_count"] = int(row["positive_feedback_count"]) + positive_feedback_count
            row["negative_feedback_count"] = int(row["negative_feedback_count"]) + negative_feedback_count
            row["updated_at"] = now

    async def list_rows(self) -> list[ModelFeedbackRow]:
        async with self._lock:
            items = [(k, dict(v)) for k, v in self._rows.items()]
        items.sort(key=lambda x: x[0])
        out: list[ModelFeedbackRow] = []
        for name, d in items:
            out.append(
                ModelFeedbackRow(
                    model_name=name,
                    call_count=int(d.get("call_count", 0)),
                    success_count=int(d.get("success_count", 0)),
                    failure_count=int(d.get("failure_count", 0)),
                    positive_feedback_count=int(d.get("positive_feedback_count", 0)),
                    negative_feedback_count=int(d.get("negative_feedback_count", 0)),
                    updated_at=float(d["updated_at"]) if d.get("updated_at") is not None else None,
                )
            )
        return out


class SqliteModelFeedbackStore:
    __slots__ = ("_conn", "_table")

    def __init__(self, conn: Any, *, table: str) -> None:
        self._conn = conn
        self._table = validate_postgres_identifier(table, kind="sqlite table")

    async def _ensure_table(self) -> None:
        await self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{self._table}" (
                model_name TEXT NOT NULL PRIMARY KEY,
                call_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                positive_feedback_count INTEGER NOT NULL DEFAULT 0,
                negative_feedback_count INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._conn.commit()

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        name = normalize_feedback_model_name(model_name)
        dc = _nonneg("call_count", call_count)
        ds = _nonneg("success_count", success_count)
        df = _nonneg("failure_count", failure_count)
        dp = _nonneg("positive_feedback_count", positive_feedback_count)
        dn = _nonneg("negative_feedback_count", negative_feedback_count)
        now = time.time()
        await self._conn.execute(
            f'''
            INSERT INTO "{self._table}"
              (model_name, call_count, success_count, failure_count,
               positive_feedback_count, negative_feedback_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_name) DO UPDATE SET
              call_count = call_count + excluded.call_count,
              success_count = success_count + excluded.success_count,
              failure_count = failure_count + excluded.failure_count,
              positive_feedback_count = positive_feedback_count + excluded.positive_feedback_count,
              negative_feedback_count = negative_feedback_count + excluded.negative_feedback_count,
              updated_at = excluded.updated_at
            ''',
            (name, dc, ds, df, dp, dn, now),
        )
        await self._conn.commit()

    async def list_rows(self) -> list[ModelFeedbackRow]:
        cur = await self._conn.execute(
            f'''
            SELECT model_name, call_count, success_count, failure_count,
                   positive_feedback_count, negative_feedback_count, updated_at
            FROM "{self._table}" ORDER BY model_name
            '''
        )
        rows = await cur.fetchall()
        await cur.close()
        out: list[ModelFeedbackRow] = []
        for r in rows:
            out.append(
                ModelFeedbackRow(
                    model_name=str(r[0]),
                    call_count=int(r[1]),
                    success_count=int(r[2]),
                    failure_count=int(r[3]),
                    positive_feedback_count=int(r[4]),
                    negative_feedback_count=int(r[5]),
                    updated_at=float(r[6]) if r[6] is not None else None,
                )
            )
        return out


class PostgresModelFeedbackStore:
    __slots__ = ("_conn", "_schema", "_sql", "_table_sql")

    def __init__(self, conn: Any, *, schema: str | None, table: str) -> None:
        from psycopg import sql

        self._sql = sql
        tname = validate_postgres_identifier(table, kind="table")
        self._schema = schema.strip() if schema and str(schema).strip() else None
        if self._schema:
            sch = validate_postgres_identifier(self._schema, kind="schema")
            self._table_sql = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tname))
        else:
            self._table_sql = sql.Identifier(tname)
        self._conn = conn

    async def _ensure_table(self) -> None:
        if self._schema:
            sch_id = self._sql.Identifier(validate_postgres_identifier(self._schema, kind="schema"))
            async with self._conn.cursor() as cur:
                await cur.execute(self._sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sch_id))
            await self._conn.commit()
        ddl = self._sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " model_name TEXT NOT NULL PRIMARY KEY,"
            " call_count BIGINT NOT NULL DEFAULT 0,"
            " success_count BIGINT NOT NULL DEFAULT 0,"
            " failure_count BIGINT NOT NULL DEFAULT 0,"
            " positive_feedback_count BIGINT NOT NULL DEFAULT 0,"
            " negative_feedback_count BIGINT NOT NULL DEFAULT 0,"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ).format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(ddl)
        await self._conn.commit()

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        name = normalize_feedback_model_name(model_name)
        dc = _nonneg("call_count", call_count)
        ds = _nonneg("success_count", success_count)
        df = _nonneg("failure_count", failure_count)
        dp = _nonneg("positive_feedback_count", positive_feedback_count)
        dn = _nonneg("negative_feedback_count", negative_feedback_count)
        ins = self._sql.SQL(
            "INSERT INTO {} AS target (model_name, call_count, success_count, failure_count, "
            "positive_feedback_count, negative_feedback_count, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, NOW()) "
            "ON CONFLICT (model_name) DO UPDATE SET "
            "call_count = target.call_count + EXCLUDED.call_count, "
            "success_count = target.success_count + EXCLUDED.success_count, "
            "failure_count = target.failure_count + EXCLUDED.failure_count, "
            "positive_feedback_count = target.positive_feedback_count + EXCLUDED.positive_feedback_count, "
            "negative_feedback_count = target.negative_feedback_count + EXCLUDED.negative_feedback_count, "
            "updated_at = NOW()"
        ).format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(ins, (name, dc, ds, df, dp, dn))
        await self._conn.commit()

    async def list_rows(self) -> list[ModelFeedbackRow]:
        q = self._sql.SQL(
            "SELECT model_name, call_count, success_count, failure_count, "
            "positive_feedback_count, negative_feedback_count, "
            "EXTRACT(EPOCH FROM updated_at) FROM {} ORDER BY model_name"
        ).format(self._table_sql)
        async with self._conn.cursor() as cur:
            await cur.execute(q)
            rows = await cur.fetchall()
        out: list[ModelFeedbackRow] = []
        for r in rows:
            ts = r[6]
            updated = float(ts) if ts is not None else None
            out.append(
                ModelFeedbackRow(
                    model_name=str(r[0]),
                    call_count=int(r[1]),
                    success_count=int(r[2]),
                    failure_count=int(r[3]),
                    positive_feedback_count=int(r[4]),
                    negative_feedback_count=int(r[5]),
                    updated_at=updated,
                )
            )
        return out


class MongoModelFeedbackStore:
    __slots__ = ("_coll",)

    def __init__(self, coll: Any) -> None:
        self._coll = coll

    async def _ensure_indexes(self) -> None:
        await self._coll.create_index("model_name", unique=True, name="deerflow_model_feedback_name")

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        name = normalize_feedback_model_name(model_name)
        _nonneg("call_count", call_count)
        _nonneg("success_count", success_count)
        _nonneg("failure_count", failure_count)
        _nonneg("positive_feedback_count", positive_feedback_count)
        _nonneg("negative_feedback_count", negative_feedback_count)
        inc: dict[str, int] = {}
        if call_count:
            inc["call_count"] = call_count
        if success_count:
            inc["success_count"] = success_count
        if failure_count:
            inc["failure_count"] = failure_count
        if positive_feedback_count:
            inc["positive_feedback_count"] = positive_feedback_count
        if negative_feedback_count:
            inc["negative_feedback_count"] = negative_feedback_count
        if not inc:
            return
        now = time.time()
        await self._coll.update_one(
            {"model_name": name},
            {"$inc": inc, "$set": {"updated_at": now, "model_name": name}},
            upsert=True,
        )

    async def list_rows(self) -> list[ModelFeedbackRow]:
        out: list[ModelFeedbackRow] = []
        cursor = self._coll.find({}).sort("model_name", 1)
        async for doc in cursor:
            out.append(
                ModelFeedbackRow(
                    model_name=str(doc.get("model_name", "")),
                    call_count=int(doc.get("call_count", 0)),
                    success_count=int(doc.get("success_count", 0)),
                    failure_count=int(doc.get("failure_count", 0)),
                    positive_feedback_count=int(doc.get("positive_feedback_count", 0)),
                    negative_feedback_count=int(doc.get("negative_feedback_count", 0)),
                    updated_at=float(doc["updated_at"]) if doc.get("updated_at") is not None else None,
                )
            )
        return out


def _redis_model_key(prefix: str, model_name: str) -> str:
    enc = base64.urlsafe_b64encode(model_name.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{prefix}:c:{enc}"


class RedisModelFeedbackStore:
    __slots__ = ("_prefix", "_r")

    def __init__(self, r: Any, *, key_prefix: str) -> None:
        from deerflow.runtime._db_utils import validate_redis_key_prefix

        self._r = r
        self._prefix = validate_redis_key_prefix(key_prefix)

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        name = normalize_feedback_model_name(model_name)
        dc = _nonneg("call_count", call_count)
        ds = _nonneg("success_count", success_count)
        df = _nonneg("failure_count", failure_count)
        dp = _nonneg("positive_feedback_count", positive_feedback_count)
        dn = _nonneg("negative_feedback_count", negative_feedback_count)
        if not (dc or ds or df or dp or dn):
            return
        key = _redis_model_key(self._prefix, name)
        now = time.time()
        pipe = self._r.pipeline(transaction=True)
        pipe.hsetnx(key, "model_name", name)
        if dc:
            pipe.hincrby(key, "call_count", dc)
        if ds:
            pipe.hincrby(key, "success_count", ds)
        if df:
            pipe.hincrby(key, "failure_count", df)
        if dp:
            pipe.hincrby(key, "positive_feedback_count", dp)
        if dn:
            pipe.hincrby(key, "negative_feedback_count", dn)
        pipe.hset(key, "updated_at", str(now))
        await pipe.execute()

    async def list_rows(self) -> list[ModelFeedbackRow]:
        out: list[ModelFeedbackRow] = []
        async for key in self._r.scan_iter(match=f"{self._prefix}:c:*"):
            raw = await self._r.hgetall(key)
            if not raw:
                continue
            mn = raw.get("model_name") or raw.get(b"model_name")
            if isinstance(mn, bytes):
                mn = mn.decode("utf-8", errors="replace")

            def _g(field: str) -> int:
                v = raw.get(field) or raw.get(field.encode())
                if v is None:
                    return 0
                if isinstance(v, bytes):
                    v = v.decode("ascii", errors="replace")
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return 0

            def _gf(field: str) -> float | None:
                v = raw.get(field) or raw.get(field.encode())
                if v is None:
                    return None
                if isinstance(v, bytes):
                    v = v.decode("ascii", errors="replace")
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            out.append(
                ModelFeedbackRow(
                    model_name=str(mn or ""),
                    call_count=_g("call_count"),
                    success_count=_g("success_count"),
                    failure_count=_g("failure_count"),
                    positive_feedback_count=_g("positive_feedback_count"),
                    negative_feedback_count=_g("negative_feedback_count"),
                    updated_at=_gf("updated_at"),
                )
            )
        out.sort(key=lambda r: r.model_name)
        return out
