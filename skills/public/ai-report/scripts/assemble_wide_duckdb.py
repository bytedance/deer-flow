"""ai-report Step 4: assemble-wide (新写, 纯 DuckDB PIVOT).

Phase 1 invariant: DECIMAL(38,10) precision through PIVOT. No float. Failed query
cells render as None (the sentinel code lives in assembled sentinels, not in the cell).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assemble_wide_duckdb")
    parser.add_argument("--parsed", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    parsed = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
    query = json.loads(Path(args.query).read_text(encoding="utf-8"))

    facts = query.get("metric_facts", [])
    if not facts:
        # Empty input → empty output.
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps([], ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return 0

    # Collect distinct column keys (preserving first-seen order).
    col_keys: list[str] = []
    seen: set[str] = set()
    for f in facts:
        key = f"{f['idx_id']}@{f['period']}"
        if key not in seen:
            seen.add(key)
            col_keys.append(key)

    # Build branch → facts map for clean iteration.
    facts_by_branch: dict[str, list[dict]] = {}
    for f in facts:
        facts_by_branch.setdefault(f["org_ecd"], []).append(f)

    # Per-call :memory: DuckDB conn (Phase 1 invariant — DuckDB conn is not thread-safe).
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE metric_facts (org_ecd VARCHAR, col_key VARCHAR, value_str VARCHAR)"
        )
        for org, fs in facts_by_branch.items():
            for f in fs:
                if f.get("status") != "ok" or f.get("numeric_value") is None:
                    continue
                conn.execute(
                    "INSERT INTO metric_facts VALUES (?, ?, ?)",
                    [org, f"{f['idx_id']}@{f['period']}", str(f["numeric_value"])],
                )

        # PIVOT via DuckDB. MAX(DECIMAL) preserves precision; no float() anywhere.
        pivot_sql = (
            "SELECT org_ecd AS branch_num, "
            + ", ".join(f'CAST("{k}" AS DECIMAL(38,10)) AS "{k}"' for k in col_keys)
            + " FROM metric_facts PIVOT (MAX(value_str) FOR col_key IN ("
            + ", ".join(f"'{k}'" for k in col_keys)
            + ")) AS p ORDER BY branch_num"
        )
        result_proxy = conn.execute(pivot_sql)
        rows = result_proxy.fetchall()
        col_names = [d[0] for d in result_proxy.description]
    finally:
        conn.close()

    wide: list[dict] = []
    for row in rows:
        d = {"branch_num": row[0]}
        for i, col in enumerate(col_names[1:], start=1):
            val = row[i]
            # Decimal → str (preserve precision through JSON)
            d[col] = str(val) if val is not None else None
        wide.append(d)

    # Fill missing branch × col cells with None explicitly (so column shape is
    # complete even when one branch has no data for some idx_id).
    for org in sorted(facts_by_branch.keys()):
        row = next((r for r in wide if r["branch_num"] == org), None)
        if row is None:
            row = {"branch_num": org}
            wide.append(row)
        for k in col_keys:
            row.setdefault(k, None)
    wide.sort(key=lambda r: r["branch_num"])

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(wide, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())