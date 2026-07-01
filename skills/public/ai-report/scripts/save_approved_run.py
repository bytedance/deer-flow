"""ai-report Step 13: save approved run to DuckDB (new CLI wrapper).

Reads an <stem>.approved.json payload assembled by the lead agent and writes
one row to Store.approved_runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="save_approved_run")
    parser.add_argument("--input", required=True, help="<stem>.approved.json path")
    parser.add_argument("--db-path", required=True)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from duckdb_store import Store

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    store = Store(db_path=args.db_path)
    store.open()
    try:
        store.save_approved_run(
            payload["run_id"],
            payload["table_id"],
            payload["report_id"],
            payload["section_id"],
            payload["wide_table"],
            payload["headers_2d"],
            payload["descriptions"],
            payload["status"],
            payload["sentinels"],
            payload["runlog"],
            payload["design_md_path"],
        )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())