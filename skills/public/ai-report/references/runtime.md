# ai-report Runtime Pipeline Reference

Read this when invoking the runtime CLI, debugging a runtime failure, or
changing the read-only path from `approved_runs` to final outputs.

## Entry point

`scripts/runtime_pipeline.py` exposes a 5-step orchestrator
(`RuntimePipeline.run_report`) and a thin CLI wrapper.

```bash
python scripts/runtime_pipeline.py \
    --db-path /mnt/ai-report-data/duckdb \
    --report-id <report_id> \
    --out-dir /mnt/ai-report-data \
    [--strict]
```

Default `--db-path` and `--out-dir` match the design pipeline so a freshly
approved run can be rendered without flags.

## Step-by-step

### R-0: existence check

`Store.get_report_meta(report_id)`. If missing → CLI exits 1 with
`❌ report_id 不存在: <id>` on stderr. No `status.json` written.

This is a hard precondition: a runtime invocation against an unknown
report_id is a user error, not a recoverable runtime error.

### R-1: pull approved tables

`Store.list_approved_tables(report_id)` returns one row per
`(section_id, run_id)` in `approved_runs` where the design pipeline wrote
`status='ok'` or `status='partial'`.

- If the list is empty:
  - non-strict: exit 1, stderr `⚠️ 报告 {report_id} 没有任何 approved section, 请先运行 design pipeline 完成 design`.
  - strict: raise RuntimeError (caller wants loud failure).

### R-2: build payload

`report_md.build_runtime_payload(Store, report_id)` joins
`reports` × `approved_runs` × `report_sections` × `report_tables` into the
shape `render_markdown.py` and `render_docx.py` expect:

```python
{
  "title": str,
  "sections": [
    {
      "section_title": str,
      "reports": [{
        "title": str,
        "description": str | None,
        "headers": list[list[dict]],  # 2D headers_2d
        "rows": list[dict],            # wide rows
        "sentinels": list[str],        # ⚠️ codes
        "computed_sentinels": dict,
      }],
    },
  ],
}
```

`description` may be a `list[str]` (legacy) or `list[{"text": str}]` (post-fix).
`report_md._coerce_description` normalizes both.

### R-2.5: ensure out_dir exists

`Path(out_dir).mkdir(parents=True, exist_ok=True)`. Fixes Issue 19 (CLI
first-run would FileNotFoundError before this).

### R-3: render markdown

`render_markdown.render_markdown(payload)` → `<report_id>.report.md`.

Pure text, no styling. Used as the chat-shared preview when docx is too
heavy to paste.

### R-4: render docx

`render_docx.render_docx(payload, out_path, style_path=...)` →
`<report_id>.report.docx`. Style path defaults to
`scripts/report_style.json` (same as the legacy `report_docx.py`).

### R-5: 中文回执

`assemble_status.build_status` aggregates per-section sentinels from
`approved_runs.sentinels` (JSON list of ⚠️ codes) and the runlog. Output is:

- written to `status.json` (machine-readable)
- printed to stdout via `format_zh_receipt` (Chinese, user-facing)
- the stdout print is `flush=True` so it lands in the chat before any
  subsequent tool call

Exit code is always 0 in R-5 — partial success is not a runtime error.

## Strict mode

`--strict` upgrades R-1's "empty" branch from a soft exit-1 to a
RuntimeError. Use it in CI or smoke tests where you want the failure loud.

## Failure modes

| Step | Failure | Exit | stderr | stdout |
|---|---|---:|---|---|
| R-0 | report_id not found | 1 | `❌ report_id 不存在: <id>` | — |
| R-1 | no approved sections (non-strict) | 1 | `⚠️ 报告 ... 没有任何 approved section` | — |
| R-1 | no approved sections (strict) | 1 | `FAIL: strict mode: no approved tables for <id>` | — |
| R-2..R-5 | any unhandled exception | 1 | `FAIL: <exception>` | — |
| R-5 | partial section (sentinels present) | 0 | — | 中文回执 含 ⚠️ 行 |
| R-5 | all sections ok | 0 | — | 中文回执 全部 ✅ |

R-5 always prints the receipt — partial reports are still deliverables.

## What runtime does NOT do

- Re-query SQLBot. Once a section is approved, its `metric_facts` are frozen.
- Re-run compute. Computed columns live in `approved_runs.wide_table` as
  already-evaluated `Decimal` strings.
- Re-validate or re-lint. Source MD is hashed at design time; runtime
  trusts the approved payload.
- Touch `metric_facts`, `compute_irs`, or any design-time state. Runtime is
  read-only over the DuckDB store.

## Re-rendering after design changes

If the user edits the source MD and re-runs the design pipeline:

1. `Store.upsert_report` writes a new `src_hash` for the same `report_id`.
2. Old `approved_runs` rows are kept (audit trail) but excluded from
   `list_approved_tables` for runtime rendering, because they reference a
   stale `table_id`.
3. The new design pipeline writes fresh `approved_runs` for the new
   `table_id`.
4. Runtime CLI then renders the freshest approved runs.

To force rendering of an older approved run (e.g. for diff comparison),
read `approved_runs` directly via DuckDB CLI — runtime_pipeline does not
expose this.