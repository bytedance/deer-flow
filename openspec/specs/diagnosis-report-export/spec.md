## ADDED Requirements

### Requirement: Diagnosis report shall render 6-section markdown structure
The `render_diagnosis_markdown()` function SHALL produce a markdown report with exactly 6 sections: (1) 设备与任务, (2) 异常发现, (3) 证据链, (4) 诊断结论, (5) 鉴别诊断, (6) 维护建议. Each section SHALL adapt content based on capability_tier.

#### Scenario: Basic tier report structure
- **WHEN** capability_tier is "basic"
- **THEN** markdown SHALL contain all 6 sections
- **AND** section 4 (诊断结论) SHALL contain rule_matches table (rule_id, description, confidence, supporting_evidence_count)
- **AND** section 5 (鉴别诊断) SHALL list excluded hypotheses from rule matching
- **AND** section 6 (维护建议) SHALL contain rule-derived recommendations

#### Scenario: Pro tier report structure
- **WHEN** capability_tier is "pro"
- **THEN** markdown SHALL contain all 6 sections
- **AND** section 4 SHALL additionally contain multi-hypothesis comparison table (candidate_id, label, likelihood, severity, rationale, supporting_evidence_count)
- **AND** section 4 SHALL contain cross-device correlation paragraph (if multiple devices)
- **AND** section 6 SHALL contain correlation-derived recommendations

#### Scenario: Ultra tier report structure
- **WHEN** capability_tier is "ultra"
- **THEN** markdown SHALL contain all 6 sections
- **AND** section 4 SHALL additionally contain causal inference results (cause → effect relationships with p-values)
- **AND** section 4 SHALL contain LSTM anomaly prediction summary (predicted vs actual, confidence intervals)
- **AND** section 6 SHALL contain adaptive threshold recommendations

### Requirement: Diagnosis report shall render report metadata header
The markdown SHALL include a metadata section with report generation context.

#### Scenario: Metadata header with all fields
- **WHEN** diagnosis_report_features.json contains report_meta object
- **THEN** markdown SHALL include: 设备类型 (kind), 规则集 (rules_skill), 数据来源 (data_source), 报告生成时间 (generated_at), 能力等级 (capability_tier)

#### Scenario: Metadata header with model fallback
- **WHEN** model_fallback flag is true
- **THEN** markdown SHALL include warning line: "⚠ 模型回退：Ultra 模型不可用，已回退到 Pro 等级"

#### Scenario: Metadata header with schedule label
- **WHEN** schedule_label field is present (e.g., "事件驱动 · critical alarm · 2026-05-26 14:00")
- **THEN** markdown SHALL include schedule label in metadata section

### Requirement: Diagnosis report shall render equipment summary
The markdown SHALL include equipment summary for each device in the diagnosis scope.

#### Scenario: Multi-device equipment summary
- **WHEN** per_device[] contains multiple devices
- **THEN** section 1 SHALL list each device with: equipment_name, operation_phase, alarm_status

#### Scenario: Single device equipment summary
- **WHEN** per_device[] contains one device
- **THEN** section 1 SHALL list the single device with all fields

#### Scenario: Equipment summary with max value
- **WHEN** device has max_value data (point, feature, value, unit)
- **THEN** section 2 (异常发现) SHALL include max value line for that device

### Requirement: Diagnosis report shall render evidence chain table
The markdown SHALL include evidence chain as a table with verdict classification.

#### Scenario: Evidence chain table with all verdicts
- **WHEN** evidence_chain[] contains entries with verdict "exceed", "marginal", "normal"
- **THEN** section 3 SHALL render table with columns: 指标, 特征, 值, 阈值, 判定
- **AND** verdict SHALL be rendered as: exceed → "超阈值", marginal → "边缘", normal → "正常"

#### Scenario: Empty evidence chain
- **WHEN** evidence_chain[] is empty
- **THEN** section 3 SHALL render: "_本次诊断未收集到证据链数据_"

### Requirement: Diagnosis report shall render root cause ranking
The markdown SHALL include root cause ranking section with likelihood and severity scores.

#### Scenario: Root cause ranking with multiple candidates
- **WHEN** root_cause_ranking[] contains multiple entries
- **THEN** section 4 SHALL render table with columns: 排名, 根因, 可能性, 严重度, 依据
- **AND** entries SHALL be sorted by likelihood (high > medium > low) then severity

#### Scenario: Root cause ranking with primary finding
- **WHEN** one entry has is_primary: true
- **THEN** that entry SHALL be marked with "★ 主要根因" label

#### Scenario: Empty root cause ranking
- **WHEN** root_cause_ranking[] is empty
- **THEN** section 4 SHALL render: "_未识别到明确根因，建议人工复核_"

### Requirement: Diagnosis report shall render cross-device correlation
The markdown SHALL include cross-device correlation section when multiple devices are diagnosed.

#### Scenario: Correlated root causes across devices
- **WHEN** cross_device_correlation.correlated_root_causes[] is non-empty
- **THEN** markdown SHALL include paragraph: "跨设备关联分析：{root_cause_label} 影响 {device_count} 台设备（{device_names}）"

#### Scenario: No cross-device correlation
- **WHEN** cross_device_correlation is empty object or correlated_root_causes[] is empty
- **THEN** cross-device correlation section SHALL be omitted

### Requirement: Diagnosis report shall render impact assessment
The markdown SHALL include impact assessment section with business impact metrics.

#### Scenario: Impact assessment with all fields
- **WHEN** impact_assessment contains affected_equipment_count, estimated_downtime_hours, business_impact
- **THEN** section SHALL render: "影响范围：{affected_equipment_count} 台设备，预估停机 {estimated_downtime_hours} 小时，业务影响：{business_impact}"

#### Scenario: Impact assessment missing fields
- **WHEN** impact_assessment is missing some fields
- **THEN** markdown SHALL render "—" for missing fields

### Requirement: Diagnosis report shall render differential diagnosis
The markdown SHALL include differential diagnosis section listing excluded hypotheses.

#### Scenario: Differential diagnosis with excluded hypotheses
- **WHEN** differential_diagnosis[] contains entries with reason_excluded
- **THEN** section 5 SHALL render table: 排除假设, 排除依据

#### Scenario: Empty differential diagnosis
- **WHEN** differential_diagnosis[] is empty
- **THEN** section 5 SHALL render: "_无排除假设_"

### Requirement: Diagnosis report shall render prioritized recommendations
The markdown SHALL include recommendations section sorted by priority.

#### Scenario: Recommendations with priority levels
- **WHEN** recommendations[] contains entries with priority "urgent", "important", "routine"
- **THEN** section 6 SHALL render recommendations sorted by priority (urgent first)
- **AND** each recommendation SHALL show: priority label (紧急/重要/常规), action, rationale

#### Scenario: Empty recommendations
- **WHEN** recommendations[] is empty
- **THEN** section 6 SHALL render: "_暂无维护建议_"

### Requirement: Diagnosis report shall support HTML rendering for PDF export
The `render_diagnosis_html()` function SHALL produce HTML suitable for weasyprint PDF conversion.

#### Scenario: HTML report generation
- **WHEN** write_report() is called with fmt="pdf" and report_type="diagnosis"
- **THEN** system SHALL call render_diagnosis_html() to generate HTML
- **AND** HTML SHALL include same 6-section structure as markdown
- **AND** HTML SHALL include CSS styling for tables, verdict colors, and priority labels

#### Scenario: PDF export with weasyprint unavailable
- **WHEN** weasyprint is not installed or import fails
- **THEN** system SHALL fallback to markdown export
- **AND** system SHALL log warning about PDF unavailable
