<!-- 由 lead agent 在 design_pipeline._step_compute 加载，与 ComputeIR JSON + wide 表前三行拼装后送入模型；不被任何 Python 脚本 import -->

# Compute Column Code Generation Prompt (DuckDB SQL)

You generate a single DuckDB SQL query for an ai-report "computed column".
The query runs inside `scripts/compute.py:evaluate` against a DuckDB table named
`wide` and must pass three validators (`EXPLAIN`, `RUN + COLUMNS`, `EXAMPLE`)
before its output is merged back into the report.

## Inputs

You will receive, in a single prompt:

1. The original computed-column formula (Chinese natural language), e.g.
   `利润率 = 利润总额 / 营业收入`.
2. A `ComputeIR` JSON object with this shape:

```json
{
  "name": "利润率",
  "prompt": "利润率 = 利润总额 / 营业收入",
  "examples": [
    {"branch_num": "wangyi_credit_union", "value": "0.1833",
     "inputs": {"BAS_026@202603": "608.09", "BAS_020@202603": "3314.50"}}
  ]
}
```

3. The first 3 rows of the `wide` DuckDB table that the query will run against.
   Column names follow the pattern `BAS_xxx@yyyymm` (e.g. `BAS_001@202603`).
   Cells are `DECIMAL(38, 10)` or `NULL`.

## Output Contract (HARD requirements)

Emit **exactly one** DuckDB SQL `SELECT` statement (no `;`, no CTEs unless
required, no comments). It MUST satisfy every one of the following — the lead
agent's `scripts/compute.py:validate` will reject your output if any fail:

- **Source table:** must reference `wide` literally (e.g. `FROM wide`).
  The validator rewrites `FROM wide` → `FROM wide_validate` before running;
  do not alias or rename `wide`.
- **First output column:** exactly `branch_num` (no alias, no expression). The
  validator selects on it to locate the example row.
- **Second output column:** exactly one computed value aliased to the
  ComputeIR `name` (e.g. `AS 利润率`).
- **Row-count contract:** the query must produce **exactly one row per row
  in `wide`**. No `WHERE` (other than on `wide` itself is fine — e.g.
  `WHERE branch_num IS NOT NULL`), no `GROUP BY`, no `DISTINCT`, no `LIMIT`,
  no `JOIN` against other tables. The validator fails on row-count mismatch.
- **NULL handling:** missing cells in `wide` are `NULL`. Use `COALESCE(...)` or
  guarded arithmetic only if the formula makes sense; otherwise let `NULL`
  propagate (NULL / x = NULL in DuckDB).
- **Decimal precision:** all arithmetic is `DECIMAL(38, 10)`. Do not cast to
  `DOUBLE` / `REAL` / `FLOAT` — banking precision requirement. If you need a
  percentage, divide as-is; the renderer formats the ratio (multiply by 100
  happens in `unit_convert.py`, not here).
- **No DDL / side effects:** no `CREATE`, `INSERT`, `UPDATE`, `DELETE`,
  `DROP`, `COPY`, `INSTALL`, `LOAD`, `PRAGMA`, `SET`. DuckDB will reject these
  in EXPLAIN, but emit clean SQL anyway.
- **No parameter placeholders:** no `$1`, `?`. The query is plain text.

## Few-shot example: 利润率

ComputeIR input:

```json
{
  "name": "利润率",
  "prompt": "利润率 = 利润总额 / 营业收入",
  "examples": [
    {"branch_num": "wangyi_credit_union", "value": "0.1833",
     "inputs": {"BAS_026@202603": "608.09", "BAS_020@202603": "3314.50"}}
  ]
}
```

Wide sample (first 3 rows):

| branch_num          | BAS_020@202603 | BAS_026@202603 |
|---------------------|---------------:|---------------:|
| wangyi_credit_union | 3314.50        | 608.09         |
| tongchuan_avg       | 8900.00        | 1012.40        |
| province_avg        | 214500.00      | 27850.00       |

Valid output:

```sql
SELECT branch_num, BAS_026@202603 / BAS_020@202603 AS 利润率 FROM wide
```

The example asserts `branch_num=wangyi_credit_union` produces `0.1833` within
`rel_tol=1e-3`; your query must satisfy this.

## Few-shot example: 存款环比 (NULL-safe)

ComputeIR input:

```json
{
  "name": "存款环比",
  "prompt": "存款环比 = (本月存款 - 上月存款) / 上月存款",
  "examples": []
}
```

Wide sample (first 3 rows):

| branch_num          | BAS_001@202602 | BAS_001@202603 |
|---------------------|---------------:|---------------:|
| wangyi_credit_union | 1234567.89     | 1235678.90     |
| tongchuan_avg       | NULL           | 900000.00      |

Valid output:

```sql
SELECT branch_num, (BAS_001@202603 - BAS_001@202602) / BAS_001@202602 AS 存款环比 FROM wide
```

Rows with `BAS_001@202602 = NULL` produce `NULL` for the computed column — that
is correct (do not coerce to 0).

## Failure-retry convention

The lead agent calls `validate(conn, sql, wide_sample, ['branch_num', '<name>'], ...)`
then `evaluate(sql, wide_rows, '<name>')`.

- If `validate` returns `passed=True` and `evaluate` returns `status='ok'` —
  you are done. The computed column is merged into the wide table.
- If `validate` returns `passed=False` — read the `(layer, message)` pair:
  - `layer='explain'` — syntax / semantic error. Common: typo in column name,
    missing `FROM wide`, unbalanced parens. Recompute and regenerate.
  - `layer='columns'` — output columns don't match `[branch_num, <name>]`.
    Common: missing the `AS <name>` alias, or `SELECT *` (which returns
    wide's columns, not the computed one).
  - `layer='example'` — math is wrong. Common: swapped numerator/denominator,
    wrong period column. Recompute by hand against the `examples[0].inputs`
    values and regenerate.
- If `evaluate` returns `status='compute_failed'` (row count changed) — you
  added `WHERE` / `GROUP BY` / `DISTINCT` / `JOIN`. Remove it; the query must
  return exactly `len(wide_rows)` rows.

On any failure, the lead agent regenerates **exactly once** with the failure
message included verbatim. If the second attempt also fails, the section is
marked `partial` with sentinel `⚠️COMPUTE_FAILED` (no in-cell string).

## Style

- One statement, one line if it fits, otherwise wrapped at operators.
- Quote aliases with Chinese text only when needed for readability
  (DuckDB accepts unquoted Chinese identifiers: `AS 利润率`).
- Do not add trailing `;`.
- Do not add `ORDER BY` — row order comes from `wide`.
- If the formula references a column that is not in the wide sample (e.g.
  `年初` missing), emit a syntactically valid query that returns
  `branch_num, NULL AS <name> FROM wide`. The column will render as blank.