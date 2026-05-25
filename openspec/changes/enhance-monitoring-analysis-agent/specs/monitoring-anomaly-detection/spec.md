## ADDED Requirements

### Requirement: Anomaly detection via threshold and statistical methods
The agent SHALL fetch equipment monitoring data and apply both threshold-based comparison (against configured alarm limits) and statistical outlier detection (IQR or Z-score method) to identify anomalous data points.

#### Scenario: Threshold-based anomaly detected
- **WHEN** any fetched data point exceeds its configured upper alarm threshold (from `_report_common.py` KPI definitions)
- **THEN** the data point is flagged with `severity: "critical"` and rendered as a red marker on the ECharts visualization

#### Scenario: Statistical outlier detected
- **WHEN** a data point falls outside 3×IQR (inter-quartile range) from the median of the time window
- **THEN** the data point is flagged with `severity: "warning"` and rendered as an orange marker

#### Scenario: Both methods agree amplifies severity
- **WHEN** a data point is flagged by both threshold and statistical methods
- **THEN** the severity escalates (warning→critical, critical remains critical) and the finding includes `detection_methods: ["threshold", "statistical"]`

#### Scenario: No anomalies found
- **WHEN** all data points are within thresholds and no statistical outliers detected
- **THEN** agent renders a `card` with status "正常" (green) and summary "监测期间未发现异常数据点"

### Requirement: Anomaly severity grading
The agent SHALL grade each detected anomaly on a three-tier scale following the existing system convention.

#### Scenario: Watch grade (info/blue)
- **WHEN** a data point exceeds the 2×IQR boundary but not the 3×IQR boundary, and is within alarm thresholds
- **THEN** the anomaly is graded `severity: "info"` with label "注意"

#### Scenario: Warning grade (yellow/orange)
- **WHEN** a data point exceeds 3×IQR or crosses the warning threshold (80% of alarm limit) but not the alarm limit
- **THEN** the anomaly is graded `severity: "warning"` with label "警告"

#### Scenario: Critical grade (red)
- **WHEN** a data point exceeds the configured alarm threshold
- **THEN** the anomaly is graded `severity: "critical"` with label "危险"

### Requirement: Anomaly summary table
The agent SHALL render a `table` GenUI block listing all detected anomalies with columns: timestamp, equipment, metric, measured value, threshold, deviation (%), severity, and detection method.

#### Scenario: Anomaly table with multiple entries
- **WHEN** 5 anomalies are detected across 3 metrics
- **THEN** agent renders a `table` with 5 rows sorted by severity (critical first) then by deviation descending

#### Scenario: Anomaly table includes contextual info
- **WHEN** anomaly detection completes
- **THEN** each table row includes a `verdict` column indicating whether the anomaly is "持续恶化" (≥3 consecutive anomalous points), "突跳" (single isolated point), or "波动异常" (oscillating pattern)

### Requirement: Differentiation from sensor/environment artifacts
The agent SHALL include logic to distinguish equipment anomalies from sensor faults and environmental interference.

#### Scenario: Multi-parameter cross-validation
- **WHEN** a vibration spike is detected on one sensor but temperature and pressure on the same equipment show no change
- **THEN** the finding includes `artifact_risk: "possible_sensor_fault"` with confidence assessment

#### Scenario: Correlated multi-parameter anomaly
- **WHEN** vibration, temperature, and pressure all show anomalous values simultaneously on the same equipment
- **THEN** the finding includes `artifact_risk: "low"` (confirmed equipment anomaly) with higher confidence
