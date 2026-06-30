"""ai-report compute (新写, 纯 DuckDB, 无 pandas). 5 sub-commands: assemble-wide / extract-ir / validate / evaluate / apply-computed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb


SENTINEL_CAST_FAILED = "⚠️CAST_FAILED"
SENTINEL_QUERY_FAILED = "⚠️QUERY_FAILED"


@dataclass
class ComputeIR:
    name: str
    prompt: str
    examples: list[dict] = field(default_factory=list)


def extract_ir(body: str) -> list[ComputeIR]:
    """Parse `> 计算:` blocks from report MD body.

    Each block: `> 计算: name = "X", prompt = "Y"[, examples = [...]]`
    """
    irs: list[ComputeIR] = []
    pattern = re.compile(
        r'>\s*计算:\s*name\s*=\s*"([^"]+)"\s*,\s*prompt\s*=\s*"([^"]+)"(?:\s*,\s*examples\s*=\s*(\[[^\]]*\]))?',
    )
    for m in pattern.finditer(body):
        name, prompt, examples_raw = m.group(1), m.group(2), m.group(3)
        import json as _json
        examples = _json.loads(examples_raw) if examples_raw else []
        irs.append(ComputeIR(name=name, prompt=prompt, examples=examples))
    return irs


def _cell_value(f: dict) -> str:
    """Return the string cell to store in the facts table for one fact row.

    Sentinels are kept as strings (so they survive VARCHAR PIVOT). Numbers are
    stringified so the column has a uniform VARCHAR type (DuckDB CASE unification
    rejects VARCHAR/DOUBLE mixes even with explicit TRY_CAST).
    """
    value = f.get("numeric_value")
    if f.get("status") == "query_failed":
        return SENTINEL_QUERY_FAILED
    if f.get("status") != "ok" or value is None:
        return SENTINEL_CAST_FAILED
    return str(float(value))


def _parse_cell(raw: object) -> object:
    """Post-process one wide cell: numeric strings → float, sentinel strings → str, None → None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw in (SENTINEL_QUERY_FAILED, SENTINEL_CAST_FAILED):
            return raw
        try:
            return float(raw)
        except ValueError:
            return raw
    if isinstance(raw, (int, float)):
        return float(raw)
    return raw


def assemble_wide(metric_facts: list[dict], run_id: str, table_id: str) -> list[dict]:
    """PIVOT metric_facts to wide table via DuckDB. Returns list of {branch_num, idx_id@period: value, ...}.

    Strategy: keep `numeric_value` as VARCHAR throughout the SQL (so CASE/MAX
    don't have to unify mixed types). After PIVOT, post-process each cell in
    Python: numeric strings → float, sentinel strings preserved verbatim.
    """
    if not metric_facts:
        return []
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE facts (branch_num TEXT, idx_id TEXT, period_alias TEXT, numeric_value TEXT)"
    )
    for f in metric_facts:
        conn.execute(
            "INSERT INTO facts VALUES (?, ?, ?, ?)",
            [f.get("branch_num", ""), f.get("idx_id", ""), f.get("period_alias", ""),
             _cell_value(f)],
        )
    distinct_keys = sorted({f"{f.get('idx_id','')}@{f.get('period_alias','')}" for f in metric_facts})
    in_clause = ", ".join(f"'{k}'" for k in distinct_keys)
    rows = conn.execute(
        f"""SELECT * FROM (
              SELECT branch_num, idx_id || '@' || period_alias AS col_key, numeric_value
              FROM facts
            ) PIVOT (
              MAX(numeric_value)
              FOR col_key IN ({in_clause})
            )"""
    ).fetchall()
    cols = [d[0] for d in conn.description]
    out = []
    for r in rows:
        row = dict(zip(cols, r))
        for c in cols:
            if c != "branch_num":
                row[c] = _parse_cell(row[c])
        out.append(row)
    conn.close()
    return out