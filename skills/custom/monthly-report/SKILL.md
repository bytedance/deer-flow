---
name: monthly-report
description: Monthly equipment operation report generation scripts. Provides query_monthly, monthly_kpi, list_equipment, and export_report for the ai-report--monthly agent.
---

# Monthly Report Skill Scripts

This skill provides executable scripts for monthly equipment operation report generation. The agent uses these scripts via the `bash` tool to query monthly KPI data, compute summaries, and export Markdown reports.

## When to Use This Skill

Use these scripts when:

- The user requests a monthly equipment operation report
- The ai-report--monthly agent needs to fetch monthly KPI data
- A DSL template references `monthly-report/` namespace scripts

## Preconditions

- The `bash` tool must be available (sandbox tool group enabled)
- Environment variables:
  - `MONTHLY_REPORT_OUTPUT_DIR` — Output directory (falls back to `WEEKLY_REPORT_OUTPUT_DIR`, then `DAILY_REPORT_OUTPUT_DIR`, then `/mnt/user-data/outputs`)
  - `DEER_FLOW_DATA_PROVIDER` — Ignored for monthly source (pinned to platform bridge)

## Scripts

### query_monthly.py — Query monthly operation data

```bash
python /mnt/skills/custom/monthly-report/scripts/query_monthly.py \
  --report-month YYYY-MM \
  --equipment "RM-001,RM-002" \
  --kpis "runtime_rate,downtime_count,mtbf,mttr" \
  --compare previous_month,previous_year_month
```

Writes `/mnt/user-data/outputs/monthly_data.json`. Fetches per-day data from the platform bridge, buckets into week buckets (month-anchored, NOT ISO weeks), and aggregates into the monthly shape including maintenance records, critical events, and improvement tracking.

### monthly_kpi.py — Compute monthly KPI summary

```bash
python /mnt/skills/custom/monthly-report/scripts/monthly_kpi.py \
  --input /mnt/user-data/outputs/monthly_data.json \
  --output /mnt/user-data/outputs/monthly_kpi.json
```

Produces `kpi_summary` (with MoM/YoY deltas), `weekly_trend_chart`, `anomaly_top_n`, `critical_events`, `improvement_tracking`, `overall_status`, and `next_month_plan`.

### list_equipment.py — Discover available equipment

```bash
python /mnt/skills/custom/monthly-report/scripts/list_equipment.py \
  --type all|static_equipment|rotating_machinery|pump|reciprocating_machinery \
  --scope all|area|specific \
  --filter "Area-1" \
  --limit 50
```

Output: `{"equipment": [...], "available_kpis": [...], "area_counts": {...}}`

### export_report.py — Export the monthly KPI payload to Markdown

```bash
python /mnt/skills/custom/monthly-report/scripts/export_report.py \
  --input /mnt/user-data/outputs/monthly_kpi.json \
  --output /mnt/user-data/outputs/monthly_report.md
```

Generates a Markdown report with 8 sections: 月度总览, 月 KPI, 周维度趋势, 异常 TopN, 重大事件回顾, 月环比+同比, 改进措施跟踪, 下月计划.

## Output Convention

- All scripts output JSON to stdout
- Errors do not crash (exit 0); error info is in the `error` field of the JSON output
- Authentication is via environment variables, never hardcoded

## Integration with AI Report Agent

The ai-report--monthly agent SOUL.md references these scripts for data fetching and report generation. The skill is self-contained with no cross-skill dependencies.
