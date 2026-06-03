---
name: daily-report
description: Daily equipment operation report generation scripts. Provides query_daily, daily_kpi, list_equipment, and export_report for the ai-report--daily agent.
---

# Daily Report Skill Scripts

This skill provides executable scripts for daily equipment operation report generation. The agent uses these scripts via the `bash` tool to query daily KPI data, compute summaries, and export Markdown reports.

## When to Use This Skill

Use these scripts when:

- The user requests a daily equipment operation report
- The ai-report--daily agent needs to fetch daily KPI data
- A DSL template references `daily-report/` namespace scripts

## Preconditions

- The `bash` tool must be available (sandbox tool group enabled)
- Environment variables:
  - `DAILY_REPORT_OUTPUT_DIR` — Output directory (default `/mnt/user-data/outputs`)
  - `DEER_FLOW_DATA_PROVIDER` — Ignored for daily source (pinned to platform bridge)

## Scripts

### query_daily.py — Query daily report data

```bash
python /mnt/skills/custom/daily-report/scripts/query_daily.py \
  --date YYYY-MM-DD \
  --equipment "E001,E002" \
  --kpis "runtime_rate,downtime_count,alarm_count" \
  --compare previous_day|previous_week|none
```

Writes `/mnt/user-data/outputs/daily_data.json`. Fetches data from the platform bridge.

### daily_kpi.py — Compute KPI summary, trend chart and alarms

```bash
python /mnt/skills/custom/daily-report/scripts/daily_kpi.py \
  --input /mnt/user-data/outputs/daily_data.json \
  --output /mnt/user-data/outputs/daily_kpi.json
```

Produces `kpi_summary`, `trend_chart` (ready-to-render ECharts option), `alarm_table`, `overall_status`, and `recommendations`.

### list_equipment.py — Discover available equipment

```bash
python /mnt/skills/custom/daily-report/scripts/list_equipment.py \
  --type all|static_equipment|rotating_machinery|pump|reciprocating_machinery \
  --scope all|area|specific \
  --filter "Area-1" \
  --limit 50
```

Output: `{"equipment": [...], "available_kpis": [...], "area_counts": {...}}`

### export_report.py — Export the daily KPI payload to Markdown

```bash
python /mnt/skills/custom/daily-report/scripts/export_report.py \
  --input /mnt/user-data/outputs/daily_kpi.json \
  --output /mnt/user-data/outputs/daily_report.md
```

Generates a Markdown report with sections: 概览, KPI 指标, 运行趋势, 异常设备排行, 异常事件, 建议.

## Output Convention

- All scripts output JSON to stdout
- Errors do not crash (exit 0); error info is in the `error` field of the JSON output
- Authentication is via environment variables, never hardcoded

## Integration with AI Report Agent

The ai-report--daily agent SOUL.md references these scripts for data fetching and report generation. The skill is self-contained with no cross-skill dependencies.
