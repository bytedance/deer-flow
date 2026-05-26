## Why

当前 `ai-report--diagnosis` agent 仅是一个薄壳，缺少完整的 GenUI 交互流水线和能力等级门控。系统已有成熟的故障诊断脚本链（`query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_analysis.py`）和专业化 agent（`fault-diagnosis--rotating/reciprocating/pump`），但诊断报告功能尚未整合到 AI 报告体系中，缺乏多设备聚合、能力等级分层（Basic/Pro/Ultra）和事件驱动调度能力。

## What Changes

- **升级 `ai-report--diagnosis` agent**：添加 `monitoring:pro` 和 `monitoring:ultra` 工具组，引入 `data-analyst` skill，重写 SOUL.md 为完整的 3 步 GenUI 流水线（故障事件选择 → 诊断范围 → 执行+导出）
- **新增 `diagnosis_report_transform.py`**：多设备诊断结果聚合脚本，支持跨设备根因关联、影响范围评估、处置建议优先级排序
- **扩展 `export_diagnosis_report.py`**：支持 Basic/Pro/Ultra 三层差异化渲染（Basic: 规则匹配结论，Pro: 多假设对比+关联分析，Ultra: 因果推断+LSTM 预测+自适应阈值）
- **完善 DSL 脚本注册**：在 `report_scripts.yaml` 中注册完整诊断流水线（query → features → analysis → transform → export）
- **新增事件驱动调度**：Ultra 等级支持 critical alarm 自动触发诊断，Pro 等级支持定时巡检式诊断

## Capabilities

### New Capabilities
- `diagnosis-report-pipeline`: 诊断报告 GenUI 流水线（故障事件选择、诊断范围配置、多设备聚合执行、分层可视化、报告导出）
- `diagnosis-report-export`: 诊断报告导出渲染（6 章节标准结构、Basic/Pro/Ultra 三层差异化内容、对比模式、PDF 导出）
- `diagnosis-report-scheduling`: 诊断报告调度（Pro 定时巡检、Ultra 事件驱动触发、去重限流）

### Modified Capabilities

## Impact

**代码变更**
- `agents/builtin/ai-report--diagnosis/config.yaml` — 添加 tool_groups 和 skill 依赖
- `agents/builtin/ai-report--diagnosis/SOUL.md` — 完整重写（~500 行）
- `skills/custom/data-analyst/scripts/diagnosis_report_transform.py` — 新建（~350 行）
- `skills/custom/data-analyst/scripts/export_diagnosis_report.py` — 扩展渲染函数（~300 行新增）
- `skills/custom/data-analyst/report_scripts.yaml` — 新增 4 个脚本声明
- `skills/custom/data-analyst/scripts/test_diagnosis_report.py` — 新建单元测试（~600 行）
- `skills/custom/data-analyst/scripts/test_diagnosis_report_integration.py` — 新建集成测试（~400 行）

**依赖**
- 复用现有脚本链：`query_diagnosis.py` / `diagnosis_features.py` / `diagnosis_analysis.py`
- 复用现有规则集：`vibration-fault-diagnosis` / `pump-fault-diagnosis` / `reciprocating-fault-diagnosis`
- 无新增外部依赖

**API**
- 无破坏性变更
- 新增 `diagnosis_report_features.json` 输出契约（per_device[]、cross_device_correlation、impact_assessment、root_cause_ranking、recommendations）

**调度**
- Pro: 定时巡检（daily embedded / weekly standalone）
- Ultra: critical alarm 事件驱动（去重窗口 2h，同一设备同一故障类型）
