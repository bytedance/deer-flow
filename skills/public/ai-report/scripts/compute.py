"""ai-report compute (新写, 纯 DuckDB, 无 pandas). 5 sub-commands: assemble-wide / extract-ir / validate / evaluate / apply-computed.

Phase 1 政策:
- 数据层纯 DuckDB DECIMAL(38,10), 无 float (银行精度要求)
- 失败 cell 不编码哨兵字符串, NULL 留空; 哨兵聚合走 assemble_status (task 13)
- DuckDB 连接模块化 (_get_conn 单例, validate 接收 caller conn)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import duckdb


# ---------- 模块级 DuckDB 连接 (assemble_wide / evaluate 用 :memory: 单例) ---------- #

_conn: duckdb.DuckDBPyConnection | None = None


def _get_conn() -> duckdb.DuckDBPyConnection:
    """Module-level :memory: DuckDB singleton.

    为什么 :memory: 而不是 Store.conn: 本模块是纯转换函数 (输入 list[dict] →
    输出 list[dict]), 不读写 ai-report.duckdb 持久表. validate(conn, ...)
    接收 caller 注入的 conn, 因为它需要 TEMP TABLE 生命周期跟随 caller 事务.
    """
    global _conn
    if _conn is None:
        _conn = duckdb.connect(":memory:")
    return _conn


def reset_conn_for_tests() -> None:
    """Test helper: close module conn so next call reopens. Test fixture only."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ---------- extract-ir ---------- #

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


# ---------- assemble-wide ---------- #

def assemble_wide(metric_facts: list[dict], run_id: str, table_id: str) -> list[dict]:
    """PIVOT ok-status metric_facts to wide table. Returns list of {branch_num, idx_id@period: Decimal|None, ...}.

    Phase 1 policy:
    - Filter status='ok' before PIVOT. Failed facts become NULL cells (no in-cell sentinels).
      Status info lives in metric_facts.status; aggregate-level sentinels are computed
      separately by assemble_status (task 13) for the runlog.
    - Column type is DECIMAL(38,10). DuckDB PIVOT MAX(DECIMAL) preserves Decimal precision
      (no float() ever — banking precision requirement).
    - Module-level :memory: DuckDB conn (via _get_conn). DROP TABLE at start of each call
      resets state from previous call.
    """
    if not metric_facts:
        return []
    ok_facts = [f for f in metric_facts if f.get("status") == "ok"]
    # Pre-compute distinct_keys from ALL facts (including failed) so wide table
    # has the full column shape — failed cells become NULL, columns aren't dropped.
    distinct_keys = sorted({f"{f.get('idx_id','')}@{f.get('period_alias','')}" for f in metric_facts})
    if not ok_facts:
        # All facts failed; emit one empty row per distinct branch_num so wide table
        # still has all expected columns. Caller can detect via all-NULL cells.
        all_branches = sorted({f.get("branch_num", "") for f in metric_facts})
        if not all_branches:
            return []
        return [{"branch_num": bn, **{k: None for k in distinct_keys}} for bn in all_branches]
    conn = _get_conn()
    conn.execute("DROP TABLE IF EXISTS facts")
    conn.execute(
        "CREATE TABLE facts (branch_num TEXT, col_key TEXT, numeric_value DECIMAL(38,10))"
    )
    for f in ok_facts:
        conn.execute(
            "INSERT INTO facts VALUES (?, ?, ?)",
            [f.get("branch_num", ""),
             f"{f.get('idx_id','')}@{f.get('period_alias','')}",
             f.get("numeric_value")],
        )
    in_clause = ", ".join(f"'{k}'" for k in distinct_keys)
    rows = conn.execute(
        f"""SELECT * FROM facts PIVOT (
              MAX(numeric_value)
              FOR col_key IN ({in_clause})
            )"""
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]