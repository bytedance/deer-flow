## ADDED Requirements

### Requirement: Spectrum analysis entry point from anomaly results

The agent SHALL offer a quick-entry to spectrum analysis at the end of the anomaly detection pipeline when anomalies are detected.

#### Scenario: Anomalies detected — offer spectrum drill-down

- **WHEN** the anomaly detection pipeline completes and at least 1 anomaly point was found
- **THEN** the agent SHALL render a `markdown` block after the anomaly summary table stating: "发现 N 个异常时刻。如需查看异常时刻的波形频谱特征，请在下一次分析中选择「图谱分析」类型，系统将引导您选择具体时间点和测点进行深挖。"
- **AND** the markdown SHALL list the top 3 anomaly timestamps as clickable reference

#### Scenario: No anomalies — skip spectrum suggestion

- **WHEN** the anomaly detection pipeline completes and no anomalies were found
- **THEN** the agent SHALL NOT render spectrum analysis suggestion
