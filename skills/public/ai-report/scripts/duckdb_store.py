"""ai-report: 5-table DuckDB store with run_id history (新写, 纯 DuckDB, 无 pandas)."""
from __future__ import annotations

import hashlib
import json as _json
import uuid
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = "/mnt/ai-report-data/duckdb/ai-report.duckdb"

# JSON columns auto-decoded by list_approved_tables (so callers get Python objects, not raw strings).
_JSON_COLUMNS = ("wide_table", "computed_columns", "descriptions", "sentinels")


class Store:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> "Store":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self._db_path)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        assert self._conn is not None, "Store not opened"
        return self._conn

    def init_schema(self) -> None:
        self.conn.execute(_SCHEMA_SQL)


# ID 命名见 spec §preamble
def make_report_id(source_md_path: str) -> str:
    return hashlib.sha256(source_md_path.encode("utf-8")).hexdigest()[:16]


def make_run_id() -> str:
    return uuid.uuid4().hex


def make_section_id(report_id: str, section_order: int) -> str:
    return f"{report_id}_s{section_order:02d}"


def make_table_id(section_id: str, table_order: int) -> str:
    return f"{section_id}_t{table_order:02d}"


# ---------- CRUD ---------- #

def upsert_report(self, report_id: str, title: str, source_md_path: str, source_md_hash: str) -> str:
    self.conn.execute(
        """INSERT INTO reports (report_id, schema_version, report_title, source_md_path, source_md_hash)
           VALUES (?, 1, ?, ?, ?)
           ON CONFLICT (report_id) DO UPDATE SET
             report_title=excluded.report_title,
             source_md_path=excluded.source_md_path,
             source_md_hash=excluded.source_md_hash,
             updated_at=now()""",
        [report_id, title, source_md_path, source_md_hash],
    )
    return report_id


def upsert_section(self, report_id: str, section_order: int, section_title: str) -> str:
    section_id = make_section_id(report_id, section_order)
    self.conn.execute(
        """INSERT INTO report_sections (section_id, schema_version, report_id, section_order, section_title)
           VALUES (?, 1, ?, ?, ?)
           ON CONFLICT (section_id) DO UPDATE SET
             section_title=excluded.section_title,
             updated_at=now()""",
        [section_id, report_id, section_order, section_title],
    )
    return section_id


def upsert_table(
    self, report_id: str, section_id: str, table_order: int, table_title: str,
    source_md_snapshot: str, source_md_hash: str, parsed_payload: dict,
) -> str:
    table_id = make_table_id(section_id, table_order)
    self.conn.execute(
        """INSERT INTO report_tables
           (table_id, schema_version, report_id, section_id, table_order, table_title,
            approval_status, source_md_snapshot, source_md_hash, parsed_payload)
           VALUES (?, 1, ?, ?, ?, ?, 'draft', ?, ?, ?)
           ON CONFLICT (table_id) DO UPDATE SET
             table_title=excluded.table_title,
             source_md_snapshot=excluded.source_md_snapshot,
             source_md_hash=excluded.source_md_hash,
             parsed_payload=excluded.parsed_payload,
             updated_at=now()""",
        [table_id, report_id, section_id, table_order, table_title,
         source_md_snapshot, source_md_hash, _json.dumps(parsed_payload, ensure_ascii=False)],
    )
    return table_id


def get_report_meta(self, report_id: str) -> dict | None:
    row = self.conn.execute("SELECT * FROM reports WHERE report_id=?", [report_id]).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


def get_table(self, table_id: str) -> dict | None:
    row = self.conn.execute("SELECT * FROM report_tables WHERE table_id=?", [table_id]).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


def insert_metric_facts(self, run_id: str, table_id: str, report_id: str, facts: list[dict]) -> None:
    """Batch insert via executemany (one round-trip for N facts)."""
    if not facts:
        return
    rows = [
        [
            run_id, table_id, report_id,
            f.get("branch_num", ""), f.get("branch_short_name"),
            f.get("idx_id", ""), f.get("period_alias", ""), f.get("period_value"),
            f.get("raw_value"), f.get("numeric_value"),
            f.get("status", "ok"), f.get("error_message"),
        ]
        for f in facts
    ]
    self.conn.executemany(
        """INSERT INTO metric_facts
           (run_id, schema_version, table_id, report_id, branch_num, branch_short_name,
            idx_id, period_alias, period_value, raw_value, numeric_value, status, error_message)
           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        rows,
    )


def get_metric_facts(self, run_id: str, table_id: str) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM metric_facts WHERE run_id=? AND table_id=? ORDER BY branch_num, idx_id, period_alias",
        [run_id, table_id],
    ).fetchall()
    cols = [d[0] for d in self.conn.description]
    return [dict(zip(cols, r)) for r in rows]


def save_approved_run(
    self, run_id: str, table_id: str, report_id: str, section_id: str,
    wide_table: list, computed_columns: list, descriptions: list, status: str,
    sentinels: list, runlog_markdown: str, design_md_path: str,
) -> None:
    # Phase 1 fix: UPDATE report_tables BEFORE INSERT into approved_table_runs.
    # DuckDB 1.5.2 raises FK violation on any UPDATE of a parent row that has
    # existing children, even when the FK column is not changing. So we must
    # update the parent first (when it has no approved_run children yet),
    # then insert the child. (Alternative would be ON UPDATE CASCADE, but
    # DuckDB 1.5.2 doesn't support FK action clauses.)
    self.conn.execute(
        """UPDATE report_tables
           SET approval_status='approved', last_design_run_id=?, updated_at=now()
           WHERE table_id=?""",
        [run_id, table_id],
    )
    self.conn.execute(
        """INSERT INTO approved_table_runs
           (run_id, schema_version, table_id, report_id, section_id, wide_table,
            computed_columns, descriptions, status, sentinels, runlog_markdown, design_md_path)
           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [run_id, table_id, report_id, section_id, _json.dumps(wide_table, ensure_ascii=False),
         _json.dumps(computed_columns, ensure_ascii=False),
         _json.dumps(descriptions, ensure_ascii=False),
         status, _json.dumps(sentinels, ensure_ascii=False),
         runlog_markdown, design_md_path],
    )


def list_approved_tables(self, report_id: str) -> list[dict]:
    rows = self.conn.execute(
        """SELECT rt.table_id, rt.section_id, rt.table_order, rt.table_title,
                  rs.section_order, rs.section_title,
                  atr.run_id, atr.wide_table, atr.computed_columns, atr.descriptions,
                  atr.status, atr.sentinels, atr.runlog_markdown
           FROM report_tables rt
           JOIN report_sections rs ON rt.section_id=rs.section_id
           JOIN approved_table_runs atr ON atr.run_id=rt.last_design_run_id
           WHERE rt.report_id=? AND rt.approval_status='approved'
           ORDER BY rs.section_order, rt.table_order""",
        [report_id],
    ).fetchall()
    cols = [d[0] for d in self.conn.description]
    out: list[dict] = []
    for r in rows:
        d = dict(zip(cols, r))
        for jc in _JSON_COLUMNS:
            if jc in d and isinstance(d[jc], str):
                d[jc] = _json.loads(d[jc])
        out.append(d)
    return out


def get_approved_run(self, table_id: str) -> dict | None:
    row = self.conn.execute(
        """SELECT * FROM approved_table_runs
           WHERE table_id=? ORDER BY created_at DESC LIMIT 1""",
        [table_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


def list_tables_by_section(self, section_id: str) -> list[dict]:
    """Return report_tables rows for a section, ordered by table_order.

    Phase 1 fix: 封装 FK 查询, 替代 DesignPipeline.run_report 里直接 store.conn.execute(...) 的反模式.
    """
    rows = self.conn.execute(
        "SELECT * FROM report_tables WHERE section_id=? ORDER BY table_order",
        [section_id],
    ).fetchall()
    cols = [d[0] for d in self.conn.description]
    return [dict(zip(cols, r)) for r in rows]


# 把方法绑到 Store 类
Store.upsert_report = upsert_report
Store.upsert_section = upsert_section
Store.upsert_table = upsert_table
Store.get_report_meta = get_report_meta
Store.get_table = get_table
Store.insert_metric_facts = insert_metric_facts
Store.get_metric_facts = get_metric_facts
Store.save_approved_run = save_approved_run
Store.list_approved_tables = list_approved_tables
Store.get_approved_run = get_approved_run
Store.list_tables_by_section = list_tables_by_section


# TIMESTAMPTZ (UTC) instead of naive TIMESTAMP — survives server timezone drift.
# now() consistent across DEFAULT clauses and ON CONFLICT DO UPDATE SET clauses
# (DuckDB 1.5.2 treats bare `current_timestamp` in ON CONFLICT as a column ref).
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
  report_id        TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_title     TEXT NOT NULL,
  source_md_path   TEXT NOT NULL,
  source_md_hash   TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_sections (
  section_id       TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_id        TEXT NOT NULL REFERENCES reports(report_id),
  section_order    INTEGER NOT NULL,
  section_title    TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(report_id, section_order)
);

CREATE TABLE IF NOT EXISTS report_tables (
  table_id              TEXT PRIMARY KEY,
  schema_version        INTEGER NOT NULL DEFAULT 1,
  report_id             TEXT NOT NULL REFERENCES reports(report_id),
  section_id            TEXT NOT NULL REFERENCES report_sections(section_id),
  table_order           INTEGER NOT NULL,
  table_title           TEXT NOT NULL,
  approval_status       TEXT NOT NULL DEFAULT 'draft'
                            CHECK (approval_status IN ('draft','approved','rejected')),
  source_md_snapshot    TEXT NOT NULL,
  source_md_hash        TEXT NOT NULL,
  parsed_payload        JSON NOT NULL,
  last_design_run_id    TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(report_id, section_id, table_order)
);
CREATE INDEX IF NOT EXISTS idx_report_tables_status ON report_tables(report_id, approval_status);

CREATE TABLE IF NOT EXISTS metric_facts (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  branch_num          TEXT NOT NULL,
  branch_short_name   TEXT,
  idx_id              TEXT NOT NULL,
  period_alias        TEXT NOT NULL,
  period_value        TEXT,
  raw_value           TEXT,
  numeric_value       DECIMAL(38,10),
  status              TEXT NOT NULL,
  error_message       TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
);
CREATE INDEX IF NOT EXISTS idx_metric_facts_run ON metric_facts(run_id, table_id);

CREATE TABLE IF NOT EXISTS approved_table_runs (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  section_id          TEXT NOT NULL,
  wide_table          JSON NOT NULL,
  computed_columns    JSON NOT NULL DEFAULT '[]',
  descriptions        JSON NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL,
  sentinels           JSON NOT NULL DEFAULT '[]',
  runlog_markdown     TEXT NOT NULL,
  design_md_path      TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(run_id, table_id)
);
CREATE INDEX IF NOT EXISTS idx_approved_runs_table ON approved_table_runs(table_id, created_at DESC);
"""