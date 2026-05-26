## ADDED Requirements

### Requirement: Multi-KPI health data fetch
The agent SHALL invoke `query_daily.py --aggregate` with all selected KPI keys to obtain a single-day snapshot of equipment health across multiple parameters.

#### Scenario: Aggregate KPI fetch for dashboard
- **WHEN** agent calls `query_daily.py --date <today> --equipment <ids> --kpis runtime_rate,alarm_count,vibration_level,temperature,pressure,corrosion_rate --aggregate --compare none`
- **THEN** the script returns aggregated KPI values with `current_value`, `unit`, and `target_range` per KPI per equipment

#### Scenario: KPI fetch failure surfaces error
- **WHEN** the INS provider returns an error for the KPI data fetch
- **THEN** agent renders a `markdown` error and does not produce a dashboard

### Requirement: Radar chart visualization
The agent SHALL render a `render_ui` ECharts radar/spider chart showing each equipment's normalized KPI profile against target ranges.

#### Scenario: Single equipment radar chart
- **WHEN** one equipment is selected for KPI dashboard mode
- **THEN** agent renders an ECharts radar chart with axes for each selected KPI, showing the equipment's current values normalized to [0,1] against target range

#### Scenario: Multi-equipment overlay radar
- **WHEN** 2-5 equipment are selected for KPI dashboard mode
- **THEN** agent renders an ECharts radar chart with each equipment as a separate colored polygon, enabling visual cross-equipment comparison

#### Scenario: More than 5 equipment falls back to table
- **WHEN** 6+ equipment are selected for KPI dashboard mode
- **THEN** agent renders a `table` with equipment×KPI matrix using color-coded cells (green/yellow/red based on target compliance) instead of an unreadable radar chart

### Requirement: Gauge cards for key metrics
The agent SHALL render `card` GenUI blocks for the top 4 KPIs showing gauge-style values with color coding.

#### Scenario: Gauge card color coding
- **WHEN** KPI dashboard mode renders gauge cards
- **THEN** each card displays: KPI name, current value with unit, target range indicator, and color (green=within target, yellow=approaching limit, red=out of target)

#### Scenario: Equipment average across selection
- **WHEN** multiple equipment are selected
- **THEN** the gauge cards show fleet-average values with a subtitle indicating "N台设备均值" and worst-case device name in small text

### Requirement: Target compliance summary
The agent SHALL compute and display overall target compliance as a percentage of KPI×equipment pairs that are within their target ranges.

#### Scenario: Full compliance
- **WHEN** all KPI×equipment pairs are within target ranges
- **THEN** a `card` with title "目标达标率" shows "100%" in green

#### Scenario: Partial compliance
- **WHEN** 12 of 20 KPI×equipment pairs are within target
- **THEN** a `card` with title "目标达标率" shows "60%" in yellow, with subtitle listing the non-compliant pairs
