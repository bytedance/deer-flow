## ADDED Requirements

### Requirement: Basic data access — trend data only
At Basic tier, the system SHALL fetch only trend KPI data via `query_trend.py` (which calls `getTrendDataHis`).

#### Scenario: Basic tier fetches trend data
- **WHEN** Agent has only `monitoring:basic` and user requests trend analysis
- **THEN** the system SHALL invoke `query_trend.py` with the selected metric keys and date range

### Requirement: Pro data access — trend + alerts + events
At Pro tier, the system SHALL fetch trend data AND alarm events AND machine drop/start events, merging them into a unified timeline.

#### Scenario: Pro tier fetches multi-source data
- **WHEN** Agent has `monitoring:pro` and user requests anomaly detection
- **THEN** the system SHALL call `query_trend.py` for KPI data AND query alarm/event APIs, merging results into the analysis input

### Requirement: Ultra data access — full data fusion
At Ultra tier, the system SHALL fetch all available data types: trend KPIs, waveform/spectrum samples, orbit data, alarm events, machine events, and external data connectors.

#### Scenario: Ultra tier fetches waveform alongside trend
- **WHEN** Agent has `monitoring:ultra` and user requests spectrum analysis
- **THEN** the system SHALL fetch trend data for context AND raw waveform data for spectral analysis, presenting a unified multi-source view

### Requirement: Data source provenance in report
At Pro and Ultra tiers, the report payload SHALL include a `data_sources` section listing each data source, its endpoint, record count, and freshness.

#### Scenario: Pro report includes data source table
- **WHEN** Pro-tier analysis completes
- **THEN** `monitoring_features.json` SHALL contain `data_sources: [{source_name, record_count, date_range, freshness}]`
