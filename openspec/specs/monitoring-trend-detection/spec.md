## ADDED Requirements

### Requirement: Trend data fetch via query_trend.py
The agent SHALL invoke `query_trend.py` with `--metric-keys`, `--date-range`, `--aggregation`, and optional `--forecast-horizon` to obtain time-series data for trend analysis.

#### Scenario: Successful trend data fetch
- **WHEN** agent calls `python /mnt/skills/custom/data-analyst/scripts/query_trend.py --metric-keys runtime_rate,vibration_level --date-range 2026-01-01..2026-05-25 --aggregation daily --forecast-horizon 14`
- **THEN** the script writes `trend_data.json` to the run output directory and returns JSON with `time_series[]` and `metadata` fields on stdout

#### Scenario: INS provider error propagates
- **WHEN** `query_trend.py` encounters an `HttpProviderError` from the INS backend
- **THEN** the script outputs `{"error": "HttpProviderError: ..."}` to stdout, agent renders a `markdown` error, and no fake report is generated

### Requirement: Trend analysis decomposition
The agent SHALL invoke `trend_analysis.py` with the `trend_data.json` output to compute trend decomposition, anomaly flags, slope/volatility metrics, and forecast values.

#### Scenario: Trend analysis produces findings
- **WHEN** agent calls `trend_analysis.py` with valid `trend_data.json` input
- **THEN** the script writes `trend_analysis.json` containing `findings[]` (each with `metric_key`, `direction` (rising/falling/stable), `slope`, `volatility`, `forecast_value`, `confidence`) and `evidence[]` (with `source_type`, `snapshot_path`, `time_range`)

#### Scenario: Degradation rate calculation
- **WHEN** any metric's slope exceeds ±2 standard deviations of historical volatility
- **THEN** a finding with `severity: "warning"` is emitted and the ECharts line chart renders a dashed forecast extension with confidence band

#### Scenario: Inflection point detection
- **WHEN** a metric's 7-day moving average crosses its 30-day moving average
- **THEN** a finding with `direction_change: true` is emitted and the inflection point is annotated on the trend chart

### Requirement: Trend visualization via ECharts
The agent SHALL render trend analysis results using `render_ui` with ECharts line chart including: raw data series, moving average overlay, threshold bands, anomaly markers, and forecast extension.

#### Scenario: Trend ECharts block rendered
- **WHEN** trend analysis completes successfully
- **THEN** agent calls `render_ui(component="echart", props={...})` with a multi-series line chart option containing: historical line, MA(7) dashed line, upper/lower threshold bands, forecast dashed extension with confidence interval, and vertical anomaly markers

#### Scenario: Multi-metric trend renders separate panels
- **WHEN** trend analysis covers 3+ metrics
- **THEN** agent renders one ECharts block per metric, each with its own threshold bands and unit labels
