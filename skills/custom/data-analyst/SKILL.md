---
name: data-analyst
description: Data source discovery and fetching scripts for the data-analyst agent. Provides list_datasets, fetch_dataset, and preview_dataset commands that connect to external data platforms via environment variables.
---

# Data Analyst Skill Scripts

This skill provides executable scripts for dynamic data source discovery and fetching. The agent uses these scripts via the `bash` tool when MCP data catalog tools are not available.

## When to Use This Skill

Use these scripts when:

- The user asks for data analysis and you need to discover available data sources
- No MCP `data_catalog.*` tools are available
- The `bash` tool is available in your toolset

## Preconditions

- The `bash` tool must be available (sandbox tool group enabled)
- Environment variables must be configured:
  - `DATA_PLATFORM_URL` — Base URL of the data platform API
  - `DATA_PLATFORM_TOKEN` — Bearer token for authentication (optional)

## Scripts

### list_datasets.py — Discover available data sources

```bash
python /mnt/skills/custom/data-analyst/scripts/list_datasets.py [--source-type TYPE] [--search KEYWORD] [--limit N] [--parent PARENT_ID]
```

Output: `{"datasets": [{"id": "...", "name": "...", "description": "...", ...}], "total": N}`

### fetch_dataset.py — Fetch data from a selected source

```bash
python /mnt/skills/custom/data-analyst/scripts/fetch_dataset.py --dataset-id ID [--format json|csv] [--limit N] [--offset N]
```

Output: `{"columns": [...], "data": [...], "total": N, "dataset_id": "..."}`

### preview_dataset.py — Preview schema and sample rows

```bash
python /mnt/skills/custom/data-analyst/scripts/preview_dataset.py --dataset-id ID [--rows N]
```

Output: `{"dataset_id": "...", "columns": [{"name": "...", "type": "...", ...}], "sample_rows": [...], "total_rows": N}`

### query_daily.py — Query daily report data (ai-report--daily MVP)

```bash
python /mnt/skills/custom/data-analyst/scripts/query_daily.py \
  --date YYYY-MM-DD \
  --equipment "E001,E002" \
  --kpis "runtime_rate,downtime_count,alarm_count" \
  --compare previous_day|previous_week|none
```

Writes `/mnt/user-data/outputs/daily_data.json`. Falls back to deterministic
demo data when no real data API is configured. See design doc §6.1 for the
output contract.

### daily_kpi.py — Compute KPI summary, trend chart and alarms

```bash
python /mnt/skills/custom/data-analyst/scripts/daily_kpi.py \
  --input /mnt/user-data/outputs/daily_data.json \
  --output /mnt/user-data/outputs/daily_kpi.json
```

Produces `kpi_summary`, `trend_chart` (ready-to-render ECharts option),
`alarm_table`, `overall_status`, and `recommendations`. See design doc §6.2.

### export_report.py — Export the daily KPI payload

```bash
python /mnt/skills/custom/data-analyst/scripts/export_report.py \
  --input /mnt/user-data/outputs/daily_kpi.json \
  --format md \
  --output /mnt/user-data/outputs/daily_report.md
```

Currently supports Markdown only; PDF is deferred (Sprint plan Story 6).

### query_diagnosis.py — Query diagnosis trend features (fault-diagnosis MVP)

```bash
python /mnt/skills/custom/data-analyst/scripts/query_diagnosis.py \
  --kind centrifugal_pump \
  --equipment "PUMP-A-001,PUMP-A-002" \
  --start "2026-05-12T00:00:00" \
  --end "2026-05-13T00:00:00" \
  --mode oneoff \
  --compare previous_period
```

Stage 1 (aggregate trend pull) for the `fault-diagnosis--{pump,rotating,reciprocating}`
agents. Internally invokes `ins-extract-trend-features` and falls back to deterministic
demo data when the InS toolchain is unavailable. Writes
`/mnt/user-data/outputs/query_diagnosis.json` per design doc §7.1. Waveform / spectrum /
orbit are not pulled here — the LLM handles those sparsely as Stage 2 against the
`anomaly_time_ms` returned in `points[].trend_summary`.

### diagnosis_features.py — Compute diagnosis features + rule matches

```bash
python /mnt/skills/custom/data-analyst/scripts/diagnosis_features.py \
  --input /mnt/user-data/outputs/query_diagnosis.json \
  --focus "unbalance,cavitation,min_flow_violation" \
  --rules-skill pump-fault-diagnosis \
  --output /mnt/user-data/outputs/diagnosis_features.json
```

Stage 2 of the fault-diagnosis pipeline. Reads `query_diagnosis.json`, optionally
picks up `spectrum_*.json` / `orbit_*.json` deep-sample files written by the LLM
during Stage 2, loads the corresponding rule book SKILL.md / references, runs a
best-effort rule match against `--focus` codes, and writes
`diagnosis_features.json` per design doc §7.2 (containing `evidence_chain` with
`verdict ∈ {exceed, marginal, normal}`, `rule_matches`, ECharts options, demo
historical cases, recommendations). Reciprocating kinds skip orbit charts.

## Output Convention

- All scripts output JSON to stdout
- Errors do not crash (exit 0); error info is in the `error` field of the JSON output
- Authentication is via environment variables, never hardcoded
- Scripts set internal timeouts (30s default) and limit output size

## Integration with Data Analyst Agent

The data-analyst agent SOUL.md references these scripts as Priority 2 in the data fetching chain:

1. MCP Tools (highest priority)
2. **Skill Scripts** (this skill)
3. http_connector (config-driven fallback)
4. Static form (last resort)
