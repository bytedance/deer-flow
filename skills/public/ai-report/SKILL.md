---
name: ai-report
description: Design and run multi-table DuckDB-backed AI reports from approved report definitions.
---

# ai-report

Use this skill for DuckDB V2 report design and runtime experiments.

## Current status

This skill is a self-contained DuckDB V2 implementation. It does not depend on any other skill in the workspace.

## Runtime model

Design Mode saves approved report definitions into `definitions.duckdb` and exports `report_design.md`.

Runtime Mode reads an active definition, writes a per-run `run.duckdb`, executes approved `compute_sql`, regenerates descriptions from current data, assembles `render_payload`, and renders final outputs without interactive checkpoints.

## Implementation notes

- Keep V2 modules under `skills/public/ai-report/scripts/ai_report/`.
- Keep tests under `skills/public/ai-report/scripts/tests/`.
- Use `docx/ai-report/` as the design and plan source.
