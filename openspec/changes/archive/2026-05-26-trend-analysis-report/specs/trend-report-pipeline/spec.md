## ADDED Requirements

### Requirement: 设备选择参数收集
趋势分析报告 SHALL 通过 GenUI `device-selector-multi` 组件收集用户选择的设备列表。设备选择器的 `maxSelect` 参数 SHALL 根据能力等级动态调整（Basic=5, Pro=20, Ultra=50）。

#### Scenario: Basic 等级设备选择
- **WHEN** 用户以 Basic 等级启动趋势分析报告
- **THEN** 系统渲染 `device-selector-multi` 组件，`maxSelect` 设为 5，`queryParams.orgId` 使用当前组织 ID

#### Scenario: Pro 等级设备选择
- **WHEN** 用户以 Pro 等级启动趋势分析报告
- **THEN** 系统渲染 `device-selector-multi` 组件，`maxSelect` 设为 20，支持按设备类型分组展示

#### Scenario: Ultra 等级设备选择
- **WHEN** 用户以 Ultra 等级启动趋势分析报告
- **THEN** 系统渲染 `device-selector-multi` 组件，`maxSelect` 设为 50，`queryParams.orgId` 为 0（跨组织查询）

### Requirement: 分析范围参数收集
趋势分析报告 SHALL 通过 GenUI `form` 组件收集分析时间范围、关注指标和对比模式。分析类型固定为 trend，不展示分析类型选择器。

#### Scenario: 分析范围表单渲染
- **WHEN** 用户完成设备选择并提交
- **THEN** 系统渲染包含以下字段的表单：开始日期（date）、结束日期（date）、关注指标（multi-select，可选）、对比模式（select：无/环比/同比）

#### Scenario: 日期校验
- **WHEN** 用户提交的日期范围超过 365 天或格式不匹配 `^\d{4}-\d{2}-\d{2}$`
- **THEN** 系统渲染 `markdown` 提示具体错误，要求用户重新提交，不执行任何脚本

#### Scenario: 对比模式 Pro 门控
- **WHEN** 用户选择"环比"或"同比"对比模式但能力等级为 Basic
- **THEN** 系统忽略对比模式参数，在报告中标注对比功能需要 Pro 等级

### Requirement: 趋势数据拉取
趋势分析报告 SHALL 调用 `query_trend.py` 脚本拉取时间序列数据。聚合粒度 SHALL 根据时间跨度自动选择（≤7 天 hourly，8-60 天 daily，>60 天 weekly）。

#### Scenario: 短期数据拉取
- **WHEN** 用户选择的时间范围为 5 天
- **THEN** 系统调用 `query_trend.py --aggregation hourly`，输出 `/mnt/user-data/outputs/data/trend_data.json`

#### Scenario: 中期数据拉取
- **WHEN** 用户选择的时间范围为 30 天
- **THEN** 系统调用 `query_trend.py --aggregation daily`，输出 `/mnt/user-data/outputs/data/trend_data.json`

#### Scenario: 数据拉取错误处理
- **WHEN** `query_trend.py` 返回 JSON 包含 `error` 字段
- **THEN** 系统渲染 `markdown` 说明错误原因，终止分析流程，不生成报告

### Requirement: 趋势分析执行
趋势分析报告 SHALL 根据能力等级调用对应的趋势分析脚本：Basic 调用 `trend_analysis.py`，Pro 调用 `pro_trend.py`，Ultra 调用 `ultra_trend.py`。

#### Scenario: Basic 趋势分析
- **WHEN** 能力等级为 Basic
- **THEN** 系统调用 `trend_analysis.py --input trend_data.json`，确认 `/mnt/user-data/outputs/data/trend_analysis.json` 存在

#### Scenario: Pro 趋势分析
- **WHEN** 能力等级为 Pro
- **THEN** 系统调用 `pro_trend.py --input trend_data.json`，确认 `/mnt/user-data/outputs/data/pro_trend_analysis.json` 存在

#### Scenario: Ultra 趋势分析与回退
- **WHEN** 能力等级为 Ultra 且 ONNX 模型文件 `/opt/features-tool/models/trend_forecaster.onnx` 不存在
- **THEN** 系统回退调用 `pro_trend.py`，在报告 payload 中标注 `model_fallback: true`

#### Scenario: Pro 回退到 Basic
- **WHEN** 能力等级为 Pro 但 `pro_trend.py` 依赖缺失（`scikit-learn`/`statsmodels`/`ruptures` 未安装）
- **THEN** 系统回退调用 `trend_analysis.py`，在报告 payload 中标注 `capability_fallback: true`

### Requirement: 数据质量评估
Pro/Ultra 等级 SHALL 在趋势分析前执行数据质量评估脚本 `data_quality.py`。

#### Scenario: Pro 数据质量评估
- **WHEN** 能力等级为 Pro 且 `trend_data.json` 已生成
- **THEN** 系统调用 `data_quality.py --input trend_data.json --tier pro`，将输出的缺失值位置和完整率注入报告 payload 的 `data_quality` 字段

#### Scenario: Basic 跳过数据质量评估
- **WHEN** 能力等级为 Basic
- **THEN** 系统跳过数据质量评估步骤，报告 payload 的 `data_quality` 为空数组

### Requirement: 趋势可视化渲染
趋势分析报告 SHALL 对每个有显著趋势的指标渲染 ECharts 折线图。Pro/Ultra 等级 SHALL 额外渲染多模型对比图、STL 分解子图和变点标注。

#### Scenario: Basic 趋势图表
- **WHEN** Basic 等级分析完成，指标 `vibration_level` 的 `direction` 为 `increasing`
- **THEN** 系统渲染包含历史数据、7 日移动平均、预测线和阈值线的 ECharts 折线图

#### Scenario: Pro 增强图表
- **WHEN** Pro 等级分析完成
- **THEN** 系统额外渲染：多模型对比图（线性/多项式/指数叠加）、STL 分解 3 子图（trend/seasonal/residual）、PELT 变点竖虚线标注、95% 置信区间带

#### Scenario: Ultra LSTM 预测图
- **WHEN** Ultra 等级分析完成且 LSTM 模型可用
- **THEN** 系统额外渲染 LSTM 预测叠加图（历史 + LSTM 预测 + 80%/95% 置信区间带状）和协变组卡片

### Requirement: 多设备趋势聚合
趋势分析报告 SHALL 支持多设备趋势结果的聚合。`trend_report_transform.py` 脚本 SHALL 将多台设备的趋势分析结果合并为统一报告 payload。

#### Scenario: 多设备聚合
- **WHEN** 用户选择了 3 台设备，每台设备的趋势分析已完成
- **THEN** `trend_report_transform.py` 输出 `/mnt/user-data/outputs/trend_report_features.json`，包含 `per_device[]`（逐设备结果）和 `cross_device_summary`（跨设备摘要）

#### Scenario: 设备数超限
- **WHEN** 用户选择的设备数超过当前能力等级上限
- **THEN** 系统在设备选择步骤即拒绝，渲染 `markdown` 提示设备数限制

### Requirement: 报告章节结构
趋势分析报告 SHALL 包含以下标准章节：执行摘要、逐设备趋势详析、横向对比（多设备时）、劣化预警、预测、维护建议。

#### Scenario: 单设备报告结构
- **WHEN** 用户选择 1 台设备生成趋势报告
- **THEN** 报告包含：执行摘要、设备趋势详析、劣化预警、预测、维护建议（跳过横向对比章节）

#### Scenario: 多设备报告结构
- **WHEN** 用户选择 3 台设备生成趋势报告
- **THEN** 报告包含：执行摘要、逐设备趋势详析（3 节）、横向对比（同指标跨设备对比表）、劣化预警（跨设备排序）、预测、维护建议

### Requirement: 能力等级确定
趋势分析报告 SHALL 根据用户意图和运行时上下文确定能力等级。默认使用 Pro 等级。

#### Scenario: 默认 Pro 等级
- **WHEN** 用户未指定能力等级
- **THEN** 系统使用 Pro 等级（`capability_tier: pro`），调用 `pro_trend.py`

#### Scenario: 用户指定 Ultra
- **WHEN** 用户消息中包含"深度分析"、"预测"或"Ultra"
- **THEN** 系统使用 Ultra 等级（`capability_tier: ultra`），调用 `ultra_trend.py`

#### Scenario: 用户指定 Basic
- **WHEN** 用户消息中包含"快速"、"简单"或"闪速"
- **THEN** 系统使用 Basic 等级（`capability_tier: basic`），调用 `trend_analysis.py`
