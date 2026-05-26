## ADDED Requirements

### Requirement: Basic trend — linear regression
At Basic tier, the system SHALL compute linear regression slope, direction (rising/falling/stable), volatility (std/|mean|), and naïve linear forecast for each metric.

#### Scenario: Basic trend finds upward slope
- **WHEN** a metric's values increase monotonically over 30 days
- **THEN** findings SHALL include `direction: "up"`, `slope_per_step` > 0, and `forecast` based on last-segment linear extrapolation

### Requirement: Pro trend — multi-model + decomposition + change points
At Pro tier, the system SHALL fit linear, polynomial (degree 2), and exponential models, select best by adjusted R², apply STL seasonal decomposition (when ≥14 data points), and detect structural change points via PELT.

#### Scenario: Polynomial selected over linear
- **WHEN** a metric shows acceleration (concave up) and polynomial R²_adj > linear R²_adj by ≥0.05
- **THEN** `model_type: "polynomial"` SHALL be selected and the ECharts SHALL overlay all 3 fitted curves

#### Scenario: STL decomposes weekly seasonality
- **WHEN** daily data spans ≥30 days
- **THEN** output SHALL include `decomposition: {trend, seasonal, residual}` and the seasonal component period SHALL be 7

#### Scenario: PELT detects regime change
- **WHEN** a metric's mean shifts from 3.2 to 5.8 mid-series
- **THEN** `change_points` SHALL include the shift timestamp and a vertical dashed line SHALL annotate the ECharts

### Requirement: Ultra trend — DL forecast + co-trending + adaptive thresholds
At Ultra tier, the system SHALL load ONNX LSTM model for multi-step forecast with 80%/95% confidence intervals, detect co-trending metric groups, flag divergent metrics, and recommend alarm thresholds from historical 3σ baselines.

#### Scenario: LSTM forecast with confidence bands
- **WHEN** Ultra trend runs with forecast_horizon=30
- **THEN** the ECharts SHALL render a shaded 80% confidence band around the forecast line

#### Scenario: Co-trending group detected
- **WHEN** vibration_level and temperature both trend upward with r>0.7
- **THEN** findings SHALL include `co_trending_group: {metrics: ["vibration_level", "temperature"], label: "同步劣化组", combined_risk_score: X}`

#### Scenario: Metric diverges from co-trending group
- **WHEN** 3 metrics normally trend together but pressure shows opposing direction
- **THEN** findings SHALL flag `divergence_alert: true` for pressure

#### Scenario: Automatic threshold recommendation
- **WHEN** historical data spans ≥60 points and the 99.7th percentile (3σ) is below the current alarm threshold
- **THEN** output SHALL include `threshold_recommendation: {recommended_upper, current_upper, action: "tighten"}`
