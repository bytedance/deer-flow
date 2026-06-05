---
name: weekly-report
description: Weekly equipment operation report generation scripts. Provides query_weekly, weekly_kpi, list_equipment, and export_report for the ai-report--weekly agent.
---

# Weekly Report Skill Scripts

This skill provides executable scripts for weekly equipment operation report generation. The agent uses these scripts via the `bash` tool to query weekly KPI data, compute summaries, and export Markdown reports.

## When to Use This Skill

Use these scripts when:

- The user requests a weekly equipment operation report
- The ai-report--weekly agent needs to fetch weekly KPI data
- A DSL template references `weekly-report/` namespace scripts

## Preconditions

- The `bash` tool must be available (sandbox tool group enabled)
- Environment variables:
  - `WEEKLY_REPORT_OUTPUT_DIR` — Output directory (falls back to `DAILY_REPORT_OUTPUT_DIR`, then `/mnt/user-data/outputs`)
  - `DEER_FLOW_DATA_PROVIDER` — Ignored for weekly source (pinned to platform bridge)

## Scripts

### query_weekly.py — Query 7-day aggregated operation data

```bash
python /mnt/skills/custom/weekly-report/scripts/query_weekly.py \
  --week-start YYYY-MM-DD \
  --equipment "RM-001,RM-002" \
  --kpis "runtime_rate,downtime_count,alarm_count" \
  --compare previous_week|previous_year|none
```

Writes `/mnt/user-data/outputs/weekly_data.json`. Fetches per-day data from the platform bridge and aggregates into a 7-day shape.

### query_sms_abnormal.py — Query 7-day SMS abnormal events

```bash
python /mnt/skills/custom/weekly-report/scripts/query_sms_abnormal.py \
  --week-start YYYY-MM-DD \
  --equipment "RM-001,RM-002" \
  --type rotating_machinery
```

Writes `/mnt/user-data/outputs/sms_abnormal.json`. Queries the SMS /api/abnormal/list for the full 7-day week range with equipment-level filtering. Non-rotating equipment types short-circuit to empty results.

### weekly_kpi.py — Compute weekly KPI summary, trend chart and alarms

```bash
python /mnt/skills/custom/weekly-report/scripts/weekly_kpi.py \
  --input /mnt/user-data/outputs/weekly_data.json \
  --output /mnt/user-data/outputs/weekly_kpi.json
```

Produces `kpi_summary`, `daily_trend_chart` (ready-to-render ECharts option), `anomaly_top_n`, `alarm_table`, `sms_abnormal_table`, `overall_status`, and `next_week_focus`. If `sms_abnormal.json` exists in the output directory, SMS anomaly data is automatically incorporated into the KPI summary and overall status.

### list_equipment.py — Discover available equipment

```bash
python /mnt/skills/custom/weekly-report/scripts/list_equipment.py \
  --type all|static_equipment|rotating_machinery|pump|reciprocating_machinery \
  --scope all|area|specific \
  --filter "Area-1" \
  --limit 50
```

Output: `{"equipment": [...], "available_kpis": [...], "area_counts": {...}}`

### export_report.py — Export the weekly KPI payload to Markdown

```bash
python /mnt/skills/custom/weekly-report/scripts/export_report.py \
  --input /mnt/user-data/outputs/weekly_kpi.json \
  --output /mnt/user-data/outputs/weekly_report.md
```

Generates a Markdown report with sections: 本周概览, 周 KPI, 日趋势, 异常 TopN, SMS 异常事件, 告警流水, 下周关注.

## Output Convention

- All scripts output JSON to stdout
- Errors do not crash (exit 0); error info is in the `error` field of the JSON output
- Authentication is via environment variables, never hardcoded

## Integration with AI Report Agent

The ai-report--weekly agent SOUL.md references these scripts for data fetching and report generation. The skill is self-contained with no cross-skill dependencies.
