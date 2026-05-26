## ADDED Requirements

### Requirement: Diagnosis report GenUI pipeline shall support fault event selection
The system SHALL provide a GenUI form for users to select fault event parameters including equipment kind, diagnosis date/time, and focus fault codes. The form SHALL validate all inputs before proceeding.

#### Scenario: Render fault event selection form
- **WHEN** user requests diagnosis report and no fault event parameters are present
- **THEN** system SHALL render `form` component with fields: `kind` (enum: centrifugal_pump, positive_displacement_pump, steam_turbine, centrifugal_compressor, reciprocating_compressor, gearbox), `diagnosis_date` (string, YYYY-MM-DD format), `diagnosis_hour` (string, "0"-"23"), `focus_codes` (multi-select from rule book codes)
- **AND** system SHALL stop and wait for user submission

#### Scenario: Validate diagnosis date format
- **WHEN** user submits form with `diagnosis_date` not matching `^\d{4}-\d{2}-\d{2}$`
- **THEN** system SHALL render markdown error message "日期格式无效，请使用 YYYY-MM-DD 格式"
- **AND** system SHALL NOT proceed to next step

#### Scenario: Validate equipment kind
- **WHEN** user submits form with `kind` not in VALID_KINDS enum
- **THEN** system SHALL render markdown error message "设备类型无效，请从列表中选择"
- **AND** system SHALL NOT proceed to next step

#### Scenario: Proceed to diagnosis scope after valid submission
- **WHEN** user submits valid fault event form
- **THEN** system SHALL extract parameters from `ui_interaction.payload` (not `values`)
- **AND** system SHALL render diagnosis scope form

### Requirement: Diagnosis report GenUI pipeline shall support diagnosis scope configuration
The system SHALL provide a GenUI form for users to configure diagnosis scope including affected equipment selection, compare window (Pro/Ultra only), and analysis depth.

#### Scenario: Render diagnosis scope form
- **WHEN** fault event form is validated successfully
- **THEN** system SHALL render `form` component with fields: `equipment_ids` (multi-select, max based on capability tier: Basic=5, Pro=20, Ultra=50), `compare_window` (optional, select: none/historical_same_event/historical_baseline, Pro/Ultra only), `analysis_depth` (enum: standard/comprehensive)

#### Scenario: Enforce equipment selection limit by tier
- **WHEN** capability_tier is "basic" and user selects 6 equipment IDs
- **THEN** system SHALL render markdown error message "Basic 等级最多支持 5 台设备"
- **AND** system SHALL NOT execute scripts

#### Scenario: Gate compare_window by capability tier
- **WHEN** capability_tier is "basic"
- **THEN** compare_window field SHALL be disabled or hidden in the form
- **AND** default value SHALL be "none"

### Requirement: Diagnosis report pipeline shall execute tier-appropriate scripts
The system SHALL execute different script chains based on capability_tier, reusing existing diagnosis scripts.

#### Scenario: Basic tier script execution
- **WHEN** capability_tier is "basic"
- **THEN** system SHALL execute: `query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_report_transform.py`
- **AND** system SHALL pass `--capability-tier basic` to transform script

#### Scenario: Pro tier script execution
- **WHEN** capability_tier is "pro"
- **THEN** system SHALL execute: `query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_analysis.py` → `pro_correlation.py` → `diagnosis_report_transform.py`
- **AND** system SHALL pass `--capability-tier pro` to transform script

#### Scenario: Ultra tier script execution
- **WHEN** capability_tier is "ultra"
- **THEN** system SHALL execute: `query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_analysis.py` → `ultra_anomaly.py` → `ultra_correlation.py` → `diagnosis_report_transform.py`
- **AND** system SHALL pass `--capability-tier ultra` to transform script

#### Scenario: Ultra model fallback to Pro
- **WHEN** capability_tier is "ultra" but ONNX model file is missing or corrupted
- **THEN** system SHALL fallback to Pro tier script chain
- **AND** system SHALL set `model_fallback: true` in diagnosis_report_features.json
- **AND** system SHALL render markdown warning "Ultra 模型不可用，已回退到 Pro 等级"

### Requirement: Diagnosis report pipeline shall aggregate multi-device results
The `diagnosis_report_transform.py` script SHALL aggregate per-device diagnosis results into a unified report payload with cross-device root cause correlation.

#### Scenario: Multi-device aggregation
- **WHEN** user selects multiple equipment IDs and diagnosis completes for all
- **THEN** transform script SHALL produce `diagnosis_report_features.json` containing: `per_device[]` (each with equipment_id, equipment_name, capability_tier, findings[], evidence_chain[], rule_matches[], recommendations[]), `cross_device_correlation` (correlated_root_causes[], shared_evidence[]), `impact_assessment` (affected_equipment_count, estimated_downtime_hours, business_impact), `root_cause_ranking` (ranked list by likelihood × severity), `recommendations` (prioritized by urgency)

#### Scenario: Single device diagnosis
- **WHEN** user selects exactly one equipment ID
- **THEN** transform script SHALL produce `diagnosis_report_features.json` with `per_device[]` containing one element
- **AND** `cross_device_correlation` SHALL be empty object `{}`
- **AND** `impact_assessment` SHALL reflect single device scope

#### Scenario: Cross-device root cause correlation
- **WHEN** two or more devices share the same root cause finding (e.g., "bearing_wear" with likelihood >= "medium")
- **THEN** `cross_device_correlation.correlated_root_causes[]` SHALL include entry with: `root_cause_id`, `root_cause_label`, `affected_devices[]` (equipment_id + equipment_name), `correlation_strength` ("high" if 3+ devices, "medium" if 2 devices)

### Requirement: Diagnosis report pipeline shall render ECharts visualizations
The system SHALL render ECharts configurations for diagnosis-specific visualizations based on capability tier.

#### Scenario: Basic tier visualization
- **WHEN** capability_tier is "basic" and diagnosis completes
- **THEN** system SHALL render `echart` component showing evidence chain verdict distribution (bar chart: exceed/marginal/normal counts per equipment)

#### Scenario: Pro tier visualization
- **WHEN** capability_tier is "pro" and diagnosis completes
- **THEN** system SHALL render `echart` components: (1) evidence chain verdict bar chart, (2) multi-hypothesis likelihood radar chart (showing candidate findings with likelihood scores), (3) cross-device correlation heatmap (if multiple devices)

#### Scenario: Ultra tier visualization
- **WHEN** capability_tier is "ultra" and diagnosis completes
- **THEN** system SHALL render `echart` components: (1) evidence chain verdict bar chart, (2) causal inference DAG diagram (showing causal relationships between parameters), (3) LSTM anomaly prediction time series (showing predicted vs actual values), (4) adaptive threshold comparison chart

### Requirement: Diagnosis report pipeline shall export final report only
The system SHALL call `present_files` only for the final diagnosis report file, never for intermediate script outputs.

#### Scenario: Export final report
- **WHEN** diagnosis pipeline completes and report is generated
- **THEN** system SHALL call `present_files` with only `diagnosis_report.md` or `diagnosis_report.pdf`
- **AND** system SHALL NOT include `query_diagnosis.json`, `diagnosis_features.json`, `diagnosis_analysis.json`, `diagnosis_report_features.json`, or any other intermediate files

#### Scenario: Generate download link
- **WHEN** report export completes
- **THEN** system SHALL render markdown with download link: `/api/threads/{thread_id}/artifacts/diagnosis_report.md`
- **AND** system SHALL display report summary (total findings, root cause count, recommendation count)

### Requirement: Diagnosis report pipeline shall select appropriate rule set
The system SHALL select the rule set based on equipment `kind` parameter for rule matching.

#### Scenario: Rotating machinery rule set
- **WHEN** `kind` is one of: steam_turbine, centrifugal_compressor, axial_compressor, multi_shaft_gear_compressor, screw_compressor, gearbox
- **THEN** system SHALL use `vibration-fault-diagnosis` rule set for rule matching

#### Scenario: Pump rule set
- **WHEN** `kind` is one of: centrifugal_pump, positive_displacement_pump
- **THEN** system SHALL use `pump-fault-diagnosis` rule set for rule matching

#### Scenario: Reciprocating machinery rule set
- **WHEN** `kind` is reciprocating_compressor
- **THEN** system SHALL use `reciprocating-fault-diagnosis` rule set for rule matching

#### Scenario: Unknown kind fallback
- **WHEN** `kind` is not in any known rule set mapping
- **THEN** system SHALL render markdown warning "未知设备类型，将使用通用振动规则集"
- **AND** system SHALL use `vibration-fault-diagnosis` as fallback rule set

### Requirement: Diagnosis report agent shall register monitoring tool groups
The `ai-report--diagnosis` agent config SHALL include `monitoring:pro` and `monitoring:ultra` tool groups and `data-analyst` skill dependency.

#### Scenario: Agent config includes monitoring tool groups
- **WHEN** agent config is loaded
- **THEN** `tool_groups` SHALL include: `bash`, `monitoring:pro`, `monitoring:ultra`
- **AND** `skills` SHALL include: `data-analyst`

#### Scenario: Agent starters include tier-specific options
- **WHEN** agent config is loaded
- **THEN** starters SHALL include: "生成诊断报告" (auto_start: true), "深度诊断分析（Ultra）" (tool_groups: [monitoring:ultra]), "多设备诊断聚合" (tool_groups: [monitoring:pro])

### Requirement: Diagnosis report pipeline shall support device kind configuration
The system SHALL maintain a `diagnosis_kind_config.yaml` file that maps each equipment `kind` to its corresponding rule set, focus codes, and visualization templates. The agent SHALL use this configuration to parameterize script execution for different device types.

#### Scenario: Load kind configuration at startup
- **WHEN** diagnosis report agent initializes
- **THEN** system SHALL load `diagnosis_kind_config.yaml` containing mappings for all supported kinds
- **AND** configuration SHALL include: kind → rules_skill, kind → focus_codes enum, kind → viz_templates, kind → query_template

#### Scenario: Route focus_codes by kind
- **WHEN** user selects equipment kind in fault event form
- **THEN** focus_codes multi-select options SHALL be populated from `diagnosis_kind_config.yaml` based on selected kind
- **AND** focus_codes SHALL reflect device-specific fault families (e.g., rotating: unbalance_1x/misalignment_2x, pump: cavitation/bearing_wear, reciprocating: valve_leak/rod_drop)

#### Scenario: Pass kind parameters to scripts
- **WHEN** executing query_diagnosis.py
- **THEN** system SHALL pass `--kind {kind}` and `--rules-skill {rules_skill}` parameters loaded from kind configuration
- **AND** query_diagnosis.py SHALL use kind-specific query templates

#### Scenario: Select device-specific visualizations
- **WHEN** rendering ECharts for diagnosis results
- **THEN** system SHALL include device-specific charts from `viz_templates` in kind configuration (e.g., orbit_plot for rotating, pv_diagram for pump, pv_indicator for reciprocating)
- **AND** generic evidence chain bar chart SHALL always be included

### Requirement: Diagnosis report pipeline shall not modify professional agents
The `ai-report--diagnosis` agent SHALL NOT modify or invoke existing `fault-diagnosis--rotating/pump/reciprocating` professional agents. All differentiation SHALL be achieved through script-level parameterization.

#### Scenario: Report agent operates independently
- **WHEN** diagnosis report agent executes pipeline
- **THEN** system SHALL NOT call or communicate with fault-diagnosis--* agents
- **AND** system SHALL execute scripts directly with kind-specific parameters

#### Scenario: Professional agents remain unchanged
- **WHEN** diagnosis report feature is deployed
- **THEN** fault-diagnosis--rotating/pump/reciprocating agents SHALL continue to operate with their existing SOUL.md and GenUI workflows
- **AND** no modifications SHALL be made to professional agent configurations or scripts

#### Scenario: Shared scripts, isolated agents
- **WHEN** both report agent and professional agents execute diagnosis
- **THEN** both SHALL use the same underlying scripts (query_diagnosis.py, diagnosis_features.py, etc.)
- **AND** scripts SHALL be parameterized to support both interactive diagnosis (professional agents) and batch report generation (report agent)

### Requirement: Diagnosis report pipeline shall handle data quality assessment
The system SHALL assess data quality before diagnosis execution and report quality issues.

#### Scenario: Data quality check passes
- **WHEN** query_diagnosis.py returns data with completeness >= 80% and no critical warnings
- **THEN** system SHALL proceed to diagnosis execution without interruption

#### Scenario: Data quality check warns
- **WHEN** query_diagnosis.py returns data with completeness < 80% or has warnings
- **THEN** system SHALL render markdown warning listing all data quality issues
- **AND** system SHALL proceed to diagnosis execution
- **AND** system SHALL include data quality warnings in final report

#### Scenario: Data source fallback indicator
- **WHEN** query_diagnosis.py uses demo_fallback data source (InS toolchain unavailable)
- **THEN** system SHALL render markdown notice "使用演示数据（InS 工具链不可用）"
- **AND** system SHALL set `data_source: "demo_fallback"` in diagnosis_report_features.json
