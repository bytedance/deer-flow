## ADDED Requirements

### Requirement: Basic comparison — no historical comparison
At Basic tier, the system SHALL analyze only the selected time range without comparing to prior periods.

### Requirement: Pro comparison — period-over-period
At Pro tier, the system SHALL automatically fetch and compare against the previous equivalent period (week-over-week, month-over-month, year-over-year), highlighting significant changes.

#### Scenario: Week-over-week comparison
- **WHEN** user selects a 7-day analysis window and agent has `monitoring:pro`
- **THEN** the system SHALL fetch the previous 7-day window and output `comparison: {period: "wow", current_avg, previous_avg, delta_pct}` for each metric

#### Scenario: Month-over-month comparison
- **WHEN** user selects a 30-day window
- **THEN** the system SHALL compare against the previous 30-day window and flag metrics with delta >20%

### Requirement: Ultra comparison — peer benchmark + industry benchmark
At Ultra tier, the system SHALL additionally compare against peer equipment of the same type AND against industry benchmark values when available.

#### Scenario: Peer group benchmark
- **WHEN** 5 pumps of the same model are analyzed at Ultra tier
- **THEN** the report SHALL include a "同类设备基准对比" section with percentile ranks and highlight outliers

#### Scenario: Industry benchmark reference
- **WHEN** industry benchmark data is available (e.g., ISO 10816 vibration limits for pump class)
- **THEN** the report SHALL include the relevant industry standard as a reference line on ECharts

### Requirement: Comparison section in report
At Pro and Ultra tiers, the report SHALL include a "历史对比" or "基准对比" section with the comparison results.

#### Scenario: Pro report shows WoW change
- **WHEN** Pro-tier week-over-week comparison finds vibration_level +15%
- **THEN** the report SHALL highlight "振动烈度较上周上升 15%，请关注" in the findings
