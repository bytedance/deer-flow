## ADDED Requirements

### Requirement: Structured monitoring report generation
The agent SHALL generate a structured monitoring analysis report containing: analysis scope, key findings (3-5 bullet summary), data visualizations (ECharts blocks), detailed analysis section, and recommendations — rendered via `render_ui` markdown with embedded chart blocks.

#### Scenario: Report sections rendered in order
- **WHEN** monitoring analysis completes data processing
- **THEN** agent renders GenUI blocks in fixed sequence: (1) `card` for scope summary, (2) `echart`/`table` blocks for analysis results, (3) `markdown` for findings + recommendations + download links

#### Scenario: Key findings precede details
- **WHEN** the final markdown block is rendered
- **THEN** it opens with a "## 关键发现" section containing 3-5 bullet points summarizing the most important observations before the detailed analysis sections

#### Scenario: Data quality notes included
- **WHEN** any data quality issues are detected during analysis (missing points, sensor gaps, outlier flags)
- **THEN** the report includes a "## 数据质量说明" section listing each issue with timestamp and affected metric

### Requirement: Dual-format export via export_report.py
The agent SHALL export the monitoring report payload to Markdown (required) and PDF (optional, if weasyprint is available) using the existing `export_report.py` infrastructure with `report_type="monitoring"`.

#### Scenario: Markdown export succeeds
- **WHEN** agent invokes `write_report(payload, "md", report_type="monitoring")` via inline Python import
- **THEN** the file `/mnt/user-data/outputs/monitoring_report.md` is written and a download link is appended to the report markdown

#### Scenario: PDF export succeeds when weasyprint is available
- **WHEN** agent invokes `write_report(payload, "pdf", report_type="monitoring")` and weasyprint is installed
- **THEN** the file `/mnt/user-data/outputs/monitoring_report.pdf` is written and a PDF download link is added

#### Scenario: PDF export degrades gracefully
- **WHEN** agent invokes `write_report(payload, "pdf", report_type="monitoring")` and weasyprint is not installed
- **THEN** `ImportError` is caught, `pdf_available = False`, and the report includes "PDF 不可用（weasyprint 未安装）"

#### Scenario: Present files exposes only final artifacts
- **WHEN** exports complete
- **THEN** agent calls `present_files` only for `monitoring_report.md` and `monitoring_report.pdf` (if available) — never for intermediate JSON files

### Requirement: Monitoring report payload schema
The monitoring report payload written to `monitoring_features.json` SHALL contain: `analysis_type`, `equipment_summary[]`, `findings[]` (with `severity`, `metric`, `description`, `confidence`), `evidence[]` (with §13.2 interpretive fields: `source_type`, `source_id`, `snapshot_path`, `time_range`), `echart_options[]` (ready-to-render ECharts configs), `data_quality[]` (warnings about missing/gap data), and `recommendations[]`.

#### Scenario: Evidence chain follows §13.2 contract
- **WHEN** monitoring report payload is assembled
- **THEN** each `evidence[]` entry includes `source_type` ("monitoring_trend"/"monitoring_anomaly"/"monitoring_kpi"/"monitoring_correlation"), `source_id`, `snapshot_path`, `checksum`, `time_range`, and `retrieved_at` ISO timestamp

#### Scenario: Recommendations are actionable
- **WHEN** report includes recommendations
- **THEN** each recommendation includes: `priority` (urgent/important/normal/observe), `action` (specific action description), `equipment_id`, and `metric` — never vague statements like "建议持续观察"
