"""ai-report runtime wrapper: pull approved snapshots, call render_markdown, write report.md (新写)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from duckdb_store import DEFAULT_DB_PATH, Store
from render_markdown import render_markdown


def _coerce_description(d: Any) -> str | None:
    """Phase 1 contract: design_pipeline stores descriptions as plain strings
    (from _llm_describe return value). Older callers / tests may pass
    dict-shaped `[{"text": "..."}]`. Accept both.
    """
    if not d:
        return None
    if isinstance(d, dict):
        return str(d.get("text") or "").strip() or None
    return str(d).strip() or None


def build_runtime_payload(store: Store, report_id: str) -> dict:
    """Pull approved tables (按 section_order, table_order), build render_payload.

    Phase 1: list_approved_tables already auto-decodes JSON columns and
    parsed_payload, so the `if isinstance(..., str)` guards are no-ops in
    practice but kept defensive in case a future caller passes a raw Store.
    """
    rows = store.list_approved_tables(report_id)
    sections_dict: dict[int, dict] = {}
    for r in rows:
        sec_order = r["section_order"]
        sec_title = r["section_title"]
        if sec_order not in sections_dict:
            sections_dict[sec_order] = {"title": sec_title, "reports": []}
        # list_approved_tables already JSON-decodes these, but be defensive
        wide = json.loads(r["wide_table"]) if isinstance(r["wide_table"], str) else r["wide_table"]
        sentinels = json.loads(r["sentinels"]) if isinstance(r["sentinels"], str) else r["sentinels"]
        descriptions = json.loads(r["descriptions"]) if isinstance(r["descriptions"], str) else r["descriptions"]
        parsed = r.get("parsed_payload") or {}
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        sections_dict[sec_order]["reports"].append({
            "title": r["table_title"],
            "description": _coerce_description(descriptions[0] if descriptions else None),
            "headers": parsed.get("headers_2d", []),
            "rows": wide,
            "sentinels": sentinels,
            "computed_sentinels": {},
        })
    sections = [sections_dict[k] for k in sorted(sections_dict)]
    meta = store.get_report_meta(report_id) or {}
    return {"title": meta.get("report_title", report_id), "sections": sections}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_md")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        store = Store(db_path=args.db_path)
        store.open()  # auto-inits schema
        payload = build_runtime_payload(store, args.report_id)
        if not payload["sections"]:
            print(f"FAIL: no approved tables for {args.report_id}", file=sys.stderr)
            return 1
        out = render_markdown(payload)
        Path(args.out).write_text(out, encoding="utf-8")
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