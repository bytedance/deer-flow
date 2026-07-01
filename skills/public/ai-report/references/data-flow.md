# ai-report Data Flow Reference

Read this when changing `parse_md`, `compute`, `unit_convert`, `Store`,
or any path that crosses between DuckDB tables, Python dataclasses, and
JSON-serialized wide tables.

## Layered shape

```text
MD source ─→ ReportDoc (parse_md)
           ─→ ReportSplit (report_split) → section blocks
           ─→ metric_facts rows (sqlbot_client)
           ─→ wide rows (compute.assemble_wide, DuckDB)
           ─→ ComputeIR (compute.extract_ir)
           ─→ DuckDB SQL (LLM, prompts/compute_codegen.md)
           ─→ computed values (compute.evaluate)
           ─→ merged wide (compute.apply_computed)
           ─→ converted wide (unit_convert.apply_units)
           ─→ approved_runs row (Store.save_approved_run)
           ─→ runtime payload (report_md.build_runtime_payload)
           ─→ MD + DOCX (render_markdown + render_docx)
```

Two precision boundaries:

1. **MD → dataclass → metric_facts**: Python `Decimal`. No float conversion
   anywhere on the bank-precision path.
2. **wide rows → DuckDB SQL → computed values**: DuckDB `DECIMAL(38,10)`.
   SQL engine never sees `DOUBLE` / `REAL` / `FLOAT` for monetary columns.

Both boundaries persist to DuckDB JSON columns as `str(Decimal)` so the
exact decimal survives serialization round-trip.

## Tables (DuckDB)

Created by `Store.init_schema()` (called from `Store.open()`). Idempotent
on every open.

| Table | Purpose | Key columns |
|---|---|---|
| `reports` | one row per uploaded source MD | `report_id` PK, `src_hash` |
| `report_sections` | H2 sections from MD | `(report_id, section_order)` PK |
| `report_tables` | H3 tables within sections | `table_id` PK, FK → section |
| `metric_facts` | per-idx × period raw values | `run_id`, `idx_id`, `period_alias`, `numeric_value DECIMAL(38,10)`, `status` |
| `compute_irs` | parsed `> 计算:` blocks | `ir_id` PK, `name`, `prompt`, `examples` (JSON) |
| `approved_runs` | one row per approved section run | `run_id` PK, `table_id`, `wide_table` (JSON), `sentinels` (JSON), `status`, `src_hash`, `runlog` |

Foreign keys are intentionally NOT declared on `metric_facts.run_id` due
to a DuckDB 1.5.2 quirk: `UPDATE` on `approved_runs` with children in
`metric_facts` raises. Drop the FK; rely on application-level invariants.

## Data shape transitions

### 1. `ReportDoc` (parse_md dataclass)

```python
@dataclass
class ReportDoc:
    title: str
    sections: list[ReportSection]   # one per H2
    all_idx_ids: list[str]
    all_org_contexts: list[OrgContext]
    all_time_info: list[str]

@dataclass
class ReportSection:
    section_title: str
    reports: list[ReportTable]      # one per H3 in this section
    org_contexts: list[OrgContext]
    time_info: list[str]

@dataclass
class ReportTable:
    title: str                      # H3 text
    headers: list[list[Th]]         # 2D, each Th is dict-like
    source_md: str
    description_prompt: str | None
    compute_block_md: str

@dataclass
class Th:
    text: str
    idx_id: str | None = None
    period: str | None = None
    data_unit: str | None = None
    is_computed: bool = False       # True only for `data-computed` cells
    rowspan: int = 1
    colspan: int = 1
```

Bug A 修复 (Phase 1): `is_computed` is set ONLY when the HTML attribute
`data-computed` is present. Cells with `data-idx` (real indicator columns)
have `is_computed=False`. Previously, the parser incorrectly marked
indicator cells as computed, breaking `unit_convert` + `render_markdown`
cell-key lookups (they looked up by text label instead of `idx_id@period`
→ all cells rendered as "—").

### 2. `metric_facts` row

```python
{
    "branch_num": "wangyi_credit_union",
    "branch_short_name": "王益联社",
    "idx_id": "BAS_001",
    "period_alias": "202603",
    "period_value": "2026-03-01",
    "raw_value": "1234567890.50",
    "numeric_value": Decimal("1234567890.50"),
    "status": "ok" | "query_failed" | "cast_failed",
    "error_message": None | "SQLBotError: code=500 ...",
}
```

`numeric_value` is `DECIMAL(38,10)` in DuckDB. `raw_value` is `str` so
unparseable inputs are preserved as audit trail.

### 3. wide row (assemble_wide output)

```python
{
    "branch_num": "wangyi_credit_union",
    "BAS_001@202602": Decimal("12345678.9012345678"),
    "BAS_001@202603": Decimal("12345678.9012345679"),
}
```

Column naming: `f"{idx_id}@{period_alias}"`. The `@` separator is
load-bearing — never use it in `idx_id` or `period_alias` (both are
validated upstream).

Cells are `Decimal | None`. Failed facts contribute `None` (no in-cell
sentinel). Wide shape includes ALL `idx_id@period` keys from ALL facts
(ok + failed), so downstream code can render the full column structure
even on partial failure.

### 4. approved_runs.wide_table (JSON in DuckDB)

```json
[
  {
    "branch_num": "wangyi_credit_union",
    "BAS_001@202603": "12345678.9012345678",
    "利润率": "0.1833"
  }
]
```

`Decimal` cells become `str` via `DesignPipeline._jsonify_wide` so JSON
serialization round-trips. Renderers parse `str` back to `Decimal` /
`float` only at the boundary.

Computed columns are keyed by `ComputeIR.name` (Chinese text label, e.g.
`"利润率"`). The renderer distinguishes them from `idx_id@period` keys via
`headers_2d[i][j].is_computed`.

### 5. runtime payload (final shape)

```python
{
    "title": "王益联社 2026 年 3 月经营分析报告",
    "sections": [
        {
            "section_title": "存款业务",
            "reports": [{
                "title": "存款规模",
                "description": "2026年3月末, 王益联社存款余额...",  # str | None
                "headers": [[{"text": "机构", "rowspan": 2, ...},
                            {"text": "存款余额", "colspan": 2, "data_unit": "万元"}], ...],
                "rows": [{"branch_num": "wangyi_credit_union",
                          "BAS_001@202603": "12345678.9012345678", ...}],
                "sentinels": ["⚠️QUERY_FAILED"],        # ⚠️ codes, raw names never
                "computed_sentinels": {},              # reserved, always {}
            }],
        },
    ],
}
```

`description` is normalized via `report_md._coerce_description` to handle
both legacy `list[str]` and post-fix `list[{"text": str}]` formats.

## Sentinel lifecycle

| Stage | Where | Format |
|---|---|---|
| `_step_query_metrics` emits | fact row | `status='query_failed'` |
| `_step_query_metrics` emits | fact row | `status='cast_failed'` (Decimal cast fails) |
| `_step_compute` emits | `failed_compute: list[str]` | ComputeIR names |
| Step 14 normalizes | `sentinels: list[str]` | ⚠️ codes only |
| `save_approved_run` | `approved_runs.sentinels` (JSON) | codes |
| `build_status` reads | aggregates per-code counts | codes |
| `format_zh_receipt` | stdout Chinese receipt | `⚠️QUERY_FAILED × N` per code |

Never write raw names (`"利润率"`, `"BAS_001@202603"`) into `sentinels`.
Bug B 修复 (Phase 1): previously design pipeline stored raw names, which
`build_status` then counted as 0 (by-code miss) — silent underreporting
of partial failures.

## Decimal precision rules

1. `metric_facts.numeric_value` is `DECIMAL(38,10)`. Never `DOUBLE`.
2. `assemble_wide` PIVOT uses `MAX(DECIMAL)` to preserve precision (no
   aggregation side-effects; MAX of one value = the value).
3. `apply_units` is pure Python `Decimal` arithmetic:
   `Decimal("10000") * Decimal("0.0001")` = `Decimal("1.0000")` (exact).
   Never `1e8` or `10**8` (those produce `float`).
4. `compute.validate` layer 3 (EXAMPLE check) compares Decimal-to-Decimal
   with `decimal_isclose` (rel_tol=1e-3).
5. Renderers parse `str` back to `Decimal` at boundary:
   - `render_docx._format_value` casts `str → float` for display. This is
     display-only; the underlying `Decimal` is already lost via JSON
     round-trip and is not used for downstream compute.
6. `unit_convert.apply_units` non-Decimal cell → skipped (no crash, no
   silent float coercion).

## Thread safety

DuckDB connections are NOT thread-safe. The store uses:

- `Store.conn` — protected by `Store._write_lock` (threading.Lock) for
  any state-changing operation (INSERT/UPDATE/DELETE). Reads bypass the
  lock and rely on DuckDB MVCC.
- `compute._new_conn()` — fresh `:memory:` connection per call (~5ms).
  Used by `assemble_wide` and `evaluate`.
- `compute.validate` — caller-injected `conn` (typically `Store.conn`
  inside `_write_lock` block). Caller responsibility.

Single-process multi-thread is supported. Multi-process (e.g. two design
runs on the same `db_path`) is NOT — DuckDB file is single-writer.

## File paths (canonical)

| Path | Owner | Lifetime |
|---|---|---|
| `/mnt/ai-report-data/duckdb` | Store | persistent across runs |
| `/mnt/ai-report-data/<report_id>.design.md` | design pipeline | persistent |
| `/mnt/ai-report-data/<report_id>.report.md` | runtime R-3 | persistent |
| `/mnt/ai-report-data/<report_id>.report.docx` | runtime R-4 | persistent |
| `/mnt/ai-report-data/<report_id>.status.json` | runtime R-5 | persistent |

`/mnt/ai-report-data/` is the canonical ai-report data root (NOT
`/mnt/user-data/`, NOT the workspace root). Memory:
`ai-report-global-duckdb-path`.

## What the renderer does NOT see

- Raw `metric_facts` rows. The renderer only sees `wide_table` after
  unit conversion.
- ComputeIR objects. They live only in `compute_irs` table for audit.
- LLM prompt text. Only the rendered output reaches the renderer.
- DuckDB row IDs. All cross-table joins are by `run_id` / `table_id`.