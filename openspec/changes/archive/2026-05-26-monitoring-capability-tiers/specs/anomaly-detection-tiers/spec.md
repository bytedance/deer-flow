## ADDED Requirements

### Requirement: Basic anomaly — fixed threshold + IQR
At Basic tier, the system SHALL detect anomalies using static per-KPI thresholds and IQR statistical method (|z| > 2.0, ≥3 consecutive points for cluster).

#### Scenario: Threshold-based anomaly detected
- **WHEN** vibration_level exceeds 7.1 mm/s (hardcoded threshold)
- **THEN** the anomaly SHALL be flagged with `severity: "critical"` and `methods: ["threshold"]`

#### Scenario: IQR statistical outlier detected
- **WHEN** a value falls outside 3×IQR fences
- **THEN** the anomaly SHALL be flagged with `methods: ["statistical"]` and `severity: "warning"`

### Requirement: Pro anomaly — Isolation Forest + DBSCAN + adaptive threshold
At Pro tier, the system SHALL additionally apply Isolation Forest for multi-dimensional outlier detection, DBSCAN to cluster anomalies by proximity, and compute rolling-window adaptive thresholds (default window=30).

#### Scenario: Multi-dimensional anomaly found by Isolation Forest
- **WHEN** vibration and temperature are individually within threshold but their combination is anomalous in IF space
- **THEN** the point SHALL be flagged with `methods: ["isolation_forest"]` and `severity: "warning"`

#### Scenario: DBSCAN groups anomalies into clusters
- **WHEN** 15 anomalies are detected across 3 metrics over a week
- **THEN** output SHALL include `anomaly_clusters[]` with cluster metadata and a cluster summary table in the UI

#### Scenario: Adaptive threshold tracks cyclic pattern
- **WHEN** a metric has a weekly cycle and the rolling window is 30
- **THEN** the adaptive threshold SHALL track the cycle, reducing false positives relative to static threshold

### Requirement: Ultra anomaly — Autoencoder + cross-validation + root cause
At Ultra tier, the system SHALL additionally score anomalies via ONNX Autoencoder reconstruction error, cross-validate across sensors (single-sensor anomaly → elevated artifact risk), and rank root cause candidates by matching anomaly patterns against known fault signatures.

#### Scenario: Autoencoder detects subtle anomaly
- **WHEN** a point is within all static and adaptive thresholds but Autoencoder reconstruction error > 3σ
- **THEN** the point SHALL be flagged with `methods: ["autoencoder"]` and `severity: "warning"`

#### Scenario: Single-sensor anomaly downgraded
- **WHEN** vibration_level spikes at T but temperature, pressure, and flow are all normal at T
- **THEN** `artifact_risk` SHALL be `"high"` and severity SHALL be downgraded one level

#### Scenario: Multi-sensor anomaly confirmed
- **WHEN** vibration AND temperature both show anomalies at the same timestamp
- **THEN** `artifact_risk` SHALL be `"low"` and severity SHALL be elevated to `"critical"`

#### Scenario: Root cause candidate ranked
- **WHEN** an anomaly cluster matches the "gradual vibration + temperature rise" pattern
- **THEN** findings SHALL include `root_cause_candidates: [{fault_type, match_score, evidence}]` sorted by score descending
