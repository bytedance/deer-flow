# ai-report DuckDB V2: run report Data Flow

## Definition source

Runtime reads definitions from `definitions.duckdb`:

```text
reports(status = active)
→ report_sections(enabled = true)
→ report_tables(approval_status = approved)
→ table_metrics(approval_status = approved)
→ table_computes(approval_status = approved)
```

## Runtime parameter source

Runtime parameters come from the run command or a params file:

```json
{
  "period_bindings": {
    "本期": "2024Q4",
    "去年同期": "2023Q4",
    "上期": "2024Q3"
  },
  "org_scope": [
    {"branch_num": "27020199", "branch_short_name": "王益联社"}
  ],
  "output_formats": ["md", "docx"]
}
```

The parameters are saved to `run_meta.run_params`.

## SQLBot data destination

SQLBot results are normalized into `run.duckdb.metric_facts`.

Each fact keeps both the semantic alias and the bound runtime value:

```text
period_alias = 本期
period_value = 2024Q4
```

## compute_sql execution

For each table:

```text
metric_facts
→ table_frame wide view
→ approved table_computes.compute_sql
→ computed_facts
```

`compute_sql` must:

- read only `table_frame`
- return `branch_num`
- return one or more columns whose aliases match approved `compute_name` values
- not insert or update tables

## render_payload generation

`render_payload` is assembled from `run.duckdb`:

- `run_meta` for report/run metadata
- `run_sections` for sections and ordering
- `run_tables` for tables, headers, prompts, policies
- `metric_facts` for base metric cells
- `computed_facts` for calculated cells
- runtime description generation for `description_text`

Renderers consume only `render_payload`.
