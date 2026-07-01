"""ai-report compute (新写, 纯 DuckDB, 无 pandas). 5 sub-commands: assemble-wide / extract-ir / validate / evaluate / apply-computed.

Phase 1 政策:
- 数据层纯 DuckDB DECIMAL(38,10), 无 float (银行精度要求)
- 失败 cell 不编码哨兵字符串, NULL 留空; 哨兵聚合走 assemble_status (task 13)
- DuckDB 连接模型:
  - assemble_wide / evaluate: 每次 call 新建 :memory: conn (per-call), 5ms 开销换线程安全
    (DuckDB connection 不是线程安全, 共享单例在多 thread 调用下会炸)
  - validate: caller 注入 conn (typically Store.conn), 因为 TEMP TABLE 生命周期
    需要跟随 caller 事务; caller 自己保证线程安全 (Store._write_lock)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import duckdb


# ---------- per-call :memory: conn (线程安全, 每次新建) ---------- #

def _new_conn() -> duckdb.DuckDBPyConnection:
    """Create a fresh :memory: DuckDB connection.

    Why per-call (not module singleton): DuckDB connection is NOT thread-safe.
    If assemble_wide / evaluate share a module-level conn, concurrent threads
    calling them will interleave execute() and corrupt state. Per-call costs
    ~5ms but guarantees isolation.

    Why :memory: (not Store.conn): these are pure in-memory transforms
    (input list[dict] → output list[dict]); no persistent table is read or
    written. validate() takes caller-injected conn because its TEMP TABLE
    lifecycle follows the caller transaction.
    """
    return duckdb.connect(":memory:")


# ---------- extract-ir ---------- #

@dataclass
class ComputeIR:
    name: str
    prompt: str
    examples: list[dict] = field(default_factory=list)


def _parse_example(tail: str) -> dict | None:
    """Parse `BAS_0263[current=1420, yoy_same=1200] -> 0.1833` into a dict.

    Used by chatbi-report-style `> 计算:` blocks (with `.示例:` suffix).
    """
    m = re.match(r"^([A-Z]+_\d+)\s*\[(.*?)\]\s*->\s*(\S+)$", tail)
    if not m:
        return None
    inputs_str = m.group(2)
    inputs: dict[str, str] = {}
    for kv in re.findall(r"(\w+)\s*=\s*([^,]+)", inputs_str):
        inputs[kv[0].strip()] = kv[1].strip()
    return {"inputs": inputs, "expected": m.group(3)}


def extract_ir(body: str) -> list[ComputeIR]:
    """Parse the `> 计算:` block into a list of ComputeIR.

    Canonical ai-report form (single accepted form):
        > 计算:
        >   2023利润同比 = 2023年值减2022年值再除2022年值
        >   2024利润同比 = 2024年值减2023年值再除2023年值
        >   2024利润同比.示例: BAS_0263[2024=1200, 2023=1000] -> 0.2

    `name = prompt` defines a computed column; `<name>.示例: ...` attaches
    an example (parsed as {inputs: {...}, expected: "..."}) for validate's
    example layer to check.
    """
    compute_match = re.search(
        r"^>\s*计算:\s*\n(.*?)(?=^>[^ \n]|\Z)", body, re.MULTILINE | re.DOTALL
    )
    if not compute_match:
        return []
    by_name: dict[str, ComputeIR] = {}
    for raw in compute_match.group(1).splitlines():
        # Block boundary: non-`>` line (e.g. <table>) ends the `> 计算:` block.
        if not raw.lstrip().startswith(">"):
            break
        line = raw.lstrip("> ").strip()
        if not line:
            continue
        if ".示例:" in line:
            head, _, tail = line.partition(".示例:")
            name = head.strip()
            ex = _parse_example(tail.strip())
            if name in by_name and ex is not None:
                by_name[name].examples.append(ex)
            continue
        if "=" not in line:
            continue
        name, expr = (s.strip() for s in line.split("=", 1))
        by_name[name] = ComputeIR(
            name=name, prompt=f"{name} = {expr}", examples=[],
        )
    return list(by_name.values())


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
    conn = _new_conn()
    try:
        conn.execute(
            "CREATE TABLE facts (branch_num TEXT, col_key TEXT, numeric_value DECIMAL(38,10))"
        )
        rows_to_insert = [
            [f.get("branch_num", ""),
             f"{f.get('idx_id','')}@{f.get('period_alias','')}",
             f.get("numeric_value")]
            for f in ok_facts
        ]
        conn.executemany("INSERT INTO facts VALUES (?, ?, ?)", rows_to_insert)
        in_clause = ", ".join(f"'{k}'" for k in distinct_keys)
        rows = conn.execute(
            f"""SELECT * FROM facts PIVOT (
                  MAX(numeric_value)
                  FOR col_key IN ({in_clause})
                )"""
        ).fetchall()
        cols = [d[0] for d in conn.description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


# ---------- validate (3 layers) + evaluate + apply-computed ---------- #

@dataclass
class ValidationResult:
    passed: bool
    layer: str  # "all" if passed; else "explain" | "columns" | "example"
    error: str | None = None


def decimal_isclose(a: Decimal, b: Decimal, rel_tol: Decimal = Decimal("1e-3")) -> bool:
    """Decimal-only approximate equality (replaces math.isclose for banking precision).

    |a - b| <= rel_tol * |b|. Zero corner: a == b returns True (rel_tol * 0 is 0).
    rel_tol=1e-3 (0.1%) is loose enough to tolerate LLM SQL rounding differences
    but tight enough to catch real semantic errors.
    """
    a, b = Decimal(a), Decimal(b)
    if a == b:
        return True
    return abs(a - b) <= rel_tol * abs(b)


def _detect_column_types(rows: list[dict]) -> dict[str, str]:
    """Per-column SQL type: DECIMAL(38,10) only if ALL non-None values are numeric.

    P1-6 fix: previous logic promoted to DECIMAL if ANY row was numeric, which
    blew up on INSERT when another row had a string in the same column. Now
    requires uniform numeric content; mixed → VARCHAR (loses precision but
    doesn't raise; mixed columns are not expected from assemble_wide output).
    """
    cols = list(rows[0].keys()) if rows else []
    types: dict[str, str] = {}
    for c in cols:
        non_none = [r.get(c) for r in rows if r.get(c) is not None]
        all_numeric = bool(non_none) and all(
            isinstance(v, (Decimal, int)) and not isinstance(v, bool) for v in non_none
        )
        types[c] = "DECIMAL(38,10)" if all_numeric else "VARCHAR"
    return types


def _materialize_wide_table(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
    table_name: str,
) -> None:
    """Create TEMP TABLE `table_name` from `rows` with type-inferred columns.

    Shared by validate (caller conn) and evaluate (module conn). Fixes:
    - P1-1: both use _detect_column_types so SQL behavior is identical
      (no VARCHAR/DECIMAL divergence between validate-pass and evaluate-fail).
    - P1-3: executemany batch-insert replaces N+1 execute() loop.
    - P1-6: _detect_column_types falls back to VARCHAR on mixed columns.
    """
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    if not rows:
        conn.execute(f"CREATE TEMP TABLE {table_name} (branch_num VARCHAR)")
        return
    col_types = _detect_column_types(rows)
    cols = list(col_types.keys())
    col_defs = ", ".join(f'"{c}" {col_types[c]}' for c in cols)
    conn.execute(f"CREATE TEMP TABLE {table_name} ({col_defs})")
    placeholders = ", ".join(["?"] * len(cols))
    batch: list[list] = []
    for row in rows:
        vals: list = []
        for c in cols:
            v = row.get(c)
            if v is None:
                vals.append(None)
            elif col_types[c] == "DECIMAL(38,10)":
                vals.append(v if isinstance(v, Decimal) else Decimal(str(v)))
            else:
                vals.append(str(v))
        batch.append(vals)
    conn.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", batch)


def validate(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    wide_sample_rows: list[dict],
    expected_columns: list[str],
    example_input: dict | None,
    example_expected: Decimal | None,
) -> ValidationResult:
    """3-layer validation. 无 keyword blacklist (Phase 1 政策).

    Layer order:
    1. EXPLAIN — catch syntax/semantic errors. Materializes wide_validate first
       (real columns) so EXPLAIN sees actual column references; no separate stub.
    2. RUN + COLUMNS — execute SQL on the materialized sample rows, then check
       output columns cover expected_columns.
    3. EXAMPLE — optional Decimal precision check on one row. Reuses Layer 2's
       result (no second SQL execution).
    """
    try:
        # Materialize sample rows into wide_validate (shared with evaluate for
        # column-type consistency). Done BEFORE EXPLAIN so column references
        # resolve to real columns.
        _materialize_wide_table(conn, wide_sample_rows, "wide_validate")
        exec_sql = sql.replace("FROM wide", "FROM wide_validate").replace(
            "from wide", "from wide_validate"
        )

        # 第 1 层: EXPLAIN
        try:
            conn.execute(f"EXPLAIN {exec_sql}")
        except duckdb.Error as e:
            return ValidationResult(False, "explain", str(e))

        # 第 2 层: RUN + COLUMNS
        try:
            rows = conn.execute(exec_sql).fetchall()
        except duckdb.Error as e:
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
            except (ValueError, ArithmeticError) as e:
                return ValidationResult(False, "example", f"cannot convert actual to Decimal: {e}")
            if not decimal_isclose(actual_d, expected_d):
                return ValidationResult(False, "example", f"expected {expected_d}, got {actual_d}")

        return ValidationResult(True, "all", None)
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS wide_validate")
        except duckdb.Error:
            pass


# ---------- evaluate ---------- #

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

    Row-count contract (P0-1): if SQL has WHERE/GROUP BY/DISTINCT that changes
    row count, status='compute_failed' (silent truncation is a data bug).

    DECIMAL precision: wide_rows cells with Decimal/int values get DECIMAL(38,10)
    columns via _materialize_wide_table, shared with validate() so behavior
    is identical (P1-1).
    """
    if not wide_rows:
        return [], "ok"
    conn = _new_conn()
    try:
        _materialize_wide_table(conn, wide_rows, "wide")
        try:
            rows = conn.execute(sql).fetchall()
        except duckdb.Error:
            return [None] * len(wide_rows), "compute_failed"

        # P0-1: row count must match wide_rows (no silent truncation by WHERE/etc.)
        if len(rows) != len(wide_rows):
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
                except (ValueError, ArithmeticError):
                    values.append(None)
        return values, "ok"
    finally:
        conn.close()


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