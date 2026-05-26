## ADDED Requirements

### Requirement: Multi-step GenUI monitoring workflow
The `monitoring-analysis` agent SHALL implement a callback-driven state machine via `render_ui` forms, progressing through equipment selection → analysis type → time range → execution → report, following the same pattern as `fault-diagnosis--pump`.

#### Scenario: First entry renders equipment selector
- **WHEN** user opens a new monitoring-analysis thread and the current message is not a `ui_interaction`
- **THEN** agent renders a `device-selector-multi` component with `callback_id="monitor-equipment"` and stops, replying "请在左侧组织树中选择设备后提交。"

#### Scenario: Equipment callback renders analysis type form
- **WHEN** agent receives `ui_interaction` with `callback_id="monitor-equipment"` and `payload.selected` is non-empty
- **THEN** agent validates each device ID against `[A-Za-z0-9_-]+`, then renders a `form` with `callback_id="monitor-scope"` offering analysis type choices (trend/anomaly/kpi_dashboard/correlation) and time range fields

#### Scenario: Scope callback triggers execution
- **WHEN** agent receives `ui_interaction` with `callback_id="monitor-scope"` and all fields validate
- **THEN** agent dispatches to the analysis mode-specific data fetch and processing pipeline based on the selected analysis type

#### Scenario: Empty equipment selection is rejected
- **WHEN** agent receives `ui_interaction` with `callback_id="monitor-equipment"` and `payload.selected` is empty
- **THEN** agent renders a `markdown` error "请至少选择一台设备" and stops

#### Scenario: Invalid device ID is rejected
- **WHEN** `payload.selected` contains a device with `id` not matching `^[A-Za-z0-9_-]+$`
- **THEN** agent renders a `markdown` error describing the invalid ID and stops, without calling any scripts

#### Scenario: Invalid analysis type is rejected
- **WHEN** agent receives `ui_interaction` with `callback_id="monitor-scope"` and `payload.analysis_type` is not one of `trend`/`anomaly`/`kpi_dashboard`/`correlation`
- **THEN** agent renders a `markdown` error and stops

#### Scenario: Same thread supports multiple analyses
- **WHEN** a user runs a second monitoring analysis in the same thread
- **THEN** agent backtracks history to find only the most recent matching callback messages, ignoring earlier round parameters

### Requirement: Analysis type dispatch
The agent SHALL dispatch to distinct data pipelines per analysis type, each producing type-specific GenUI blocks (ECharts, tables, cards) and a structured findings summary.

#### Scenario: Trend mode dispatches to query_trend pipeline
- **WHEN** `analysis_type` is `trend`
- **THEN** agent calls `query_trend.py` with selected equipment, metric keys, date range, and aggregation level, then calls `trend_analysis.py`, then renders ECharts line chart with trend + forecast + threshold bands

#### Scenario: Anomaly mode dispatches to anomaly detection pipeline
- **WHEN** `analysis_type` is `anomaly`
- **THEN** agent calls data fetch scripts, runs statistical outlier detection inline, and renders ECharts with anomaly markers, severity-colored data points, and an anomaly summary table

#### Scenario: KPI dashboard mode renders multi-KPI view
- **WHEN** `analysis_type` is `kpi_dashboard`
- **THEN** agent calls `query_daily.py --aggregate` with all selected KPIs for the latest date, then renders ECharts radar chart and gauge cards with target-rate indicators

#### Scenario: Correlation mode computes and visualizes correlation matrix
- **WHEN** `analysis_type` is `correlation`
- **THEN** agent fetches multi-parameter data via `query_trend.py` with multiple `--metric-keys`, computes Pearson correlation matrix inline, and renders ECharts heatmap
