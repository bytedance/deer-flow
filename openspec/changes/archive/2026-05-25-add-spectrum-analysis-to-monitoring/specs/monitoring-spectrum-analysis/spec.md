## ADDED Requirements

### Requirement: Spectrum analysis type in scope form

The scope callback form SHALL support `spectrum` as a valid `analysis_type` enum value alongside `trend` / `anomaly` / `kpi_dashboard` / `correlation`.

#### Scenario: Scope form includes spectrum option

- **WHEN** the equipment callback renders the analysis scope form (`callback_id="monitor-scope"`)
- **THEN** the `analysis_type` select field SHALL include an option with `value="spectrum"` and label "图谱分析 — 波形频谱特征提取与可视化"

#### Scenario: Scope callback validates spectrum type

- **WHEN** `ui_interaction` with `callback_id="monitor-scope"` is received and `payload.analysis_type` is `"spectrum"`
- **THEN** validation SHALL pass and dispatch to the spectrum analysis pipeline

### Requirement: Spectrum analysis pipeline — timestep selection

After scope validation passes for `analysis_type="spectrum"`, the agent SHALL render a second form (`callback_id="monitor-spectrum-timestep"`) that allows the user to select measurement points and target timestamps for spectrum analysis.

#### Scenario: Render timestep selection form

- **WHEN** `analysis_type` is `"spectrum"` and scope validation passes
- **THEN** the agent SHALL first run a lightweight trend query (`query_trend.py --aggregation daily`) to obtain candidate timestamps
- **AND** the agent SHALL render a `form` component with `callback_id="monitor-spectrum-timestep"`
- **AND** the form SHALL contain a `multi-select` field for choosing measurement points (type=83, name不含波形) from the selected equipment
- **AND** the form SHALL contain a `select` field for choosing a target timestamp from the trend data results

#### Scenario: No trend data available

- **WHEN** the trend query for candidate timestamps returns empty data
- **THEN** the agent SHALL render a `markdown` error: "所选设备在指定时间范围内无趋势数据，无法进行图谱分析" and stop

#### Scenario: No shaft vibration points found

- **WHEN** selected equipment has no measurement points with `type=83` or all type=83 points contain "波形" in their name
- **THEN** the agent SHALL render a `markdown` error: "所选设备未找到可用的轴振测点（type=83），图谱分析仅支持 8k 旋转机械" and stop

### Requirement: Spectrum analysis pipeline — waveform and spectrum fetch

When the timestep selection form is submitted (`callback_id="monitor-spectrum-timestep"`), the agent SHALL fetch waveform/spectrum data and extract structured features using existing skills.

#### Scenario: Fetch waveform data via skill

- **WHEN** `ui_interaction` with `callback_id="monitor-spectrum-timestep"` is received
- **THEN** the agent SHALL invoke `bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh <component_id> <time_ms>` for each selected point
- **AND** the agent SHALL write the combined output to `/mnt/user-data/outputs/waveform_data.json`
- **AND** the agent SHALL verify the output file exists and contains no `error` field before proceeding

#### Scenario: Extract spectrum features

- **WHEN** waveform data is successfully fetched
- **THEN** the agent SHALL invoke `bash /mnt/skills/custom/ins-extract-spectral-waveform-features/scripts/run.sh '<payload_json>'` with the waveform payload
- **AND** the agent SHALL write the result to `/mnt/user-data/outputs/spectrum_features.json`
- **AND** the agent SHALL verify the output file exists and contains `spectral_findings`, `waveform_findings`, `suspected_faults`, and `feature_details` fields

#### Scenario: INS error during waveform fetch

- **WHEN** `getWaveDataHis` API returns an error (network/auth/missing data)
- **THEN** the agent SHALL render the error details in a `markdown` block
- **AND** the agent SHALL NOT fall back to demo/fake data

### Requirement: Spectrum visualization — ECharts rendering

The agent SHALL render waveform (time domain) and spectrum (frequency domain) charts using the `echart` GenUI component.

#### Scenario: Render waveform line chart

- **WHEN** waveform data is available in `/mnt/user-data/outputs/waveform_data.json`
- **THEN** the agent SHALL render an `echart` component with `series.type="line"`, X axis from `wave_x` (time in ms), Y axis from `wave_y` (amplitude in μm)
- **AND** the chart title SHALL include the component name and timestamp
- **AND** if wave_y has more than 2000 points, the agent SHALL downsample before rendering

#### Scenario: Render spectrum bar chart

- **WHEN** spectrum data is available in `/mnt/user-data/outputs/waveform_data.json`
- **THEN** the agent SHALL render an `echart` component with `series.type="bar"`, X axis from `spec_x` (frequency in Hz), Y axis from `spec_y` (amplitude)
- **AND** the chart SHALL include markLine annotations at 1X and 2X frequency positions when speed data is available
- **AND** the chart title SHALL include the component name

#### Scenario: Render feature details table

- **WHEN** spectrum features are available in `/mnt/user-data/outputs/spectrum_features.json`
- **THEN** the agent SHALL render a `table` component with key feature metrics: RMS, peak-to-peak, crest factor, 1X amplitude, 2X amplitude, dominant frequency, clipping detected, drift detected
- **AND** each row SHALL include the feature name, value, and unit

#### Scenario: Render spectral findings markdown

- **WHEN** `spectrum_features.json` contains `summary`, `spectral_findings`, `waveform_findings`, `suspected_faults` arrays
- **THEN** the agent SHALL render a `markdown` component summarizing each category as bulleted lists

### Requirement: Optional orbit analysis extension

After spectrum analysis completes, the agent SHALL offer optional orbit (轴心轨迹) analysis for equipment with type=70 bearings.

#### Scenario: Offer orbit analysis

- **WHEN** spectrum visualization is rendered and the equipment has bearing components (`type=70`)
- **THEN** the agent SHALL render a `markdown` prompt: "是否继续查看轴心轨迹分析？请告知目标轴承。" 
- **AND** the agent SHALL stop and wait for user response

#### Scenario: Execute orbit analysis on user request

- **WHEN** the user confirms orbit analysis with a bearing ID
- **THEN** the agent SHALL invoke `bash /mnt/skills/custom/ins-get-orbit-data/scripts/run.sh <machine_id> <bearing_id> <time_ms>`
- **AND** the agent SHALL invoke `bash /mnt/skills/custom/ins-extract-orbit-centerline-features/scripts/run.sh '<payload_json>'`
- **AND** the agent SHALL render orbit scatter chart (X probe × Y probe) with `echart` component

### Requirement: Report export integration

Spectrum analysis results SHALL be included in the monitoring report export workflow.

#### Scenario: Write monitoring features with spectrum data

- **WHEN** spectrum analysis completes and user requests report export
- **THEN** the agent SHALL assemble `monitoring_features.json` including `spectrum_data` field with chart options, feature_details, and findings
- **AND** the agent SHALL invoke `write_report(payload, "md", report_type="monitoring")` and `write_report(payload, "pdf", report_type="monitoring")` via inline Python
- **AND** the agent SHALL call `present_files` only for final `monitoring_report.md` and `monitoring_report.pdf`

#### Scenario: Spectrum data survives report round-trip

- **WHEN** `monitoring_features.json` is loaded by `export_report.load_payload(thread_id, "monitoring")`
- **THEN** the `render_monitoring_markdown` function SHALL include spectrum findings and feature table in the output

### Requirement: Data sufficiency and validation

The spectrum pipeline SHALL enforce minimum data requirements and input validation.

#### Scenario: Validate point type is 83

- **WHEN** the user selects measurement points for spectrum analysis
- **THEN** only points with `type=83` and names NOT containing "波形" SHALL be accepted

#### Scenario: Validate timestamp from trend data

- **WHEN** the user selects a target timestamp
- **THEN** the timestamp SHALL come from the trend query results (not user-invented)
- **AND** the timestamp SHALL be a valid millisecond timestamp string (digits only)

#### Scenario: Minimum waveform data points

- **WHEN** fetched waveform data contains fewer than 8 wave_y values
- **THEN** the agent SHALL render a `markdown` warning: "波形数据量不足（<8 采样点），无法进行有意义的频谱分析" and skip chart rendering
