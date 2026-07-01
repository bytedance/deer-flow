"""ai-report runtime wrapper: pull approved snapshots, call render_docx, write report.docx (新写)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from duckdb_store import DEFAULT_DB_PATH, Store
from render_docx import render_docx
from report_md import build_runtime_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_docx")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--style", default=str(Path(__file__).resolve().parent / "report_style.json"))
    args = parser.parse_args(argv)
    try:
        store = Store(db_path=args.db_path)
        store.open()  # auto-inits schema
        payload = build_runtime_payload(store, args.report_id)
        if not payload["sections"]:
            print(f"FAIL: no approved tables for {args.report_id}", file=sys.stderr)
            return 1
        render_docx(payload, out_path=args.out, style_path=args.style)
        print(f"OK: {args.out}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())