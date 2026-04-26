# generate_line_chart — 折线图

## 功能概述
展示时间或连续自变量的趋势，可支持多系列对比，适合 KPI 监控、指标预测、走势分析。

## 输入字段
### 必填
- `data`: array<object>，每条包含 `time`（string）与 `value`（number），多系列时附带 `group`（string）。

### 可选
- `style.lineWidth`: number，自定义折线线宽。
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，指定系列颜色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。
- `axisXTitle`: string，默认空字符串。
- `axisYTitle`: string，默认空字符串。

## 使用建议
所有系列的时间点应对齐；建议按 ISO 如 `2025-01-01` 或 `2025-W01` 格式化；对于高频数据可先聚合到日/周粒度避免过密。 

## 返回结果
- 返回折线图 URL，并附 `_meta.spec` 供后续编辑。