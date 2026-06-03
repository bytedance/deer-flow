---
name: data-analyst
description: Data analysis, diagnosis, failure, closure, and inspection scripts. Daily/weekly/monthly report scripts have been migrated to daily-report, weekly-report, and monthly-report skills. Monitoring analysis scripts have been migrated to monitoring-analysis skill.
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

> **注意**：脚本已迁移到 sandbox（`/mnt/skills/custom/features-tool/tools/diagnosis_features.py`），
> 旧路径 `/mnt/skills/custom/data-analyst/scripts/diagnosis_features.py` 不再有效。

```bash
python /mnt/skills/custom/features-tool/tools/diagnosis_features.py \
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

### export_report.py + export_diagnosis_report.py — Export diagnosis/trend reports

Diagnosis and trend exports go through the existing `export_report.py`:

```python
# In-process import inside SOUL.md (preferred):
from export_report import write_report
write_report(payload, "md", report_type="diagnosis")
try:
    write_report(payload, "pdf", report_type="diagnosis")
except ImportError:
    pdf_available = False  # weasyprint not installed in current sandbox
```

CLI is supported for local testing:

```bash
python /mnt/skills/custom/data-analyst/scripts/export_report.py \
  --input /mnt/user-data/outputs/diagnosis_features.json \
  --report-type diagnosis \
  --format md
```

The diagnosis Markdown follows the 6-section template aligned with
`vibration-fault-diagnosis/SKILL.md` (设备与任务 / 异常发现 / 证据链 /
诊断结论 / 差异诊断 / 处置建议) plus optional 同类故障历史 + 执行告警
sections. PDF is wired through the same `_write_pdf` path used by daily /
weekly / monthly — install `weasyprint` in the sandbox to enable it.

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
