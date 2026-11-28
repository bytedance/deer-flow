"""Measured operation evidence, independent of checkpoint save intervals."""

import asyncio
import json
import logging
import math
import sqlite3
from contextlib import closing
from pathlib import Path

KEY = "deerflow_trajectory_timing"
OUTCOMES = {"completed", "failed", "timeout", "cancelled", "interrupted"}
logger = logging.getLogger(__name__)


def finite_ms(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 365 * 86400000
        and math.isfinite(value)
    )


class TimingOptions:
    def __init__(self, config=None):
        config = dict(config or {})
        self.enabled = config.get("enabled", True)
        if not isinstance(self.enabled, bool):
            raise ValueError("timing.enabled must be a boolean")
        self.thresholds = dict(config.get("slow_thresholds_ms") or {})
        for key, value in self.thresholds.items():
            if not isinstance(key, str) or not (
                key in {"model", "tool"}
                or (key.startswith(("model:", "tool:")) and key.split(":", 1)[1])
            ):
                raise ValueError(
                    "Slow thresholds use model, tool, model:<name>, tool:<name>"
                )
            if value is not None and (not finite_ms(value) or value == 0):
                raise ValueError(
                    "Slow thresholds must be positive milliseconds or null"
                )

    def project(self, value):
        if not isinstance(value, dict) or not finite_ms(value.get("duration_ms")):
            return None
        if not isinstance(value.get("operation"), str) or value["operation"] not in {
            "tool",
            "model",
        }:
            return None
        if (
            not isinstance(value.get("outcome"), str)
            or value["outcome"] not in OUTCOMES
        ):
            return None
        result = {
            key: value.get(key)
            for key in (
                "span_id",
                "operation",
                "name",
                "duration_ms",
                "outcome",
                "started_at",
                "ended_at",
                "error_type",
                "measurement",
            )
        }
        specific = f"{result['operation']}:{result['name']}"
        key = specific if specific in self.thresholds else result["operation"]
        threshold = self.thresholds.get(key)
        result["slow_threshold_key"] = key if key in self.thresholds else None
        result["slow_threshold_ms"] = threshold
        result["is_slow"] = threshold is not None and result["duration_ms"] >= threshold
        return result


class TimingRepository:
    """One short-lived SQLite connection per operation, safe across child loops."""

    def __init__(self, path=None, options=None):
        self.path = path
        self.options = options or TimingOptions()

    def _path(self):
        if self.path is not None:
            return Path(self.path).resolve()
        from .gateway import timing_path

        return timing_path()

    def append(self, record):
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Records contain identities and timings, never prompts or tool arguments.
        with closing(sqlite3.connect(path, timeout=2)) as conn, conn:
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS timings ("
                "span_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, thread_id TEXT NOT NULL, "
                "execution_id TEXT, message_id TEXT, anchor_id TEXT, parent_checkpoint_id TEXT, data TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS timing_scope ON timings(user_id,thread_id,execution_id)"
            )
            for field in ("message_id", "anchor_id", "parent_checkpoint_id"):
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS timing_{field} ON timings(user_id,thread_id,execution_id,{field})"
                )
            conn.execute(
                "INSERT OR IGNORE INTO timings VALUES(?,?,?,?,?,?,?,?)",
                (
                    record["span_id"],
                    record["user_id"],
                    record["thread_id"],
                    record.get("execution_id"),
                    record.get("message_id"),
                    record.get("anchor_id"),
                    record.get("parent_checkpoint_id"),
                    json.dumps(record, allow_nan=False),
                ),
            )
        path.chmod(0o600)

    async def aappend(self, record):
        # Drain an accepted write even if shutdown cancels the waiter.
        task = asyncio.create_task(asyncio.to_thread(self.append, record))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError:
                    continue
            try:
                task.result()
            except Exception:
                logger.warning("Timing write failed during cancellation", exc_info=True)
            raise

    def _find(self, user, thread, execution, ids, checkpoint_ids=None):
        path = self._path()
        if not path.exists() or (not ids and not checkpoint_ids):
            return []
        matches = list(checkpoint_ids or []) if checkpoint_ids is not None else ids
        field = "parent_checkpoint_id" if checkpoint_ids is not None else "anchor_id"
        ids = ids or [""]
        matches = matches or [""]
        placeholders = ",".join("?" for _ in ids)
        anchors = ",".join("?" for _ in matches)
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as conn:
            rows = conn.execute(
                "SELECT data FROM timings WHERE user_id=? AND thread_id=? AND "
                "execution_id IS ? AND "
                f"(message_id IN ({placeholders}) OR {field} IN ({anchors})) "
                "ORDER BY rowid DESC LIMIT 2001",
                (user, thread, execution, *ids, *matches),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    async def enrich(
        self, rows, user, thread, execution=None, checkpoint_ids=None, *, options=None
    ):
        policy = options or self.options
        ids = list(dict.fromkeys(row.get("id") for row in rows if row.get("id")))
        warnings = []
        try:
            records = await asyncio.to_thread(
                self._find, user, thread, execution, ids, checkpoint_ids
            )
        except (OSError, sqlite3.Error, ValueError):
            logger.warning(
                "Trajectory timing evidence could not be read", exc_info=True
            )
            records = []
            warnings.append("计时证据读取失败，部分耗时可能未记录。")
        if len(records) > 2000:
            warnings.append("关联计时记录较多，仅读取最近 2000 项。")
            records = records[:2000]
        by_message = {}
        for record in records:
            if record.get("message_id"):
                by_message.setdefault(record["message_id"], record)
        output = []
        attached = set()
        for row in rows:
            evidence = by_message.get(row.get("id"), row.get("timing"))
            if row["kind"] in {"assistant", "tool", "timing"}:
                timing = policy.project(evidence)
                if (
                    timing
                    and row.get("model_error_fallback")
                    and timing["outcome"] == "completed"
                ):
                    timing["outcome"] = "failed"
                row["timing"] = timing
            output.append(row)
            for record in records:
                # Exceptions without an output message are visible evidence too.
                if (
                    record.get("has_output", bool(record.get("message_id")))
                    or record.get("anchor_id") != row.get("id")
                    or record["span_id"] in attached
                ):
                    continue
                timing = policy.project(record)
                if timing is None or timing["outcome"] == "completed":
                    continue
                operation = "模型响应" if timing["operation"] == "model" else "工具调用"
                output.append(
                    {
                        "row_id": "timing:" + record["span_id"],
                        "kind": "timing",
                        "id": "timing:" + record["span_id"],
                        "text": f"{operation}未留下完整输出；此项来自实际调用边界的计时记录。",
                        "tool_name": record["name"]
                        if timing["operation"] == "tool"
                        else None,
                        "created_at": record["ended_at"],
                        "timing": timing,
                        "checkpoint_id": record.get("parent_checkpoint_id")
                        or row["checkpoint_id"],
                        "source": "runtime_timing",
                        "anchor_message_id": row["id"],
                        "tool_calls": [],
                        "truncated": False,
                    }
                )
                attached.add(record["span_id"])
        for record in records:
            if (
                record.get("has_output", bool(record.get("message_id")))
                or record["span_id"] in attached
            ):
                continue
            if record.get("parent_checkpoint_id") not in (checkpoint_ids or []):
                continue
            timing = policy.project(record)
            if timing is None or timing["outcome"] == "completed":
                continue
            output.append(
                {
                    "row_id": "timing:" + record["span_id"],
                    "id": "timing:" + record["span_id"],
                    "kind": "timing",
                    "text": "此调用未留下完整输出；此项来自实际调用边界的计时记录。",
                    "created_at": record["ended_at"],
                    "timing": timing,
                    "checkpoint_id": record["parent_checkpoint_id"],
                    "source": "runtime_timing",
                    "anchor_message_id": record.get("anchor_id"),
                    "tool_calls": [],
                    "truncated": False,
                }
            )
        return output, warnings
