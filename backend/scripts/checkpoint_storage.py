"""Read-only diagnostics for LangGraph checkpoint SQLite storage.

Usage:
    PYTHONPATH=. python scripts/checkpoint_storage.py report
    PYTHONPATH=. python scripts/checkpoint_storage.py report --db .deer-flow/data/deerflow.db
    PYTHONPATH=. python scripts/checkpoint_storage.py report --json --keep 1
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "writes")
THREAD_META_TABLE = "threads_meta"
PAYLOAD_SKIP_COLUMNS = {
    "thread_id",
    "checkpoint_ns",
    "checkpoint_id",
    "parent_checkpoint_id",
    "task_id",
    "idx",
    "channel",
    "version",
    "user_id",
    "created_at",
    "updated_at",
}


class CheckpointStorageError(RuntimeError):
    """Raised when the checkpoint storage report cannot be produced."""


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise CheckpointStorageError(f"SQLite database does not exist: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return [str(row["name"]) for row in rows]


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {_quote_identifier(table)}").fetchone()
    return int(row["count"] or 0)


def _scalar_int(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    value = row[0]
    return int(value or 0)


def _payload_columns(columns: list[str]) -> list[str]:
    payload_columns = [column for column in columns if column not in PAYLOAD_SKIP_COLUMNS]
    return payload_columns or columns


def _payload_length_expr(columns: list[str], *, alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    terms = [f"COALESCE(length({prefix}{_quote_identifier(column)}), 0)" for column in _payload_columns(columns)]
    return " + ".join(terms) if terms else "0"


def _file_size(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    return path.stat().st_size


def _format_bytes(size: int | None) -> str:
    if size is None:
        return "n/a"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _distinct_thread_ids(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    columns = _columns(conn, table)
    if "thread_id" not in columns:
        return set()
    rows = conn.execute(f"SELECT DISTINCT thread_id FROM {_quote_identifier(table)} WHERE thread_id IS NOT NULL").fetchall()
    return {str(row["thread_id"]) for row in rows}


def _table_payload_bytes(conn: sqlite3.Connection, table: str) -> int:
    columns = _columns(conn, table)
    expr = _payload_length_expr(columns)
    return _scalar_int(conn, f"SELECT COALESCE(SUM({expr}), 0) FROM {_quote_identifier(table)}")


def _thread_payload_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    columns = _columns(conn, table)
    if "thread_id" not in columns:
        return []
    expr = _payload_length_expr(columns)
    return conn.execute(
        f"""
        SELECT
            thread_id,
            COUNT(*) AS row_count,
            COALESCE(SUM({expr}), 0) AS approx_payload_bytes
        FROM {_quote_identifier(table)}
        WHERE thread_id IS NOT NULL
        GROUP BY thread_id
        """
    ).fetchall()


def _inspect_tables(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for table in CHECKPOINT_TABLES:
        exists = _table_exists(conn, table)
        result[table] = {
            "exists": exists,
            "rows": _count_rows(conn, table) if exists else 0,
            "approx_payload_bytes": _table_payload_bytes(conn, table) if exists else 0,
        }
    return result


def _build_top_threads(
    conn: sqlite3.Connection,
    *,
    limit: int,
    include_thread_ids: bool,
) -> list[dict[str, Any]]:
    per_thread: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "checkpoint_rows": 0,
            "checkpoint_blob_rows": 0,
            "write_rows": 0,
            "approx_payload_bytes": 0,
        }
    )
    table_to_key = {
        "checkpoints": "checkpoint_rows",
        "checkpoint_blobs": "checkpoint_blob_rows",
        "writes": "write_rows",
    }
    for table, key in table_to_key.items():
        if not _table_exists(conn, table):
            continue
        for row in _thread_payload_rows(conn, table):
            thread = per_thread[str(row["thread_id"])]
            thread[key] += int(row["row_count"] or 0)
            thread["approx_payload_bytes"] += int(row["approx_payload_bytes"] or 0)

    ranked = sorted(
        per_thread.items(),
        key=lambda item: (
            item[1]["approx_payload_bytes"],
            item[1]["checkpoint_rows"],
            item[0],
        ),
        reverse=True,
    )
    output: list[dict[str, Any]] = []
    for index, (thread_id, stats) in enumerate(ranked[:limit], start=1):
        entry = {"label": f"thread#{index}", **stats}
        if include_thread_ids:
            entry["thread_id"] = thread_id
        output.append(entry)
    return output


def _estimate_retention(conn: sqlite3.Connection, keep: int) -> dict[str, Any] | None:
    if not _table_exists(conn, "checkpoints"):
        return None

    checkpoint_columns = _columns(conn, "checkpoints")
    checkpoint_payload_expr = _payload_length_expr(checkpoint_columns, alias="c")
    ranked_cte = """
        WITH ranked AS (
            SELECT
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                ROW_NUMBER() OVER (
                    PARTITION BY thread_id, checkpoint_ns
                    ORDER BY checkpoint_id DESC
                ) AS rn
            FROM checkpoints
        )
    """
    removable_checkpoint_rows = _scalar_int(
        conn,
        ranked_cte + "SELECT COUNT(*) FROM ranked WHERE rn > ?",
        (keep,),
    )
    removable_checkpoint_payload_bytes = _scalar_int(
        conn,
        ranked_cte
        + f"""
        SELECT COALESCE(SUM({checkpoint_payload_expr}), 0)
        FROM checkpoints c
        JOIN ranked r
          ON c.thread_id = r.thread_id
         AND c.checkpoint_ns = r.checkpoint_ns
         AND c.checkpoint_id = r.checkpoint_id
        WHERE r.rn > ?
        """,
        (keep,),
    )

    removable_write_rows = 0
    removable_write_payload_bytes = 0
    if _table_exists(conn, "writes"):
        write_columns = _columns(conn, "writes")
        write_payload_expr = _payload_length_expr(write_columns, alias="w")
        removable_write_rows = _scalar_int(
            conn,
            ranked_cte
            + """
            SELECT COUNT(*)
            FROM writes w
            JOIN ranked r
              ON w.thread_id = r.thread_id
             AND w.checkpoint_ns = r.checkpoint_ns
             AND w.checkpoint_id = r.checkpoint_id
            WHERE r.rn > ?
            """,
            (keep,),
        )
        removable_write_payload_bytes = _scalar_int(
            conn,
            ranked_cte
            + f"""
            SELECT COALESCE(SUM({write_payload_expr}), 0)
            FROM writes w
            JOIN ranked r
              ON w.thread_id = r.thread_id
             AND w.checkpoint_ns = r.checkpoint_ns
             AND w.checkpoint_id = r.checkpoint_id
            WHERE r.rn > ?
            """,
            (keep,),
        )

    return {
        "keep": keep,
        "removable_checkpoint_rows": removable_checkpoint_rows,
        "removable_write_rows": removable_write_rows,
        "approx_removable_payload_bytes": removable_checkpoint_payload_bytes + removable_write_payload_bytes,
        "note": "Estimate covers checkpoint rows and writes linked to old checkpoints; checkpoint_blobs may be shared by version and are not counted.",
    }


def _runtime_home() -> Path:
    if env_home := os.getenv("DEER_FLOW_HOME"):
        return Path(env_home).expanduser().resolve()
    return Path.cwd().resolve() / ".deer-flow"


def _resolve_config_path(config_path: str | None) -> Path:
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise CheckpointStorageError(f"Config file does not exist: {path}")
        return path.resolve()

    if env_path := os.getenv("DEER_FLOW_CONFIG_PATH"):
        path = Path(env_path).expanduser()
        if not path.exists():
            raise CheckpointStorageError(f"Config file does not exist: {path}")
        return path.resolve()

    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parent
    candidates = (
        Path.cwd() / "config.yaml",
        backend_dir / "config.yaml",
        repo_root / "config.yaml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise CheckpointStorageError("config.yaml not found; pass --db or --config")


def _env_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$") and len(value) > 1:
        return os.getenv(value[1:], value)
    return value


def _resolve_project_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd().resolve() / path
    return path.resolve()


def _resolve_base_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _runtime_home() / path
    return path.resolve()


def _resolve_configured_sqlite_paths(
    config_path: str | None,
) -> tuple[Path | None, Path | None, str]:
    resolved_config = _resolve_config_path(config_path)
    with resolved_config.open(encoding="utf-8") as handle:
        config_data = yaml.safe_load(handle) or {}

    database = config_data.get("database") or {}
    if not isinstance(database, dict):
        database = {}
    database_backend = _env_value(database.get("backend", "sqlite"))
    sqlite_dir = _env_value(database.get("sqlite_dir", ".deer-flow/data"))

    app_db_path: Path | None = None
    if database_backend == "sqlite":
        app_db_path = _resolve_project_path(str(sqlite_dir)) / "deerflow.db"

    checkpointer = config_data.get("checkpointer")
    if isinstance(checkpointer, dict):
        checkpointer_type = _env_value(checkpointer.get("type"))
        if checkpointer_type != "sqlite":
            return None, app_db_path, f"legacy checkpointer backend is {checkpointer_type}"
        raw_path = str(_env_value(checkpointer.get("connection_string", "store.db")))
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            return None, app_db_path, f"legacy sqlite checkpointer uses non-filesystem connection string: {raw_path}"
        return _resolve_base_path(raw_path), app_db_path, "legacy checkpointer"

    if database_backend != "sqlite":
        return None, app_db_path, f"database backend is {database_backend}"
    return app_db_path, app_db_path, "database"


def inspect_checkpoint_storage(
    checkpoint_db_path: Path,
    *,
    app_db_path: Path | None = None,
    top: int = 10,
    keep: int | None = None,
    include_thread_ids: bool = False,
    source: str = "explicit",
) -> dict[str, Any]:
    checkpoint_db_path = checkpoint_db_path.expanduser().resolve()
    app_db_path = app_db_path.expanduser().resolve() if app_db_path is not None else checkpoint_db_path

    with _connect_read_only(checkpoint_db_path) as checkpoint_conn:
        checkpoint_threads = _distinct_thread_ids(checkpoint_conn, "checkpoints")
        table_stats = _inspect_tables(checkpoint_conn)
        top_threads = _build_top_threads(
            checkpoint_conn,
            limit=top,
            include_thread_ids=include_thread_ids,
        )
        retention = _estimate_retention(checkpoint_conn, keep) if keep is not None else None

    app_thread_table_exists = False
    app_threads: set[str] = set()
    app_db_exists = app_db_path.exists() if app_db_path is not None else False
    if app_db_path == checkpoint_db_path:
        with _connect_read_only(checkpoint_db_path) as app_conn:
            app_thread_table_exists = _table_exists(app_conn, THREAD_META_TABLE)
            app_threads = _distinct_thread_ids(app_conn, THREAD_META_TABLE)
    elif app_db_path is not None and app_db_path.exists():
        with _connect_read_only(app_db_path) as app_conn:
            app_thread_table_exists = _table_exists(app_conn, THREAD_META_TABLE)
            app_threads = _distinct_thread_ids(app_conn, THREAD_META_TABLE)

    orphan_thread_ids = sorted(checkpoint_threads - app_threads) if app_thread_table_exists else None

    report: dict[str, Any] = {
        "source": source,
        "checkpoint_db_path": str(checkpoint_db_path),
        "checkpoint_db_exists": checkpoint_db_path.exists(),
        "checkpoint_db_size_bytes": _file_size(checkpoint_db_path),
        "checkpoint_wal_size_bytes": _file_size(Path(str(checkpoint_db_path) + "-wal")),
        "checkpoint_shm_size_bytes": _file_size(Path(str(checkpoint_db_path) + "-shm")),
        "app_db_path": str(app_db_path) if app_db_path is not None else None,
        "app_db_exists": app_db_exists,
        "app_thread_table_exists": app_thread_table_exists,
        "checkpoint_thread_count": len(checkpoint_threads),
        "app_thread_count": len(app_threads) if app_thread_table_exists else None,
        "orphan_checkpoint_thread_count": len(orphan_thread_ids) if orphan_thread_ids is not None else None,
        "tables": table_stats,
        "top_threads": top_threads,
    }
    if include_thread_ids:
        report["checkpoint_thread_ids"] = sorted(checkpoint_threads)
        report["app_thread_ids"] = sorted(app_threads) if app_thread_table_exists else None
        report["orphan_checkpoint_thread_ids"] = orphan_thread_ids
    if retention is not None:
        report["retention_estimate"] = retention
    return report


def _print_human_report(report: dict[str, Any]) -> None:
    print("Checkpoint storage report")
    print("=========================")
    print(f"Source: {report['source']}")
    print(f"Checkpoint DB: {report['checkpoint_db_path']}")
    print(f"Checkpoint DB size: {_format_bytes(report['checkpoint_db_size_bytes'])}")
    print(f"WAL size: {_format_bytes(report['checkpoint_wal_size_bytes'])}")
    print(f"SHM size: {_format_bytes(report['checkpoint_shm_size_bytes'])}")
    if report.get("app_db_path") != report["checkpoint_db_path"]:
        print(f"App metadata DB: {report.get('app_db_path') or 'n/a'}")
    print()

    print("Tables")
    for table, stats in report["tables"].items():
        if not stats["exists"]:
            print(f"  - {table}: missing")
            continue
        print(f"  - {table}: {stats['rows']} rows, approx payload {_format_bytes(stats['approx_payload_bytes'])}")
    print()

    print("Threads")
    print(f"  - checkpoint threads: {report['checkpoint_thread_count']}")
    if report["app_thread_table_exists"]:
        print(f"  - app threads: {report['app_thread_count']}")
        print(f"  - orphan checkpoint threads: {report['orphan_checkpoint_thread_count']}")
    else:
        print("  - app thread metadata: unavailable")
    print()

    top_threads = report["top_threads"]
    if top_threads:
        print("Top checkpoint threads by estimated payload")
        for entry in top_threads:
            thread_label = entry.get("thread_id", entry["label"])
            print(f"  - {thread_label}: checkpoints={entry['checkpoint_rows']}, writes={entry['write_rows']}, blobs={entry['checkpoint_blob_rows']}, approx={_format_bytes(entry['approx_payload_bytes'])}")
        if "thread_id" not in top_threads[0]:
            print("  (raw thread IDs hidden; pass --show-thread-ids to print them)")
        print()

    retention = report.get("retention_estimate")
    if retention is not None:
        print(f"Retention estimate for keep={retention['keep']}")
        print(f"  - removable checkpoint rows: {retention['removable_checkpoint_rows']}")
        print(f"  - removable write rows: {retention['removable_write_rows']}")
        print(f"  - approx removable payload: {_format_bytes(retention['approx_removable_payload_bytes'])}")
        print(f"  - note: {retention['note']}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only DeerFlow checkpoint storage diagnostics.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser(
        "report",
        help="Report SQLite checkpoint storage size, rows, threads, and retention estimates.",
    )
    report.add_argument(
        "--config",
        help="Path to config.yaml. Defaults to DeerFlow config resolution. Ignored when --db is set.",
    )
    report.add_argument(
        "--db",
        type=Path,
        help="Checkpoint SQLite database path. Overrides config resolution.",
    )
    report.add_argument(
        "--app-db",
        type=Path,
        help="SQLite database path containing threads_meta. Defaults to --db or configured database path.",
    )
    report.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of largest checkpoint threads to show. Defaults to 10.",
    )
    report.add_argument(
        "--keep",
        type=int,
        help="Estimate rows/payload older than the latest N checkpoints per thread namespace.",
    )
    report.add_argument(
        "--show-thread-ids",
        action="store_true",
        help="Print raw thread IDs. Hidden by default to reduce accidental identifier disclosure.",
    )
    report.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.keep is not None and args.keep < 1:
        parser.error("--keep must be at least 1")

    try:
        if args.db is not None:
            checkpoint_db_path = args.db
            app_db_path = args.app_db or args.db
            source = "explicit"
        else:
            checkpoint_db_path, app_db_path, source = _resolve_configured_sqlite_paths(args.config)
            if args.app_db is not None:
                app_db_path = args.app_db
            if checkpoint_db_path is None:
                print(f"Checkpoint storage report is unavailable: {source}.", file=sys.stderr)
                return 1

        report = inspect_checkpoint_storage(
            checkpoint_db_path,
            app_db_path=app_db_path,
            top=args.top,
            keep=args.keep,
            include_thread_ids=args.show_thread_ids,
            source=source,
        )
    except CheckpointStorageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
