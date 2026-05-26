## Why

The current `monitoring-analysis` agent only implements a basic 3-step form flow (data source selection → fetch → manual analysis) without structured equipment selection, real INS data integration, or production-grade report generation. Compared to the mature `fault-diagnosis--*` agents that follow a disciplined multi-step GenUI workflow with validation, dual-format export, and closure ticket integration, the monitoring-analysis agent is underpowered for operational use. Enhancing it unlocks proactive equipment health monitoring, trend-based early warning, and multi-dimensional KPI analysis — filling the gap between daily reports (snapshot) and fault diagnosis (reactive).

## What Changes

- Replace the generic "data source discovery" flow with **equipment-first monitoring workflow**: device selection via `device-selector-multi` → monitoring scope (single/area/all) → analysis type (trend/anomaly/KPI threshold/correlation) → time range → execution
- Add **structured analysis modes**: trend monitoring (long-term degradation detection), anomaly detection (threshold-based + statistical outlier), KPI health dashboard (multi-KPI radar), and multi-parameter correlation analysis
- Wire **real INS data** through existing `data-analyst` skill scripts (`_ins_provider.py`, `query_trend.py`, `_report_common.py`) — no demo fallback
- Produce **EChart-rich analysis reports** with trend lines, threshold bands, anomaly markers, and correlation heatmaps via `render_ui` echart/table/card components
- Support **dual-format export** (Markdown + PDF) through `export_report.py`, matching the fault-diagnosis pattern
- Integrate **closure ticket creation** for critical anomalies (severity ≥ high or confidence ≥ 0.7)
- Add **proper input validation**: equipment IDs against `[A-Za-z0-9_-]+`, date ranges, analysis type enum checks
- Add **report script registry entries** (`report_scripts.yaml`) for any new monitoring-specific scripts

## Capabilities

### New Capabilities

- `monitoring-analysis-workflow`: Multi-step GenUI-driven monitoring analysis with equipment selection, analysis type choice, time range, and structured execution pipeline — following the callback-driven state machine pattern of fault-diagnosis agents
- `monitoring-trend-detection`: Long-term trend analysis with degradation rate calculation, inflection point detection, and forecast horizon — powered by `query_trend.py` and `trend_analysis.py` scripts
- `monitoring-anomaly-detection`: Threshold-based and statistical outlier detection across vibration, temperature, pressure, and process parameters — with severity grading (watch/warning/critical)
- `monitoring-kpi-dashboard`: Multi-KPI health overview with radar/spider charts, target-rate gauges, and cross-equipment comparison tables
- `monitoring-correlation-analysis`: Multi-parameter Pearson/Spearman correlation with heatmap visualization for identifying linked degradation patterns (e.g., vibration ↔ temperature ↔ flow)
- `monitoring-report-export`: Structured Markdown + PDF export with findings summary, evidence chain, ECharts embeds, and download links — reusing `export_report.py` infrastructure
- `monitoring-closure-integration`: Automatic closure ticket creation when monitoring detects critical anomalies, following the same `closed-loop-agent-integration` contract

### Modified Capabilities

None — this is a net-new enhancement of an existing agent's SOUL.md and config.yaml. No existing spec-level behavior changes.

## Impact

- **Agent files**: `agents/builtin/monitoring-analysis/config.yaml` (add skills, starters, tags), `agents/builtin/monitoring-analysis/SOUL.md` (full rewrite)
- **Skill scripts**: `skills/custom/data-analyst/report_scripts.yaml` (add monitoring-specific script entries if new scripts needed)
- **Data provider**: Reuses existing `_ins_provider.py` infrastructure — no changes required
- **Export**: Reuses `skills/custom/data-analyst/scripts/export_report.py` — may need minor monitoring report type registration
- **Frontend**: No changes required — all UI through existing GenUI components (`device-selector-multi`, `form`, `echart`, `table`, `card`, `markdown`)
- **Dependencies**: None new — all capabilities exist in the current system
