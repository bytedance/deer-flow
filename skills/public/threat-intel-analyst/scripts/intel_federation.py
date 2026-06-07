"""IntelFederation — query intel across multiple independent SQLite DBs.

Decision (2026-06-07): each data-source owner keeps their OWN SQLite db, all
sharing the SAME schema (``<source>_intel_filtered`` / ``<source>_intel_raw``,
day-partitioned). This layer registers those DBs and runs UNIONed queries
across them so the analyst skill (and DeerFlow) can ask one question and get a
combined answer — without anyone touching raw SQL or knowing the table layout.

How it works:
- Each registered db is ATTACHed under an alias into a single in-memory conn.
- For each attached db we discover its ``*_intel_filtered`` tables and build a
  normalized SELECT that prefixes a ``__db`` column (which db) on top of the
  per-row ``source_platform``. All of these are UNION ALL'd into one view.
- Read-only (``mode=ro``). Never writes. Missing/locked DBs are skipped with a
  warning rather than failing the whole query.

Registry file (yaml), default ``federation.yaml`` next to this module or
pointed to by env ``INTEL_FEDERATION_REGISTRY``:

    databases:
      - alias: telegram
        path: ../tg-intel-crawler/output/intel.db
        owner: me
      - alias: weibo
        path: /abs/path/to/teammateA/weibo.db
        owner: teammateA
      - alias: forum
        path: /abs/path/to/teammateB/forum.db
        owner: teammateB
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("intel_federation")

# Canonical column set every <source>_intel_filtered table must expose.
FILTERED_COLUMNS = [
    "day", "id", "source_platform", "source_group", "msg_date",
    "sender_id", "sender_name", "sender_username", "original_text",
    "risk_type", "risk_level", "entities", "summary", "llm_model",
    "source_url", "suffix",
]


@dataclass
class DBEntry:
    alias: str
    path: Path
    owner: str = ""


class IntelFederation:
    """Unioned read-only view over many intel SQLite DBs."""

    def __init__(self, entries: list[DBEntry]):
        self._entries = entries
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._attached: list[str] = []
        self._select_parts: list[str] = []
        self._build()

    # ---------- construction ----------

    @classmethod
    def from_registry(cls, registry_path: str | None = None) -> "IntelFederation":
        path = (
            registry_path
            or os.environ.get("INTEL_FEDERATION_REGISTRY")
            or str(Path(__file__).resolve().parent / "federation.yaml")
        )
        entries: list[DBEntry] = []
        p = Path(path)
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            base = p.parent
            for item in data.get("databases", []) or []:
                raw_path = str(item["path"])
                # ``AUTO`` (or the placeholder) resolves to
                # $TG_INTEL_CRAWLER_HOME/output/intel.db so deployers only need
                # to set one env var instead of editing the yaml.
                if raw_path.upper() == "AUTO" or "/ABS/PATH/TO/" in raw_path:
                    env = os.environ.get("TG_INTEL_CRAWLER_HOME")
                    if not env:
                        logger.warning(
                            "federation: db %s uses AUTO but TG_INTEL_CRAWLER_HOME "
                            "is unset — skipped", item.get("alias"))
                        continue
                    resolved = Path(env) / "output" / "intel.db"
                else:
                    raw = Path(raw_path)
                    resolved = raw if raw.is_absolute() else (base / raw)
                entries.append(DBEntry(
                    alias=str(item["alias"]),
                    path=resolved.resolve(),
                    owner=str(item.get("owner", "")),
                ))
        return cls(entries)

    def _build(self) -> None:
        for e in self._entries:
            if not e.path.exists():
                logger.warning("federation: db %s missing at %s — skipped", e.alias, e.path)
                continue
            try:
                # Attach read-only via URI.
                uri = f"file:{e.path}?mode=ro"
                self._conn.execute(f"ATTACH DATABASE ? AS {e.alias}", (uri,))
            except sqlite3.Error as ex:
                # Fall back to plain path if the build lacks URI support.
                try:
                    self._conn.execute(f"ATTACH DATABASE ? AS {e.alias}", (str(e.path),))
                except sqlite3.Error:
                    logger.warning("federation: cannot attach %s (%s) — skipped", e.alias, ex)
                    continue
            self._attached.append(e.alias)

            for table in self._filtered_tables(e.alias):
                cols = ", ".join(FILTERED_COLUMNS)
                self._select_parts.append(
                    f"SELECT '{e.alias}' AS __db, {cols} FROM {e.alias}.{table}"
                )

    def _filtered_tables(self, alias: str) -> list[str]:
        rows = self._conn.execute(
            f"SELECT name FROM {alias}.sqlite_master "
            f"WHERE type='table' AND name LIKE '%_intel_filtered'"
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- query ----------

    @property
    def union_sql(self) -> str:
        """The UNION ALL'd view body. Empty string if no data sources."""
        return " UNION ALL ".join(self._select_parts)

    @property
    def databases(self) -> list[dict]:
        return [
            {"alias": e.alias, "owner": e.owner, "path": str(e.path),
             "attached": e.alias in self._attached}
            for e in self._entries
        ]

    def query(self, sql_template: str, params: tuple = ()) -> list[dict]:
        """Run a query whose FROM target is the federated view.

        ``sql_template`` must reference ``{view}`` where the unioned source
        should be substituted, e.g.::

            fed.query("SELECT risk_level, COUNT(*) n FROM {view} GROUP BY risk_level")
        """
        if not self._select_parts:
            return []
        sql = sql_template.format(view=f"({self.union_sql})")
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---------- agent-facing SQL (read-only, validated) ----------

    # The federated view is exposed to user SQL under this name.
    VIEW_NAME = "intel"

    # Statement keywords that mutate or escape the sandbox — hard-blocked.
    _FORBIDDEN = (
        "insert", "update", "delete", "drop", "alter", "create", "replace",
        "attach", "detach", "pragma", "vacuum", "reindex", "truncate",
        "grant", "revoke", "begin", "commit", "rollback", "savepoint",
    )

    def schema_info(self) -> dict:
        """Describe the queryable view + columns so an agent can write SQL.

        Returns the logical view name (``intel``), its columns, and the list of
        underlying source databases. Agents should SELECT ... FROM intel.
        """
        return {
            "view": self.VIEW_NAME,
            "columns": ["__db"] + FILTERED_COLUMNS,
            "column_notes": {
                "__db": "which source database the row came from",
                "day": "partition date YYYY-MM-DD",
                "source_platform": "telegram / bot / twitter / weibo / ...",
                "risk_level": "high / medium / low",
                "entities": "JSON string: {accounts,contacts,links,tools,prices}",
            },
            "databases": [d["alias"] for d in self.databases if d["attached"]],
            "example": f"SELECT day, COUNT(*) n FROM {self.VIEW_NAME} "
                       f"WHERE risk_level='high' GROUP BY day ORDER BY day DESC",
        }

    def _validate_select(self, sql: str) -> None:
        s = sql.strip().rstrip(";").strip()
        if not s:
            raise ValueError("empty SQL")
        if ";" in s:
            raise ValueError("multiple statements are not allowed")
        low = s.lower()
        if not (low.startswith("select") or low.startswith("with")):
            raise ValueError("only SELECT / WITH (read-only) queries are allowed")
        # Word-boundary check so 'created_at' won't trip 'create', etc.
        import re
        for kw in self._FORBIDDEN:
            if re.search(rf"\b{kw}\b", low):
                raise ValueError(f"forbidden keyword in query: {kw}")

    def run_select(self, user_sql: str, *, max_rows: int = 500) -> dict:
        """Execute an agent-written read-only SELECT against the federated
        ``intel`` view. Validates it's a single read-only statement, substitutes
        the view, caps rows, and runs on a read-only connection.
        """
        if self.is_empty():
            return {"columns": [], "rows": [], "row_count": 0,
                    "note": "no data sources attached"}
        self._validate_select(user_sql)
        body = user_sql.strip().rstrip(";").strip()
        # Replace the logical view name with the real unioned subquery.
        import re
        view_sub = f"(SELECT * FROM ({self.union_sql})) AS {self.VIEW_NAME}"
        replaced = re.sub(rf"\b{self.VIEW_NAME}\b", view_sub, body, count=0)
        wrapped = f"SELECT * FROM ({replaced}) LIMIT {int(max_rows)}"
        cur = self._conn.execute(wrapped)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(r) for r in cur.fetchall()]
        return {"columns": cols, "rows": rows, "row_count": len(rows),
                "truncated": len(rows) >= max_rows}

    def is_empty(self) -> bool:
        return not self._select_parts

    def close(self) -> None:
        for alias in self._attached:
            try:
                self._conn.execute(f"DETACH DATABASE {alias}")
            except sqlite3.Error:
                pass
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
