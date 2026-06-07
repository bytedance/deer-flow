"""SQLite-backed store for raw messages and filtered intel.

Design (see chat decisions 2026-06-07):
- Single DB file (``output/intel.db``); ONE pair of tables PER data source so
  different sources live side by side without colliding. Table names are
  ``<source>_intel_raw`` and ``<source>_intel_filtered`` (e.g.
  ``telegram_intel_raw`` / ``telegram_intel_filtered``; a future Weibo source
  would use ``weibo_intel_raw`` / ``weibo_intel_filtered``).
- Both tables carry a ``day`` partition column (``YYYY-MM-DD``) + index, so
  "by day" queries are a simple ``WHERE day = ?``.
- Dedupe is ``(day, id)``: the same record stored once PER day, but kept
  across days (each day keeps its own snapshot). Implemented with a composite
  PRIMARY KEY + ``INSERT OR IGNORE``.

This store is written to by ``Exporter`` ALONGSIDE the legacy JSON/CSV files
(dual-write), so existing downstream consumers keep working unchanged.

Legacy tables ``raw_messages`` / ``filtered_intel`` (pre-multi-source naming)
are auto-migrated into the telegram tables on first open.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tg_crawler")

# Legacy → new table-name mapping (only meaningful for source="telegram").
_LEGACY_RAW_TABLE = "raw_messages"
_LEGACY_FILTERED_TABLE = "filtered_intel"

_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SQLiteStore:
    """Per-source SQLite store with day partitioning.

    Args:
        db_path: path to the .db file (shared across sources).
        source: data-source name; drives table names. Must match
            ``^[a-z][a-z0-9_]*$`` (e.g. "telegram", "weibo", "twitter").
    """

    def __init__(self, db_path: str, *, source: str = "telegram"):
        source = (source or "telegram").lower()
        if not _SOURCE_RE.match(source):
            raise ValueError(
                f"invalid source name {source!r}; must match [a-z][a-z0-9_]*"
            )
        self._source = source
        self._raw_table = f"{source}_intel_raw"
        self._filtered_table = f"{source}_intel_filtered"

        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()
        if self._source == "telegram":
            self._migrate_legacy_tables()

    # ---------- accessors ----------

    @property
    def source(self) -> str:
        return self._source

    @property
    def raw_table(self) -> str:
        return self._raw_table

    @property
    def filtered_table(self) -> str:
        return self._filtered_table

    # ---------- schema ----------

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._raw_table} (
                day          TEXT NOT NULL,
                identity     TEXT NOT NULL,
                group_name   TEXT,
                subdir       TEXT DEFAULT '',
                msg_date     TEXT,
                payload      TEXT NOT NULL,
                inserted_at  TEXT NOT NULL,
                PRIMARY KEY (day, identity)
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._raw_table}_day "
            f"ON {self._raw_table}(day)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._raw_table}_group "
            f"ON {self._raw_table}(group_name)"
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._filtered_table} (
                day             TEXT NOT NULL,
                id              TEXT NOT NULL,
                source_platform TEXT,
                source_group    TEXT,
                msg_date        TEXT,
                sender_id       INTEGER,
                sender_name     TEXT,
                sender_username TEXT,
                original_text   TEXT,
                risk_type       TEXT,
                risk_level      TEXT,
                entities        TEXT,
                summary         TEXT,
                llm_model       TEXT,
                source_url      TEXT,
                suffix          TEXT DEFAULT '',
                inserted_at     TEXT NOT NULL,
                PRIMARY KEY (day, id)
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._filtered_table}_day "
            f"ON {self._filtered_table}(day)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._filtered_table}_risk "
            f"ON {self._filtered_table}(risk_level)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._filtered_table}_platform "
            f"ON {self._filtered_table}(source_platform)"
        )
        self._conn.commit()

    def _table_exists(self, name: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cur.fetchone() is not None

    def _migrate_legacy_tables(self) -> None:
        """Copy rows from the old single-source tables into the telegram
        tables, then drop the legacy tables. Idempotent: once the legacy
        tables are gone this is a no-op. Dedupe via INSERT OR IGNORE.
        """
        moved = 0
        if self._table_exists(_LEGACY_RAW_TABLE):
            self._conn.execute(
                f"INSERT OR IGNORE INTO {self._raw_table} "
                f"SELECT * FROM {_LEGACY_RAW_TABLE}"
            )
            moved += 1
            self._conn.execute(f"DROP TABLE {_LEGACY_RAW_TABLE}")
        if self._table_exists(_LEGACY_FILTERED_TABLE):
            self._conn.execute(
                f"INSERT OR IGNORE INTO {self._filtered_table} "
                f"SELECT * FROM {_LEGACY_FILTERED_TABLE}"
            )
            moved += 1
            self._conn.execute(f"DROP TABLE {_LEGACY_FILTERED_TABLE}")
        if moved:
            self._conn.commit()
            logger.info(
                "migrated %d legacy table(s) into %s_intel_*", moved, self._source
            )

    # ---------- writes ----------

    @staticmethod
    def _raw_identity(record: dict) -> Optional[str]:
        if not isinstance(record, dict):
            return None
        for k in ("msg_id", "tweet_id"):
            if record.get(k) is not None:
                return f"{k}:{record[k]}"
        return None

    def insert_raw(
        self,
        messages: list[dict],
        *,
        group_name: str,
        subdir: str = "",
        day: Optional[str] = None,
    ) -> int:
        """Insert raw messages for ``day``. Dedupes on (day, identity).
        Returns the number of NEW rows actually inserted.
        """
        if not messages:
            return 0
        day = day or self._today()
        now = datetime.now().isoformat()
        rows = []
        for i, msg in enumerate(messages):
            identity = self._raw_identity(msg)
            if identity is None:
                identity = f"_noid:{now}:{i}"
            rows.append((
                day,
                identity,
                msg.get("group_name", group_name),
                subdir,
                msg.get("date"),
                json.dumps(msg, ensure_ascii=False),
                now,
            ))

        before = self._conn.total_changes
        self._conn.executemany(
            f"""
            INSERT OR IGNORE INTO {self._raw_table}
                (day, identity, group_name, subdir, msg_date, payload, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def insert_filtered(
        self,
        records: list[dict],
        *,
        suffix: str = "",
        day: Optional[str] = None,
    ) -> int:
        """Insert filtered intel records for ``day``. Dedupes on (day, id).
        Returns number of NEW rows inserted.
        """
        if not records:
            return 0
        day = day or self._today()
        now = datetime.now().isoformat()
        rows = []
        for r in records:
            entities = r.get("entities")
            if not isinstance(entities, str):
                entities = json.dumps(entities or {}, ensure_ascii=False)
            rows.append((
                day,
                r.get("id", ""),
                r.get("source_platform", self._source),
                r.get("source_group", ""),
                r.get("date"),
                r.get("sender_id", 0),
                r.get("sender_name", ""),
                r.get("sender_username", ""),
                r.get("original_text", ""),
                r.get("risk_type", ""),
                r.get("risk_level", ""),
                entities,
                r.get("summary", ""),
                r.get("llm_model", ""),
                r.get("source_url", ""),
                suffix,
                now,
            ))

        before = self._conn.total_changes
        self._conn.executemany(
            f"""
            INSERT OR IGNORE INTO {self._filtered_table}
                (day, id, source_platform, source_group, msg_date,
                 sender_id, sender_name, sender_username, original_text,
                 risk_type, risk_level, entities, summary, llm_model,
                 source_url, suffix, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    # ---------- reads ----------

    def count_filtered(self, *, day: Optional[str] = None) -> int:
        cur = self._conn.cursor()
        if day:
            cur.execute(
                f"SELECT COUNT(*) FROM {self._filtered_table} WHERE day = ?", (day,)
            )
        else:
            cur.execute(f"SELECT COUNT(*) FROM {self._filtered_table}")
        return int(cur.fetchone()[0])

    def count_raw(self, *, day: Optional[str] = None) -> int:
        cur = self._conn.cursor()
        if day:
            cur.execute(
                f"SELECT COUNT(*) FROM {self._raw_table} WHERE day = ?", (day,)
            )
        else:
            cur.execute(f"SELECT COUNT(*) FROM {self._raw_table}")
        return int(cur.fetchone()[0])

    # ---------- lifecycle ----------

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
