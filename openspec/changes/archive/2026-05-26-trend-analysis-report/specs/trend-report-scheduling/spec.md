## ADDED Requirements

### Requirement: 独立触发模式
趋势分析报告 SHALL 支持用户手动触发。用户通过 AI 报告入口选择"趋势分析报告"后，系统 SHALL 启动 GenUI 参数收集流水线并生成报告。

#### Scenario: 手动触发趋势报告
- **WHEN** 用户在对话框中选择 `ai-report--trend` agent 的 starter "生成趋势分析报告"
- **THEN** 系统渲染设备选择器，启动 3 步流水线（设备选择 → 分析范围 → 执行+导出）

#### Scenario: 自然语言触发
- **WHEN** 用户输入"帮我分析一下设备最近的运行趋势"
- **THEN** 系统匹配到趋势报告意图，启动 `ai-report--trend` agent 的流水线

### Requirement: Pro 定时调度
Pro 等级 SHALL 支持定时调度趋势分析报告。调度模式包含日报（嵌入趋势段落）和周报（独立趋势报告）。

#### Scenario: 日报嵌入趋势段落
- **WHEN** Pro 调度器触发日报生成且 `include_trend: true`
- **THEN** 日报流水线在 KPI 章节后追加趋势分析段落：拉取最近 24h 数据的趋势分析，渲染简版趋势图表和劣化预警，嵌入日报 Markdown

#### Scenario: 独立周趋势报告
- **WHEN** Pro 调度器触发周趋势报告
- **THEN** 系统独立生成覆盖上周数据的完整趋势分析报告，输出到 `/mnt/user-data/outputs/trend_report_weekly_{date}.md`

#### Scenario: 调度参数映射
- **WHEN** 调度模式为 `daily`
- **THEN** 趋势分析使用 `--aggregation hourly --forecast-horizon 1`；调度模式为 `weekly` 时使用 `--aggregation daily --forecast-horizon 7`

### Requirement: Ultra 事件驱动调度
Ultra 等级 SHALL 支持事件驱动的趋势分析。当 InS 告警系统产生 `severity=critical` 的告警事件时，系统 SHALL 自动触发告警设备的趋势分析。

#### Scenario: 告警触发趋势分析
- **WHEN** InS 产生 `severity=critical` 的告警事件
- **THEN** 系统自动拉取告警设备在告警时刻前后 ±7 天的趋势数据，运行 `ultra_trend.py` 分析，生成趋势报告归档到 `/mnt/user-data/outputs/`

#### Scenario: 去重限流
- **WHEN** 同一设备在 4 小时内已被事件驱动分析过
- **THEN** 系统跳过本次触发，不重复生成报告（通过检查 `trend_report_features.json` 时间戳去重）

### Requirement: 调度结果通知
调度生成的趋势分析报告 SHALL 通过 `present_files` 推送下载链接。定时调度的报告 SHALL 在报告标题中标注调度来源。

#### Scenario: 定时报告通知
- **WHEN** Pro 定时调度生成趋势报告
- **THEN** 报告标题格式为 `# 趋势分析报告（定时 · {daily/weekly} · {date}）`，系统推送下载链接

#### Scenario: 事件驱动报告通知
- **WHEN** Ultra 事件驱动生成趋势报告
- **THEN** 报告标题格式为 `# 趋势分析报告（告警触发 · {设备名} · {date}）`，系统推送下载链接和告警关联信息

### Requirement: 对比周期数据拉取
当用户选择环比（wow）或同比（yoy）对比模式时，Pro/Ultra 等级 SHALL 额外拉取对比周期的趋势数据。

#### Scenario: 环比数据拉取
- **WHEN** 用户选择对比模式为 `wow`（环比），当前分析范围为 2026-05-19 ~ 2026-05-25
- **THEN** 系统额外调用 `query_trend.py --date-range 2026-05-12..2026-05-18`，输出对比周期数据 `trend_data_compare.json`

#### Scenario: 同比数据拉取
- **WHEN** 用户选择对比模式为 `yoy`（同比），当前分析范围为 2026-05-01 ~ 2026-05-31
- **THEN** 系统额外调用 `query_trend.py --date-range 2025-05-01..2025-05-31`，输出对比周期数据 `trend_data_compare.json`

#### Scenario: 对比可视化
- **WHEN** 对比模式已启用且对比数据已拉取
- **THEN** 趋势图表中叠加对比周期虚线（当前周期实线，对比周期虚线），报告中标注变化幅度百分比
