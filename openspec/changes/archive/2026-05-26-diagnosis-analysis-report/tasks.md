# Implementation Tasks

## 1. Agent 配置升级

- [x] 1.1 升级 `agents/builtin/ai-report--diagnosis/config.yaml`：添加 `monitoring:pro` 和 `monitoring:ultra` 工具组引用，增加 `data-analyst` skill 依赖，补充 starters（生成诊断报告、深度诊断分析（Ultra）、多设备诊断聚合）
- [x] 1.2 重写 `agents/builtin/ai-report--diagnosis/SOUL.md`：包含完整的 3 步 GenUI 流水线（故障事件选择 → 诊断范围 → 执行+导出）、能力等级门控逻辑、脚本调度指令、可视化渲染规范、报告导出指令、规则集选择逻辑

## 2. 设备类型配置

- [x] 2.1 创建 `skills/custom/data-analyst/diagnosis_kind_config.yaml`：定义每个 `kind` 对应的 `rules_skill`、`family`、`focus_codes`（从规则集提取）、`viz_templates`、`query_template` 映射
- [x] 2.2 从 `vibration-fault-diagnosis` / `pump-fault-diagnosis` / `reciprocating-fault-diagnosis` 规则集中提取所有 fault code 列表，填入 `diagnosis_kind_config.yaml` 的 `focus_codes` 字段

## 3. 诊断报告 Transform 脚本

- [x] 3.1 创建 `skills/custom/data-analyst/scripts/diagnosis_report_transform.py`：实现多设备诊断结果聚合逻辑，输入为 per-device 诊断 JSON 路径列表，输出 `diagnosis_report_features.json`（含 `per_device[]`、`cross_device_correlation`、`impact_assessment`、`root_cause_ranking`、`recommendations` 字段）
- [x] 3.2 在 `diagnosis_report_transform.py` 中实现跨设备根因关联逻辑：对同 root_cause_id 跨设备聚合，生成 correlated_root_causes 列表（含 correlation_strength 评分）
- [x] 3.3 在 `diagnosis_report_transform.py` 中实现影响评估逻辑：汇总 affected_equipment_count、estimated_downtime_hours、business_impact
- [x] 3.4 在 `diagnosis_report_transform.py` 中实现根因排序逻辑：按 likelihood × severity 排序生成 root_cause_ranking
- [x] 3.5 为 `diagnosis_report_transform.py` 编写单元测试 `tests/test_diagnosis_report_transform.py`：覆盖单设备、多设备、跨设备关联、影响评估、根因排序等场景

## 4. 报告导出扩展

- [x] 4.1 在 `export_diagnosis_report.py` 中扩展 `render_diagnosis_markdown()` 函数：支持 Basic/Pro/Ultra 三层差异化内容渲染（Pro: 多假设对比表+跨设备关联段落，Ultra: 因果推断结果+LSTM 预测摘要+自适应阈值推荐）
- [x] 4.2 在 `render_diagnosis_markdown()` 中实现报告元信息段落：设备类型、规则集、数据来源、生成时间、能力等级、模型回退标志、调度标签
- [x] 4.3 在 `render_diagnosis_markdown()` 中实现跨设备关联段落：当 correlated_root_causes 非空时生成关联分析描述
- [x] 4.4 在 `render_diagnosis_markdown()` 中实现影响评估段落：affected_equipment_count、estimated_downtime_hours、business_impact
- [x] 4.5 在 `render_diagnosis_markdown()` 中实现根因排序表格：排名、根因、可能性、严重度、依据，标记主要根因
- [x] 4.6 在 `render_diagnosis_report.py` 中扩展 `render_diagnosis_html()` 函数：支持新增的 Pro/Ultra 段落的 HTML 渲染（表格、颜色标注、优先级标签）
- [x] 4.7 为扩展后的 `render_diagnosis_markdown()` 编写单元测试：覆盖单设备/多设备、Basic/Pro/Ultra、模型回退、调度标签、空数据等场景

## 5. DSL 脚本声明

- [x] 5.1 在 `report_scripts.yaml` 中注册 `query_diagnosis` 脚本声明：定义 `entry`、`kind: [transform]`、`args_schema`（含 kind、diagnosis_date、diagnosis_hour、focus_codes、equipment_ids）和 `output_files`
- [x] 5.2 在 `report_scripts.yaml` 中注册 `diagnosis_features` 脚本声明：定义 `entry`、`kind: [transform]`、`args_schema`（含 input 路径、rules_skill、skills_root）和 `output_files`
- [x] 5.3 在 `report_scripts.yaml` 中注册 `diagnosis_report_transform` 脚本声明：定义 `entry`、`kind: [transform]`、`args_schema`（含 inputs 文件路径列表、output 路径、capability_tier 枚举、equipment_ids csv、equipment_names csv、compare_mode 枚举）和 `output_files`
- [x] 5.4 验证 DSL 模板平台可发现所有诊断相关脚本声明

## 6. SOUL.md 流水线详细设计

- [x] 6.1 在 SOUL.md 中编写故障事件选择步骤：`form` 组件配置（kind 枚举、diagnosis_date YYYY-MM-DD、diagnosis_hour 0-23、focus_codes 多选）、回调处理、参数校验（日期格式、设备类型枚举）
- [x] 6.2 在 SOUL.md 中编写诊断范围步骤：`form` 组件配置（equipment_ids 多选，按能力等级限制 maxSelect: 5/20/50、compare_window 选择（Pro/Ultra only）、analysis_depth 枚举）、回调处理、设备数量校验、能力等级门控对比模式
- [x] 6.3 在 SOUL.md 中编写执行步骤：能力等级判断逻辑、规则集选择（kind → rule set 映射，从 diagnosis_kind_config.yaml 加载）、脚本调度命令（Basic/Pro/Ultra 分支，传入 --kind 和 --rules-skill 参数）、数据质量评估调用、错误处理
- [x] 6.4 在 SOUL.md 中编写可视化渲染步骤：ECharts 配置（Basic: 证据链判定柱状图 + 设备特定图表、Pro: 多假设雷达图+跨设备关联热力图、Ultra: 因果推断 DAG+LSTM 预测时序图+自适应阈值对比图）
- [x] 6.5 在 SOUL.md 中编写报告导出步骤：调用 `diagnosis_report_transform.py`、组装 `diagnosis_report_features.json`、调用 `render_diagnosis_markdown()`、`write_report()`、`present_files()`、下载链接生成
- [x] 6.6 在 SOUL.md 中编写调度模式段落：Pro 定时调度（日报嵌入/独立周报）、Ultra 事件驱动调度（critical alarm 触发、去重窗口 2h、设备限流 3/天、系统限流 10/h）、报告标题格式

## 7. 集成测试与验证

- [x] 7.1 端到端测试：Basic 等级单设备诊断报告生成（从故障事件选择到 Markdown 下载）
- [x] 7.2 端到端测试：Pro 等级多设备诊断报告生成（含多假设对比和跨设备关联）
- [x] 7.3 端到端测试：Ultra 等级回退到 Pro（ONNX 模型缺失场景）
- [ ] 7.4 验证 `export_diagnosis_report.py` 的 PDF 导出（weasyprint 可用和不可用两种场景）
- [x] 7.5 验证中间文件不暴露：确认 `present_files` 仅调用最终报告文件
- [ ] 7.6 验证事件驱动调度去重逻辑：同一设备同一故障类型 2h 内不重复触发
- [ ] 7.7 验证设备限流逻辑：同一设备每天最多 3 份诊断报告
- [x] 7.8 验证设备类型配置：不同 kind（pump/rotating/reciprocating）加载正确的规则集和 focus_codes
