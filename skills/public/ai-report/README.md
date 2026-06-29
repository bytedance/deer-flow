# ai-report

`ai-report` is the DuckDB V2 report generation skill.

## DuckDB V2 design

The architecture design is documented under `docx/ai-report/`.

The first implementation slices live under `scripts/ai_report/`:

- `definition_store.py` for `definitions.duckdb`
- `run_store.py` for `run.duckdb`
- `runtime_plan.py` for active definition loading and runtime parameter binding
- `runtime_compute.py` for approved `compute_sql`
- `render_payload.py` for the data/render boundary
- `render_markdown_v2.py` for the first Markdown vertical slice

## DuckDB file locations

DuckDB files are **not** stored inside the skill directory. The sandbox marks `/mnt/skills` read-only, so the skill cannot write there. Instead, files live under the sandbox virtual path `/mnt/ai-report-data/`:

| Virtual path (sandbox) | Host path | Purpose |
|---|---|---|
| `/mnt/ai-report-data/definitions.duckdb` | `$DEER_FLOW_HOME/ai-report/duckdb/definitions.duckdb` | Long-lived design library, shared across runs and threads |
| `/mnt/ai-report-data/runs/<run_id>.duckdb` | `$DEER_FLOW_HOME/ai-report/duckdb/runs/<run_id>.duckdb` | Per-run runtime library, isolated by `run_id` |

### One-time setup (user action)

Add this to `config.yaml` before the first runtime invocation (see `config.example.yaml:806-821` for the `sandbox.mounts` schema):

```yaml
sandbox:
  mounts:
    - host_path: ${DEER_FLOW_HOME}/ai-report/duckdb
      container_path: /mnt/ai-report-data
      read_only: false
```

Then restart DeerFlow: `make stop && make dev`. The skill does not modify `config.yaml` itself.
