# ai-report DuckDB V2: Schema

## definitions.duckdb

Long-lived report design store.

### reports

```sql
reports(
  report_id TEXT PRIMARY KEY,
  report_name TEXT,
  report_title TEXT,
  status TEXT,
  version INTEGER,
  last_preview_run_id TEXT,
  activated_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  metadata JSON
)
```

### report_sections

```sql
report_sections(
  section_id TEXT PRIMARY KEY,
  report_id TEXT,
  section_key TEXT,
  section_title TEXT,
  section_order INTEGER,
  description_prompt TEXT,
  enabled BOOLEAN,
  metadata JSON,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### report_tables

```sql
report_tables(
  table_id TEXT PRIMARY KEY,
  report_id TEXT,
  section_id TEXT,
  table_title TEXT,
  table_order INTEGER,
  source_md_path TEXT,
  source_md_hash TEXT,
  parsed_payload JSON,
  headers JSON,
  orgs JSON,
  time_info JSON,
  description_prompt TEXT,
  approval_status TEXT,
  query_failure_policy TEXT,
  compute_failure_policy TEXT,
  description_failure_policy TEXT,
  last_design_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### table_metrics

```sql
table_metrics(
  table_id TEXT,
  idx_id TEXT,
  period_alias TEXT,
  data_unit TEXT,
  header_text TEXT,
  metric_order INTEGER,
  approval_status TEXT,
  last_design_run_id TEXT,
  metadata JSON,
  PRIMARY KEY(table_id, idx_id, period_alias)
)
```

### table_computes

```sql
table_computes(
  compute_id TEXT PRIMARY KEY,
  table_id TEXT,
  compute_name TEXT,
  formula_text TEXT,
  compute_sql TEXT,
  dependencies JSON,
  examples JSON,
  approval_status TEXT,
  last_design_run_id TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### design_artifacts

```sql
design_artifacts(
  artifact_id TEXT PRIMARY KEY,
  report_id TEXT,
  table_id TEXT,
  design_run_id TEXT,
  output_id TEXT,
  artifact_type TEXT,
  file_path TEXT,
  status TEXT,
  created_at TIMESTAMP
)
```

## run.duckdb

Per-run snapshot and result store.

### run_meta

```sql
run_meta(
  run_id TEXT PRIMARY KEY,
  run_mode TEXT,
  report_id TEXT,
  report_title TEXT,
  table_id TEXT,
  report_version INTEGER,
  run_params JSON,
  checkpoint_policy TEXT,
  status TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
)
```

### run_sections

```sql
run_sections(
  run_id TEXT,
  section_id TEXT,
  report_id TEXT,
  section_key TEXT,
  section_title TEXT,
  section_order INTEGER,
  description_prompt TEXT,
  enabled BOOLEAN,
  metadata JSON,
  PRIMARY KEY(run_id, section_id)
)
```

### run_tables

```sql
run_tables(
  run_id TEXT,
  table_id TEXT,
  report_id TEXT,
  section_id TEXT,
  table_title TEXT,
  table_order INTEGER,
  parsed_payload JSON,
  headers JSON,
  orgs JSON,
  time_info JSON,
  description_prompt TEXT,
  query_failure_policy TEXT,
  compute_failure_policy TEXT,
  description_failure_policy TEXT,
  source TEXT,
  PRIMARY KEY(run_id, table_id)
)
```

### metric_facts

```sql
metric_facts(
  run_id TEXT,
  table_id TEXT,
  branch_num TEXT,
  branch_short_name TEXT,
  idx_id TEXT,
  period_alias TEXT,
  period_value TEXT,
  raw_value TEXT,
  numeric_value DECIMAL(38,10),
  data_unit TEXT,
  status TEXT,
  error_message TEXT,
  PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
)
```

### computed_facts

```sql
computed_facts(
  run_id TEXT,
  table_id TEXT,
  branch_num TEXT,
  compute_name TEXT,
  value TEXT,
  numeric_value DECIMAL(38,10),
  status TEXT,
  error_message TEXT,
  PRIMARY KEY(run_id, table_id, branch_num, compute_name)
)
```

### run_events

```sql
run_events(
  event_id TEXT PRIMARY KEY,
  run_id TEXT,
  step TEXT,
  event_type TEXT,
  status TEXT,
  message TEXT,
  payload JSON,
  created_at TIMESTAMP
)
```

### run_outputs

```sql
run_outputs(
  output_id TEXT PRIMARY KEY,
  run_id TEXT,
  table_id TEXT,
  output_type TEXT,
  file_path TEXT,
  content TEXT,
  status TEXT,
  payload JSON,
  created_at TIMESTAMP
)
```
