## ADDED Requirements

### Requirement: Multi-parameter data collection
The agent SHALL invoke `query_trend.py` with multiple `--metric-keys` to collect synchronized time-series data across all selected parameters for a single equipment.

#### Scenario: Multi-parameter trend fetch
- **WHEN** agent calls `query_trend.py --metric-keys vibration_level,temperature,pressure,flow_rate --date-range <start>..<end> --aggregation daily --forecast-horizon 0`
- **THEN** the script returns aligned time-series for all 4 metrics with matching timestamps

#### Scenario: Single equipment constraint
- **WHEN** correlation analysis mode is active and multiple equipment are selected
- **THEN** agent renders a `markdown` prompt to select exactly one equipment for correlation analysis (multi-equipment correlation is out of scope for Phase 1)

### Requirement: Pearson correlation computation
The agent SHALL execute an inline Python script (no new dependencies) to compute the Pearson correlation coefficient matrix across all parameter pairs.

#### Scenario: Correlation matrix computation
- **WHEN** multi-parameter data has N metrics with M synchronized time points
- **THEN** the inline script computes an N×N correlation matrix where `matrix[i][j]` = Pearson r between metric_i and metric_j, with values in [-1, 1]

#### Scenario: Insufficient data points
- **WHEN** the time series has fewer than 10 synchronized data points
- **THEN** agent renders a `markdown` warning "数据点不足（需≥10），无法进行可靠的相关性分析" and stops

#### Scenario: Constant-value metric excluded
- **WHEN** a metric has zero variance (all values identical) during the time window
- **THEN** the inline script excludes that metric from the matrix and adds a `data_notes` entry "metric X excluded: constant value"

### Requirement: Correlation heatmap visualization
The agent SHALL render a `render_ui` ECharts heatmap showing the correlation matrix with color gradient from blue (-1) through white (0) to red (+1).

#### Scenario: Heatmap with annotations
- **WHEN** correlation matrix is computed
- **THEN** agent renders an ECharts heatmap with: N×N colored cells, numeric r values annotated in each cell, row/column labels showing metric display names and units

#### Scenario: Strong correlation highlight
- **WHEN** any |r| ≥ 0.7 (strong correlation)
- **THEN** the corresponding cell-pair is listed in a companion `table` block as "显著相关" with interpretation (positive = "同向变化", negative = "反向变化")

#### Scenario: Weak correlation summary
- **WHEN** all |r| < 0.3 (weak correlation)
- **THEN** agent renders a `markdown` note "所选参数间未发现显著线性相关性，建议扩大时间范围或检查参数选择"

### Requirement: Correlation findings interpretation
The agent SHALL generate a natural-language interpretation of the top 3 strongest correlations (by absolute r value) with domain-relevant commentary.

#### Scenario: Vibration-temperature positive correlation
- **WHEN** vibration_level and temperature show r = 0.85
- **THEN** the interpretation includes "振动与温度强正相关（r=0.85），符合典型的机械摩擦升温模式，建议关注轴承/密封状态"

#### Scenario: Flow-pressure negative correlation
- **WHEN** flow_rate and pressure show r = -0.72
- **THEN** the interpretation includes "流量与压力强负相关（r=-0.72），符合流体力学特性；若此关系近期显著偏离历史基线，可能指示管路堵塞或阀门异常"
