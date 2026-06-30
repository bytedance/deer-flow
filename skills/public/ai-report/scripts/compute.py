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


# ---------- validate (5 layers) ---------- #

@dataclass
class ValidationResult:
    passed: bool
    layer: str  # "all" if passed; else "explain" | "from_wide" | "branch_num" | "smoke" | "columns" | "example"
    error: str | None = None


def decimal_isclose(a: Decimal, b: Decimal, rel_tol: Decimal = Decimal("1e-3")) -> bool:
    """Decimal-only approximate equality (replaces math.isclose for banking precision).

    |a - b| <= rel_tol * |b|. Zero corner: a == b returns True (rel_tol * 0 is 0).
    """
    a, b = Decimal(a), Decimal(b)
    if a == b:
        return True
    return abs(a - b) <= rel_tol * abs(b)


def validate(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    wide_sample_rows: list[dict],
    expected_columns: list[str],
    example_input: dict | None,
    example_expected: Decimal | None,
) -> ValidationResult:
    """5-layer validation. 无 keyword blacklist (Phase 1 政策).

    conn: caller-provided DuckDB connection (typically Store.conn).

    Layer order:
    1. EXPLAIN (catches syntax/semantic errors on a stub table)
    2. FROM wide text check (cheap, no DB action)
    3. BRANCH_NUM text check (cheap, no DB action)
    4. smoke (SAMPLE 3 ROWS on real sample rows)
    5. example (Decimal precision check on one row)

    Why stub for EXPLAIN: DuckDB EXPLAIN resolves table references. Without a
    stub `wide` table, EXPLAIN fails on missing-table for SQL that passes text
    checks (e.g. `SELECT branch_num, 1 AS x FROM wide`). Stub ensures EXPLAIN
    only catches actual SQL-level errors.
    """
    stub_created = False
    try:
        # Pre-create stub wide for EXPLAIN (idempotent; ignore if already exists)
        try:
            conn.execute("CREATE TEMP TABLE _validate_wide_stub (branch_num VARCHAR)")
            stub_created = True
        except Exception:
            pass

        # 第 1 层: EXPLAIN (with wide → stub)
        explain_sql = sql.replace("FROM wide", "FROM _validate_wide_stub").replace(
            "from wide", "from _validate_wide_stub"
        )
        try:
            conn.execute(f"EXPLAIN {explain_sql}")
        except Exception as e:
            return ValidationResult(False, "explain", str(e))

        # 第 2 层: FROM wide
        upper = sql.upper()
        if "FROM WIDE" not in upper:
            return ValidationResult(False, "from_wide", "SQL must contain 'FROM wide'")

        # 第 3 层: branch_num
        if "BRANCH_NUM" not in upper:
            return ValidationResult(False, "branch_num", "SQL must SELECT branch_num")

        # 建 TEMP TABLE wide_validate, 灌入 sample rows
        if wide_sample_rows:
            cols = list(wide_sample_rows[0].keys())
            col_defs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            conn.execute(f"CREATE TEMP TABLE wide_validate ({col_defs})")
            for row in wide_sample_rows:
                conn.execute(
                    f"INSERT INTO wide_validate VALUES ({', '.join(['?'] * len(cols))})",
                    [str(row.get(c, "")) for c in cols],
                )
        else:
            conn.execute("CREATE TEMP TABLE wide_validate (branch_num VARCHAR)")

        # 隔离 caller schema: wide → wide_validate
        exec_sql = sql.replace("FROM wide", "FROM wide_validate").replace(
            "from wide", "from wide_validate"
        )

        # 第 4 层: smoke (SAMPLE 3 ROWS)
        try:
            smoke_sql = f"SELECT * FROM ({exec_sql}) USING SAMPLE 3 ROWS"
            result = conn.execute(smoke_sql).fetchall()
            if not result:
                return ValidationResult(False, "smoke", "SAMPLE 3 ROWS returned no rows")
        except Exception as e:
            return ValidationResult(False, "smoke", str(e))

        # 第 4.5 层: 输出列 ⊇ expected_columns
        if expected_columns:
            cols_returned = [d[0] for d in conn.description]
            missing = [c for c in expected_columns[1:] if c not in cols_returned]
            if missing:
                return ValidationResult(False, "columns", f"missing output columns: {missing}")

        # 第 5 层: example (Decimal 精度)
        if example_input is not None and example_expected is not None:
            try:
                target_branch = example_input.get("branch_num", "")
                row = conn.execute(
                    f"SELECT * FROM ({exec_sql}) WHERE branch_num=? LIMIT 1", [target_branch]
                ).fetchone()
                if not row:
                    return ValidationResult(False, "example", f"no row for branch_num={target_branch}")
                actual = row[1] if len(row) > 1 else None
                if actual is None:
                    return ValidationResult(False, "example", "actual value is None")
                actual_d = Decimal(str(actual))
                expected_d = Decimal(str(example_expected))
                if not decimal_isclose(actual_d, expected_d):
                    return ValidationResult(False, "example", f"expected {expected_d}, got {actual_d}")
            except Exception as e:
                return ValidationResult(False, "example", str(e))

        return ValidationResult(True, "all", None)
    finally:
        # 清理 TEMP TABLEs (避免 store.conn 长生命周期泄漏)
        for t in ("wide_validate", "_validate_wide_stub"):
            try:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            except Exception:
                pass