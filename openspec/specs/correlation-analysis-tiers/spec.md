## ADDED Requirements

### Requirement: Basic correlation — Pearson matrix + heatmap
At Basic tier, the system SHALL compute Pearson correlation coefficients for all metric pairs and render a heatmap.

#### Scenario: Pearson heatmap for 4 metrics
- **WHEN** correlation analysis runs on 4 metrics with ≥10 aligned data points each
- **THEN** the system SHALL output a `matrix` (N×N Pearson r values) and render an ECharts heatmap

### Requirement: Pro correlation — Spearman/Kendall + time-lag + partial
At Pro tier, the system SHALL additionally compute Spearman ρ and Kendall τ, detect time-lagged cross-correlation (lags -7 to +7), and compute partial correlation controlling for all other metrics.

#### Scenario: Non-linear relationship captured by Spearman
- **WHEN** two metrics have a monotonic but non-linear relationship
- **THEN** Spearman ρ SHALL be higher than Pearson r and findings SHALL note "检测到非线性单调关系"

#### Scenario: Lagged coupling detected
- **WHEN** temperature rises 2 days after vibration increases (max correlation at lag +2)
- **THEN** findings SHALL include `"temperature 滞后 vibration 约 2 天"` with `has_lag: true, best_lag: 2`

#### Scenario: Spurious correlation identified
- **WHEN** Pearson shows r=0.75 for vibration↔flow but partial correlation (controlling for pressure) drops to r=0.15
- **THEN** this pair SHALL be flagged as "可能为间接相关"

### Requirement: Ultra correlation — Granger causality + transfer entropy + causal graph
At Ultra tier, the system SHALL additionally test Granger causality (lags 1-7), compute transfer entropy for directed information flow, and apply graphical lasso for sparse causal graph discovery.

#### Scenario: Unidirectional Granger causality found
- **WHEN** vibration Granger-causes temperature (p<0.01 at lag 2) but not vice versa
- **THEN** `causal_edges` SHALL include `{from: "vibration", to: "temperature", direction: "unidirectional"}`

#### Scenario: Transfer entropy confirms Granger result
- **WHEN** Granger is significant AND TE(A→B) > 2× TE(B→A)
- **THEN** the edge SHALL be marked `confirmed_by_te: true`

#### Scenario: Force-directed causal graph rendered
- **WHEN** ≥2 causal edges are discovered
- **THEN** the system SHALL render an ECharts force-directed graph with metric nodes and directed causal edges
