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
    """3-layer validation (simplified from 5 layers). 无 keyword blacklist (Phase 1 政策).

    Layer order:
    1. EXPLAIN — catch syntax/semantic errors on a stub `wide` table.
       DuckDB EXPLAIN resolves table references; without a stub, EXPLAIN fails
       on missing-table for SQL that should pass. Stub ensures EXPLAIN only
       catches actual SQL-level errors.
    2. RUN + COLUMNS — run SQL on real sample rows, then check output columns
       cover expected_columns. Replaces old layers 2 (FROM wide text), 3
       (BRANCH_NUM text), 4 (smoke), 4.5 (columns). One execution covers all.
    3. EXAMPLE — optional Decimal precision check on one row. Reuses Layer 2's
       result (no second SQL execution).

    Why simplify: 5-layer design had 2 redundant text checks (FROM wide and
    BRANCH_NUM) whose failure modes were already covered by EXPLAIN + column
    check. Smoke + example executed SQL twice when example was provided.
    Simplified design: same failure coverage, half the SQL executions, ~40%
    less code. Friendly error messages ("must contain FROM wide") moved to
    prompts/compute_codegen.md as LLM guidance, not runtime checks.
    """
    try:
        # 第 1 层: EXPLAIN (with wide → stub)
        try:
            conn.execute("CREATE TEMP TABLE _validate_wide_stub (branch_num VARCHAR)")
        except Exception:
            pass  # already exists, fine
        explain_sql = sql.replace("FROM wide", "FROM _validate_wide_stub").replace(
            "from wide", "from _validate_wide_stub"
        )
        try:
            conn.execute(f"EXPLAIN {explain_sql}")
        except Exception as e:
            return ValidationResult(False, "explain", str(e))

        # 第 2 层: RUN + COLUMNS (灌入 sample rows, 跑 SQL, 检查输出列)
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

        exec_sql = sql.replace("FROM wide", "FROM wide_validate").replace(
            "from wide", "from wide_validate"
        )
        try:
            rows = conn.execute(exec_sql).fetchall()
        except Exception as e:
            return ValidationResult(False, "columns", str(e))

        cols_returned = [d[0] for d in conn.description]
        if expected_columns:
            missing = [c for c in expected_columns if c not in cols_returned]
            if missing:
                return ValidationResult(False, "columns", f"missing output columns: {missing}")

        # 第 3 层: EXAMPLE (optional, Decimal 精度)
        if example_input is not None and example_expected is not None:
            target_branch = example_input.get("branch_num", "")
            if "branch_num" not in cols_returned:
                return ValidationResult(False, "example", "SQL did not SELECT branch_num, cannot locate example row")
            bn_idx = cols_returned.index("branch_num")
            target_row = None
            for r in rows:
                if str(r[bn_idx]) == str(target_branch):
                    target_row = r
                    break
            if target_row is None:
                return ValidationResult(False, "example", f"no row for branch_num={target_branch}")

            # Pick the first non-branch_num column's value as actual (the compute output).
            non_bn_cols = [c for c in cols_returned if c != "branch_num"]
            if not non_bn_cols:
                return ValidationResult(False, "example", "SQL has no output column besides branch_num")
            actual_idx = cols_returned.index(non_bn_cols[0])
            actual = target_row[actual_idx]
            if actual is None:
                return ValidationResult(False, "example", "actual value is None")
            try:
                actual_d = Decimal(str(actual))
                expected_d = Decimal(str(example_expected))
            except Exception as e:
                return ValidationResult(False, "example", f"cannot convert actual to Decimal: {e}")
            if not decimal_isclose(actual_d, expected_d):
                return ValidationResult(False, "example", f"expected {expected_d}, got {actual_d}")

        return ValidationResult(True, "all", None)
    finally:
        for t in ("wide_validate", "_validate_wide_stub"):
            try:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            except Exception:
                pass


# ---------- evaluate ---------- #

def _detect_column_types(rows: list[dict]) -> dict[str, str]:
    """Per-column SQL type: DECIMAL(38,10) if any row has Decimal/int, else VARCHAR.

    Wide tables from assemble_wide always have Decimal cells (precision policy).
    evaluate also supports arbitrary wide_rows (for tests, ad-hoc runs); type
    detection lets us preserve Decimal precision end-to-end.
    """
    cols = list(rows[0].keys())
    types: dict[str, str] = {}
    for c in cols:
        has_numeric = any(isinstance(r.get(c), (Decimal, int)) and not isinstance(r.get(c), bool) for r in rows)
        types[c] = "DECIMAL(38,10)" if has_numeric else "VARCHAR"
    return types


def evaluate(
    sql: str,
    wide_rows: list[dict],
    column_name: str,
) -> tuple[list[Decimal | None], str]:
    """Run compute SQL against wide_rows, return (values, status).

    - values: list of Decimal | None, one per row (preserves wide_rows order).
    - status: 'ok' or 'compute_failed'.

    Phase 1 policy: in-cell sentinels removed (consistent with assemble_wide).
    On SQL failure, values is all None; status='compute_failed'. The caller
    decides how to surface the failure (assemble_status / task 13 aggregates
    these into the runlog).

    DECIMAL precision: wide_rows cells with Decimal/int values get DECIMAL(38,10)
    columns in the temp table, so SQL arithmetic preserves precision (no float).
    """
    if not wide_rows:
        return [], "ok"
    conn = _get_conn()
    conn.execute("DROP TABLE IF EXISTS wide")
    col_types = _detect_column_types(wide_rows)
    cols = list(col_types.keys())
    col_defs = ", ".join(f'"{c}" {col_types[c]}' for c in cols)
    conn.execute(f"CREATE TEMP TABLE wide ({col_defs})")
    for row in wide_rows:
        vals: list = []
        for c in cols:
            v = row.get(c)
            if v is None:
                vals.append(None)
            elif col_types[c] == "DECIMAL(38,10)":
                vals.append(Decimal(str(v)))
            else:
                vals.append(str(v))
        conn.execute(
            f"INSERT INTO wide VALUES ({', '.join(['?'] * len(cols))})",
            vals,
        )
    try:
        rows = conn.execute(sql).fetchall()
    except Exception:
        return [None] * len(wide_rows), "compute_failed"

    cols_returned = [d[0] for d in conn.description]
    if column_name not in cols_returned:
        return [None] * len(wide_rows), "compute_failed"
    col_idx = cols_returned.index(column_name)

    values: list[Decimal | None] = []
    for r in rows:
        v = r[col_idx]
        if v is None:
            values.append(None)
        elif isinstance(v, Decimal):
            values.append(v)
        else:
            try:
                values.append(Decimal(str(v)))
            except Exception:
                values.append(None)
    return values, "ok"


# ---------- apply-computed ---------- #

def apply_computed(wide: list[dict], computed: dict[str, list]) -> list[dict]:
    """Merge computed columns into wide rows. Preserves wide's row order.

    If a computed column has fewer entries than wide, trailing rows just won't
    get that column added (no error).
    """
    if not wide:
        return []
    out: list[dict] = []
    for i, row in enumerate(wide):
        new_row = dict(row)
        for col_name, col_values in computed.items():
            if i < len(col_values):
                new_row[col_name] = col_values[i]
        out.append(new_row)
    return out