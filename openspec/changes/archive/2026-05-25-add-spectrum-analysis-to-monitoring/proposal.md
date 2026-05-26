## Why

监测分析 agent 现有的 4 种分析类型（trend / anomaly / kpi_dashboard / correlation）都基于趋势数据（`getTrendDataHis`，标量 KPI 时间序列），无法利用 8k 端点已具备的波形/频谱/轴心轨迹高频数据。系统已有 `ins-get-waveform-data`、`ins-extract-spectral-waveform-features`、`ins-get-orbit-data`、`ins-extract-orbit-centerline-features` 四个技能和对应的 Python 工具，但监测分析 agent 缺少触发这些能力的入口。增加图谱分析可让用户在趋势/异常检测发现可疑时刻后，直接对特定时间点进行深挖，形成"趋势发现 → 图谱定位"的完整监测闭环。

## What Changes

- 新增第 5 种分析类型 `spectrum`，在 scope 回调表单的 `analysis_type` 枚举中增加选项
- 新增"图谱分析流水线"（Spectrum Analysis Pipeline），包含两步交互：
  - Step A：从趋势/异常结果中提取候选时间点，或允许用户手动输入时间范围，展示设备测点列表供用户选择
  - Step B：对选定的测点和时间点，调用波形/频谱获取和特征提取，用 ECharts 渲染波形图（时域）、频谱图（频域），可选轴心轨迹图
- 图表渲染：波形折线图（`wave_x` × `wave_y`）、频谱柱状图（`spec_x` × `spec_y`）、轨迹散点图（X 探头 × Y 探头）
- 特征展示：用 `table` 组件展示 `extract_spectral_waveform_features_tool` 输出的结构化特征（1X/2X 幅值、主峰、谐波模式、削波/毛刺检测、疑似故障等）
- 在异常检测管线末尾增加快捷入口："是否查看异常时刻的波形频谱？"
- 报告导出：图谱分析结果纳入 monitoring 报告，复用现有 `export_report.py` 的 `write_report` 流程

## Capabilities

### New Capabilities

- `monitoring-spectrum-analysis`: 波形频谱分析能力 — 从趋势数据中确定候选时间点，获取原始波形和频谱数据，提取频谱特征（1X/2X、谐波模式、削波/毛刺/漂移检测、疑似故障），使用 ECharts 渲染波形图、频谱图和轴心轨迹图，并将分析结果纳入监测报告导出

### Modified Capabilities

- `monitoring-anomaly-detection`: 异常检测管线末尾增加"查看波形频谱"的快捷入口，允许用户从异常时刻直接跳转到图谱分析

## Impact

- `agents/builtin/monitoring-analysis/SOUL.md` — 新增 spectrum 分支的 scope 回调和完整流水线（~200 行）
- `agents/builtin/monitoring-analysis/config.yaml` — starters 可选择性增加图谱相关快捷提示
- `skills/custom/ins-get-waveform-data/` — 复用现有技能，无需修改
- `skills/custom/ins-extract-spectral-waveform-features/` — 复用现有技能，无需修改
- `skills/custom/ins-get-orbit-data/` — 复用现有技能（可选），无需修改
- `skills/custom/ins-extract-orbit-centerline-features/` — 复用现有技能（可选），无需修改
- `backend/tests/test_monitoring_analysis_agent.py` — 新增 ~8 个测试用例覆盖图谱流水线
