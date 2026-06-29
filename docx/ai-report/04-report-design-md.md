# ai-report DuckDB V2: report_design.md Contract

Design Mode must export a final report design Markdown file:

```text
<report_id>.report_design.md
```

This file is user-reviewable, archivable, and re-importable.

## Source of truth

`definitions.duckdb` is the machine source of truth. `report_design.md` is exported from `definitions.duckdb`.

Do not build `report_design.md` by patching the original uploaded table files.

## Contents

The exported design file includes:

- report metadata
- sections and ordering
- tables and ordering
- table template snapshots
- org defaults
- period aliases
- metric definitions
- compute formulas
- approved `compute_sql`
- description prompts
- failure policies
- last approved design run IDs

## Checkpoint write-back rule

Design checkpoint changes must persist before export:

```text
checkpoint user decision
→ update run_events
→ update draft definition tables
→ export report_design.md from definitions.duckdb
→ render preview / approve
```

Examples:

- query checkpoint choosing `continue_with_sentinel` updates `report_tables.query_failure_policy`
- compute checkpoint formula correction updates `table_computes.formula_text` and `table_computes.compute_sql`
- description checkpoint prompt correction updates `report_tables.description_prompt` or `report_sections.description_prompt`
- ordering changes update `report_sections.section_order` and `report_tables.table_order`
