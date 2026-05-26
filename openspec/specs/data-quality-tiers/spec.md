## ADDED Requirements

### Requirement: Basic data quality — no checks
At Basic tier, the system SHALL pass data through without quality assessment.

### Requirement: Pro data quality — completeness check + outlier flagging
At Pro tier, the system SHALL detect missing timestamps in time series, flag values that are ±5σ from the series mean as suspicious, and report data completeness percentage.

#### Scenario: Missing data detected at Pro tier
- **WHEN** a 30-day daily series has 3 missing days
- **THEN** the report SHALL include `data_quality: {completeness_pct: 90.0, missing_periods: [{start, end, duration_days}], suspicious_points: [...]}`

#### Scenario: Complete data at Pro tier
- **WHEN** a time series has 100% completeness and no outliers >5σ
- **THEN** `data_quality.completeness_pct` SHALL be 100.0 and `suspicious_points` SHALL be empty

### Requirement: Ultra data quality — full scoring + auto-imputation
At Ultra tier, the system SHALL compute a multi-dimensional quality score (completeness × consistency × timeliness, each 0-1) and SHALL automatically impute small gaps (≤3 consecutive missing points) via linear interpolation.

#### Scenario: Data gap auto-imputed at Ultra tier
- **WHEN** a series has 2 consecutive missing points and Ultra tier is active
- **THEN** the system SHALL fill the gaps via linear interpolation and mark the imputed values with `imputed: true` in the output

#### Scenario: Large gap not imputed
- **WHEN** a series has 7 consecutive missing points
- **THEN** the system SHALL NOT impute the gap and SHALL flag it in `data_quality.gaps_requiring_attention`

### Requirement: Data quality section in report
At Pro and Ultra tiers, the report SHALL include a "数据质量说明" section with the quality assessment results.

#### Scenario: Ultra report includes quality badge
- **WHEN** Ultra-tier quality score is ≥0.9
- **THEN** the report SHALL display "数据质量：优秀 (A)" with a breakdown of the three dimensions
