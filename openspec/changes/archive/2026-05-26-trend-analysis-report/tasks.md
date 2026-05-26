# Implementation Tasks

## 1. Agent 配置升级

- [x] 1.1 升级 `agents/builtin/ai-report--trend/config.yaml`：添加 `monitoring:pro` 和 `monitoring:ultra` 工具组引用，增加 `data-analyst` skill 依赖，补充 starters（生成趋势分析报告、深度趋势分析、快速趋势扫描）
- [x] 1.2 重写 `agents/builtin/ai-report--trend/SOUL.md`：包含完整的 3 步 GenUI 流水线（设备选择 → 分析范围 → 执行+导出）、能力等级门控逻辑、脚本调度指令、可视化渲染规范、报告导出指令

## 2. 趋势报告 Transform 脚本

- [x] 2.1 创建 `skills/custom/data-analyst/scripts/trend_report_transform.py`：实现多设备趋势分析结果聚合逻辑，输入为 per-device 趋势分析 JSON 路径列表，输出 `trend_report_features.json`（含 `per_device[]`、`cross_device_summary`、`degradation_alerts`、`forecasts`、`recommendations` 字段）
- [x] 2.2 在 `trend_report_transform.py` 中实现横向对比逻辑：对同指标跨设备提取趋势方向和斜率，生成排序后的劣化优先级列表
- [x] 2.3 在 `trend_report_transform.py` 中实现环比/同比对比逻辑：读取 `trend_data_compare.json`，计算变化幅度百分比，生成对比摘要字段
- [x] 2.4 为 `trend_report_transform.py` 编写单元测试 `tests/test_trend_report_transform.py`：覆盖单设备、多设备、对比模式、降级回退等场景

## 3. 报告导出扩展

- [x] 3.1 在 `export_report.py` 的 `SUPPORTED_REPORT_TYPES` 中注册 `trend` 类型
- [x] 3.2 在 `export_report.py` 的 `_output_dir()` 函数中添加 `trend` 类型的环境变量解析链（`TREND_REPORT_OUTPUT_DIR` → `DAILY_REPORT_OUTPUT_DIR` → 默认值）
- [x] 3.3 实现 `render_trend_markdown()` 函数：标准章节结构（标题/元信息/执行摘要/逐设备详析/横向对比/劣化预警/预测/维护建议），支持 Basic/Pro/Ultra 三层的差异化内容渲染
- [x] 3.4 在 `render_trend_markdown()` 中实现 Pro 增强段落：多模型对比表、STL 分解描述、变点检测结果、置信区间说明
- [x] 3.5 在 `render_trend_markdown()` 中实现 Ultra 增强段落：LSTM 预测值表、协变组列表、自适应阈值推荐、模型置信度标注
- [x] 3.6 在 `render_trend_markdown()` 中实现对比模式段落：环比/同比数据对比表、变化幅度百分比、趋势偏离说明
- [x] 3.7 在 `write_report()` 函数中添加 `trend` 类型的分支处理（调用 `render_trend_markdown()` 生成 Markdown，weasyprint 可用时生成 PDF）
- [x] 3.8 为 `render_trend_markdown()` 编写单元测试：覆盖单设备/多设备、Basic/Pro/Ultra、对比模式、空数据等场景

## 4. DSL 脚本声明

- [x] 4.1 在 `report_scripts.yaml` 中注册 `trend_report_transform` 脚本声明：定义 `entry`、`kind: [transform]`、`args_schema`（含 `inputs` 文件路径列表、`output` 路径、`capability_tier` 枚举、`compare_mode` 枚举）和 `output_files`
- [x] 4.2 验证 DSL 模板平台可发现 `data-analyst/trend_report_transform` 脚本声明（手动验证或通过现有 loader 测试）

## 5. SOUL.md 流水线详细设计

- [x] 5.1 在 SOUL.md 中编写设备选择步骤：`device-selector-multi` 组件配置（按能力等级调整 `maxSelect` 和 `queryParams`）、回调处理、参数校验
- [x] 5.2 在 SOUL.md 中编写分析范围步骤：`form` 组件配置（日期范围、指标多选、对比模式选择）、回调处理、日期校验、能力等级门控对比模式
- [x] 5.3 在 SOUL.md 中编写执行步骤：能力等级判断逻辑、脚本调度命令（Basic/Pro/Ultra 分支）、数据质量评估调用、错误处理
- [x] 5.4 在 SOUL.md 中编写可视化渲染步骤：ECharts 折线图配置（Basic）、Pro 增强图表（多模型对比/STL/变点/置信区间）、Ultra LSTM 预测图
- [x] 5.5 在 SOUL.md 中编写报告导出步骤：调用 `trend_report_transform.py`、组装 `trend_report_features.json`、调用 `render_trend_markdown()`、`write_report()`、`present_files()`、下载链接生成
- [x] 5.6 在 SOUL.md 中编写调度模式段落：Pro 定时调度（日报嵌入/独立周报）、Ultra 事件驱动调度、去重限流、报告标题格式

## 6. 集成测试与验证

- [x] 6.1 端到端测试：Basic 等级单设备趋势报告生成（从设备选择到 Markdown 下载）
- [x] 6.2 端到端测试：Pro 等级多设备趋势报告生成（含多模型对比和环比对比）
- [x] 6.3 端到端测试：Ultra 等级回退到 Pro（ONNX 模型缺失场景）
- [x] 6.4 验证 `export_report.py` 的 `trend` 类型 PDF 导出（weasyprint 可用和不可用两种场景）
- [x] 6.5 验证中间文件不暴露：确认 `present_files` 仅调用最终报告文件
