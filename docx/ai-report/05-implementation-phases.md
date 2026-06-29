# ai-report DuckDB V2: Implementation Phases

## Phase 1: Documentation split and schema foundation

Deliverables:

- focused design documents
- `ai_report.models`
- `definition_store`
- `export-design-md`

## Phase 2: Design import vertical slice

Deliverables:

- import a parsed table design JSON into `definitions.duckdb`
- approve table/computes/metrics
- export a complete `report_design.md`

## Phase 3: Runtime snapshot and SQLBot metric facts

Deliverables:

- load active report definitions
- build SQLBot metric request plan
- use the SQLBot transport module via `sqlbot_transport.py`
- query SQLBot through `sqlbot_client.py` adapter
- normalize SQLBot responses into `MetricFact`
- create `run.duckdb`
- snapshot sections and tables
- write queried metric rows to `metric_facts`

## Phase 4: Runtime compute

Deliverables:

- build `table_frame`
- execute approved `compute_sql`
- write `computed_facts`

## Phase 5: render_payload and Markdown render

Deliverables:

- assemble `render_payload` from `run.duckdb`
- render report Markdown from `render_payload`

## Phase 6: Integration CLI and compatibility bridge

Deliverables:

- `run-report-fixture` CLI for local verification
- bridge current parsed/wide structures only where necessary
