## 1. Agent Config & Registration

- [x] 1.1 Update `agents/builtin/monitoring-analysis/config.yaml` — add `skills: [data-analyst]`, `starters` (3-4 quick-start prompts), enriched `tags`, and `parent: null` (standalone, not a group child)
- [x] 1.2 Verify agent discovery: `monitoring-analysis` appears in `GET /api/agents` listing with correct display_name, icon, tags, and starters

## 2. Monitoring Workflow SOUL.md (Core State Machine)

- [x] 2.1 Rewrite `agents/builtin/monitoring-analysis/SOUL.md` "首次进入" section — render `device-selector-multi` with `callback_id="monitor-equipment"`, stop and wait for user submission
- [x] 2.2 Implement "设备选择回调" section (`callback_id="monitor-equipment"`) — validate `payload.selected` (non-empty, IDs match `[A-Za-z0-9_-]+`), render analysis scope form with `callback_id="monitor-scope"` offering `analysis_type` (trend/anomaly/kpi_dashboard/correlation), date range, and KPI/metric selection fields
- [x] 2.3 Implement "分析范围回调" section (`callback_id="monitor-scope"`) — validate all fields, dispatch to analysis-type-specific pipeline, backtrack history for equipment selection from `monitor-equipment` callback

## 3. Trend Detection Pipeline

- [x] 3.1 Implement trend data fetch: invoke `query_trend.py` with `--metric-keys`, `--date-range`, `--aggregation`, `--forecast-horizon` extracted from scope form
- [x] 3.2 Implement trend analysis: invoke `trend_analysis.py` with trend data output, read `trend_analysis.json` for findings/evidence/forecast
- [x] 3.3 Implement trend visualization: render ECharts line chart with raw data, MA(7) overlay, threshold bands, anomaly markers, and forecast extension via `render_ui(component="echart")`
- [x] 3.4 Implement trend findings summary: render `card` for overall trend status and `markdown` for findings interpretation

## 4. Anomaly Detection Pipeline

- [x] 4.1 Implement anomaly data fetch: invoke `query_daily.py` or `query_trend.py` with appropriate parameters for the selected time window
- [x] 4.2 Implement inline anomaly detection logic: threshold comparison against KPI alarm limits + IQR statistical outlier detection, severity grading (info/warning/critical)
- [x] 4.3 Implement sensor/environment artifact differentiation: cross-validate anomalies across multiple parameters on the same equipment
- [x] 4.4 Implement anomaly visualization: ECharts scatter/line chart with severity-colored anomaly markers + threshold bands
- [x] 4.5 Implement anomaly summary table: `render_ui(component="table")` with columns timestamp/equipment/metric/value/threshold/deviation/severity/method/verdict

## 5. KPI Dashboard Pipeline

- [x] 5.1 Implement KPI data fetch: invoke `query_daily.py --aggregate` with all selected KPIs for latest date
- [x] 5.2 Implement radar chart: `render_ui(component="echart")` with radar/spider chart for 1-5 equipment, fallback to color-coded table for 6+ equipment
- [x] 5.3 Implement gauge cards: `render_ui(component="card")` for top 4 KPIs with green/yellow/red color coding and fleet average
- [x] 5.4 Implement target compliance summary: compute and display overall compliance percentage

## 6. Correlation Analysis Pipeline

- [x] 6.1 Implement multi-parameter data fetch: invoke `query_trend.py` with multiple `--metric-keys` for a single equipment
- [x] 6.2 Implement inline Pearson correlation computation: N×N matrix from synchronized time-series (≥10 data points required)
- [x] 6.3 Implement correlation heatmap: `render_ui(component="echart")` with color gradient, numeric annotations, and metric labels
- [x] 6.4 Implement correlation interpretation: natural-language commentary for top 3 strongest correlations (|r| ≥ 0.7) with domain context

## 7. Report Export

- [x] 7.1 Register `"monitoring"` report type in `skills/custom/data-analyst/scripts/export_report.py` alongside existing "daily"/"weekly"/"monthly"/"diagnosis" types
- [x] 7.2 Implement report payload assembly: write `monitoring_features.json` with equipment_summary, findings, evidence (per §13.2), echart_options, data_quality, recommendations
- [x] 7.3 Implement dual-format export via inline Python: `write_report(payload, "md", report_type="monitoring")` + `write_report(payload, "pdf", report_type="monitoring")` with weasyprint degradation
- [x] 7.4 Implement structured report rendering: GenUI blocks in fixed order (scope card → charts/tables → findings markdown → data quality → recommendations → download links)
- [x] 7.5 Implement `present_files` for final artifacts only (`monitoring_report.md` + `monitoring_report.pdf`), never intermediate JSON files

## 8. Closure Ticket Integration

- [x] 8.1 Implement auto-creation logic: `create_closure_ticket` when severity is "critical" OR (severity "high" AND confidence ≥ 0.7)
- [x] 8.2 Implement monitoring metadata schema: `source_type="monitoring"` with findings/confidence/evidence_uri/analysis_type/monitoring_run_id
- [x] 8.3 Implement duplicate detection handling: when `created=false`, report "已复用既有闭环单 ct_xxxxx"
- [x] 8.4 Implement closure tracking section: append "## 闭环跟踪" with ticket IDs, priorities, and SLA deadlines to report markdown
- [x] 8.5 Implement non-threshold note: when no closure ticket is created, include "未达自动建单阈值，可在工作台手动登记"

## 9. Input Validation & Error Handling

- [x] 9.1 Validate `payload.selected[].id` against `^[A-Za-z0-9_-]+$` at equipment callback boundary
- [x] 9.2 Validate `analysis_type` enum membership at scope callback boundary
- [x] 9.3 Validate date range format `^\d{4}-\d{2}-\d{2}$` for start/end dates
- [x] 9.4 Validate metric/KPI keys against known set from `_report_common.py`
- [x] 9.5 Implement INS error propagation: all `HttpProviderError` surfaced as `markdown` errors, no silent demo fallback
- [x] 9.6 Implement missing output file detection: check each script output file exists before proceeding to next step
- [x] 9.7 Implement minimum data sufficiency checks: ≥10 points for correlation, ≥24h for daily aggregation trend

## 10. Testing

- [x] 10.1 Write unit tests for `monitoring-analysis` SOUL.md prompt structure (test that all callback sections are present and well-formed)
- [x] 10.2 Write integration test for equipment selection → scope form workflow (mock `render_ui` and `ui_interaction`)
- [x] 10.3 Write integration test for trend detection pipeline end-to-end (with demo data)
- [x] 10.4 Write integration test for anomaly detection pipeline end-to-end (with demo data)
- [x] 10.5 Write integration test for KPI dashboard pipeline end-to-end (with demo data)
- [x] 10.6 Write integration test for correlation analysis pipeline end-to-end (with demo data)
- [x] 10.7 Write integration test for closure ticket auto-creation at severity thresholds
- [x] 10.8 Write integration test for error propagation (INS failure, missing files, invalid inputs)
- [x] 10.9 Verify existing tests (`test_lead_agent_prompt.py`, `test_ai_report_*.py`) still pass with updated agent config
