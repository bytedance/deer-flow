## ADDED Requirements

### Requirement: Basic health — compliance rate + radar
At Basic tier, the system SHALL compute per-KPI compliance (value within target range) for each equipment, render a radar chart when ≤5 devices, and display a compliance rate percentage.

#### Scenario: All KPIs compliant
- **WHEN** all KPIs for all equipment are within target ranges
- **THEN** the compliance card SHALL show 100% and color green

#### Scenario: Mixed compliance with radar chart
- **WHEN** 3 devices have partial KPI compliance and device count ≤5
- **THEN** the system SHALL render a radar chart and a compliance card with the overall percentage

### Requirement: Pro health — trending + peer comparison + weighted scoring
At Pro tier, the system SHALL additionally compute health score trends over the analysis period, compare each equipment's KPIs against peers of the same type (percentile ranks), and support weighted composite scoring.

#### Scenario: Health score trends downward
- **WHEN** equipment health score drops from 95 to 78 over 30 days
- **THEN** findings SHALL include `health_score_trend: [{date, score, delta}]` and a line chart titled "健康评分趋势"

#### Scenario: Peer comparison highlights underperformer
- **WHEN** Equipment A's vibration is at the 95th percentile among 5 pumps of the same type
- **THEN** the KPI table SHALL show a `peer_percentile` column with a warning indicator for vibration

#### Scenario: Custom KPI weights applied
- **WHEN** user provides `metric_weights: {vibration: 0.4, temperature: 0.3, pressure: 0.3}`
- **THEN** the composite score SHALL be the weighted average of normalized compliance values

### Requirement: Ultra health — predictive scoring + risk ranking + risk matrix
At Ultra tier, the system SHALL additionally predict 30-day health scores via ONNX model, rank all selected equipment by composite risk (trajectory × criticality × non-compliance count), and render a likelihood × consequence risk matrix.

#### Scenario: Predicted health enters warning zone
- **WHEN** current score is 88 and ONNX predicts 72 in 30 days
- **THEN** report SHALL flag "预计 30 天内健康评分将进入警戒区" with a gauge card

#### Scenario: Equipment ranked by risk
- **WHEN** 5 equipment are analyzed
- **THEN** output SHALL include `risk_ranking: [{equipment_id, risk_score, risk_factors, rank}]` sorted descending

#### Scenario: Risk matrix bubble chart
- **WHEN** ≥3 equipment have risk scores
- **THEN** the system SHALL render an ECharts scatter with "劣化可能性" × "影响程度" axes, bubbles sized by non-compliant KPI count, colored by risk zone
