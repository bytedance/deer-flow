# ai-report DuckDB V2: Overview and Modes

## Goal

`ai-report` turns single-table report generation into a multi-table report definition and runtime system.

Design Mode builds and confirms report definitions. Runtime Mode reads an active definition and generates the full report without interactive checkpoints.

## Design Mode

Design Mode input is a newly uploaded table design. The flow is interactive:

```text
load table input
→ lint
→ parse
→ query
→ query checkpoint
→ write metric facts
→ build table frame
→ generate or update compute_sql
→ execute compute_sql
→ compute checkpoint
→ generate description preview
→ description checkpoint
→ render table/report preview
→ apply checkpoint edits to definitions
→ export report_design.md
→ approve table or keep draft
```

Design Mode saves:

- report, section, and table metadata
- approved metrics
- approved compute formulas and `compute_sql`
- description prompts and policies
- checkpoint decisions
- preview artifacts
- final `report_design.md`

## Runtime Mode

Runtime Mode input is an active report definition plus runtime parameters:

```text
run report <report_id>
→ load active definition
→ create run.duckdb
→ snapshot sections and tables
→ build SQLBot query plan
→ query metrics
→ write metric_facts
→ build table_frame per table
→ execute approved compute_sql
→ write computed_facts
→ regenerate description from current data
→ assemble render_payload
→ render report.md/report.docx
```

Runtime Mode rules:

- no interactive checkpoints
- no runtime `compute_sql` code generation
- only active reports and approved tables/computes run
- description is regenerated from current data by default

## Unified Pipeline

The implementation should expose one executor with mode-specific policies:

```python
execute_pipeline(mode="design", context=context)
execute_pipeline(mode="runtime", context=context)
```

The first implementation slice may use smaller direct functions instead of a full executor, but it must preserve this boundary.
