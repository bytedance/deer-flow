## Context

当前系统具备完整的故障诊断能力，分布在三个层面：

1. **专业化 agent**：`fault-diagnosis--rotating/reciprocating/pump` 拥有成熟的 GenUI 流水线（sub-device-selector → 诊断时间表单 → 脚本执行 → 报告导出），脚本链 `query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_analysis.py` 已稳定运行
2. **规则集**：`vibration-fault-diagnosis` / `pump-fault-diagnosis` / `reciprocating-fault-diagnosis` 提供设备类型特定的故障规则匹配
3. **AI 报告 agent**：`ai-report--diagnosis` 当前仅是一个薄壳，SOUL.md 只描述了报告结构，无 GenUI 流水线、无能力等级门控、无脚本调度

趋势分析报告（trend-analysis-report）已完成类似的升级，验证了以下模式：
- 3 步 GenUI 流水线（选择 → 范围 → 执行）
- 能力等级门控（Basic/Pro/Ultra）
- 聚合脚本（transform）+ 分层渲染（render_*_markdown）
- DSL 注册 + 集成测试

## Goals / Non-Goals

**Goals:**
- 将 `ai-report--diagnosis` 升级为全功能诊断报告 agent，复用现有脚本链和规则集
- 实现多设备诊断结果聚合（跨设备根因关联、影响范围评估）
- 支持 Basic/Pro/Ultra 三层能力等级，Pro 增加多假设对比，Ultra 增加因果推断和 LSTM 预测
- 支持事件驱动调度（Ultra: critical alarm 自动触发）和定时巡检（Pro: weekly）
- 生成结构化诊断报告（6 章节标准结构），支持 Markdown + PDF 导出
- 完整的单元测试和集成测试覆盖

**Non-Goals:**
- 不修改现有 `fault-diagnosis--*` 专业 agent 的流水线（它们面向交互式单设备诊断，本变更面向报告聚合）
- 不新增脚本链中的数据采集或特征计算脚本（复用 `query_diagnosis.py` / `diagnosis_features.py` / `diagnosis_analysis.py`）
- 不实现实时流式诊断（仅支持批量和事件触发）
- 不修改现有规则集内容（仅引用）

## Decisions

### Decision 1: 复用现有脚本链 vs 新建诊断脚本

**选择**：复用 `query_diagnosis.py` → `diagnosis_features.py` → `diagnosis_analysis.py`，新增 `diagnosis_report_transform.py` 作为聚合层

**理由**：
- 现有脚本链已在 fault-diagnosis--* agent 中验证，数据契约（`query_diagnosis.json` / `diagnosis_features.json`）稳定
- `diagnosis_analysis.py`（Sprint S2）已实现 §13.2 合规的解释性分析（多假设、证据链、影响评估）
- 仅需新增聚合脚本处理多设备场景的横向关联

**替代方案**：新建独立的诊断报告脚本链 → 代码重复，维护成本高，且需重新验证数据契约

### Decision 2: 独立报告类型 vs 监测报告子类型

**选择**：在 `export_report.py` 中注册独立的 `diagnosis` 报告类型，调用独立的 `export_diagnosis_report.py` 渲染模块

**理由**：
- 诊断报告有独立的 6 章节结构（设备与任务 / 异常发现 / 证据链 / 诊断 / 鉴别诊断 / 建议），与监测报告（8 章节趋势分析结构）差异大
- `export_diagnosis_report.py` 已存在且实现了 `render_diagnosis_markdown()` 和 `render_diagnosis_html()`
- 独立类型便于独立演进，不影响监测报告的稳定性

**替代方案**：在监测报告中添加诊断段落 → 结构耦合，渲染逻辑复杂化

### Decision 3: 能力等级门控策略

**选择**：
- **Basic**：规则匹配结论 + 单设备诊断，使用 `diagnosis_features.py` 的规则匹配输出
- **Pro**：多假设对比 + 跨设备关联分析，使用 `diagnosis_analysis.py` 的多候选根因 + `pro_correlation.py` 的关联分析
- **Ultra**：因果推断 + LSTM 异常预测 + 自适应阈值，使用 `ultra_anomaly.py` 的 LSTM + `ultra_correlation.py` 的 Granger 因果检验

**理由**：
- 与监测分析的能力等级门控保持一致（Basic: 统计 / Pro: ML / Ultra: DL+因果）
- 现有脚本已按能力等级分层（`pro_anomaly.py` / `ultra_anomaly.py`），直接复用

### Decision 4: GenUI 流水线组件选择

**选择**：3 步流水线
1. **故障事件选择**：`form` 组件（设备类型 kind、故障时间 diagnosis_date、故障小时 diagnosis_hour、故障家族 focus_codes）
2. **诊断范围**：`form` 组件（受影响设备多选、对比时间窗口、分析深度）
3. **执行 + 导出**：脚本调度 → `echart` 可视化 → `markdown` 报告 → `present_files` 下载

**理由**：
- 诊断场景不需要设备选择器（用户已知故障设备），使用 form 更高效
- 参考 `fault-diagnosis--rotating/SOUL.md` 的 sub-device-selector + form 模式，但简化为 form-only（报告场景不需要子设备级别的精细选择）

**替代方案**：使用 `sub-device-selector` → 对报告场景过重，用户通常已知故障设备

### Decision 5: 事件驱动调度策略（Ultra）

**选择**：
- 触发条件：收到 `critical` 级别 alarm，且 alarm 关联的设备类型在 `VALID_KINDS` 中
- 去重窗口：同一设备同一故障类型 2h 内不重复触发
- 自动填充：diagnosis_date = alarm 时间，diagnosis_hour = alarm 小时，focus_codes = alarm 关联的故障家族
- 报告标题格式：`诊断报告 · {设备名} · {故障时间} · {故障类型}`

**理由**：
- 与监测分析的 Ultra 事件驱动模式一致
- 2h 去重窗口避免 alarm 风暴导致报告泛滥
- 自动填充减少用户干预，实现"零点击"诊断

## Decision 6: 设备类型兼容策略（脚本级委托）

**选择**：不通过 agent 间调度，而是在脚本层通过 `kind` 参数路由到不同的规则集、focus_codes 枚举和可视化模板。新增 `diagnosis_kind_config.yaml` 作为配置中心。

**理由**：
- `fault-diagnosis--rotating/pump/reciprocating` 三个专业 agent 的差异化主要体现在**脚本参数**（kind、rules_skill、focus_codes 枚举），而非 agent 运行时能力
- 脚本链已支持 kind 路由：`query_diagnosis.py` 有 `VALID_KINDS` 枚举，`diagnosis_features.py` 通过 `--rules-skill` 参数选择规则集
- 新增 `ai-report--diagnosis` 只需在 SOUL.md 中根据用户选择的 kind 传入不同参数，所有执行在同一个 agent 上下文内完成，避免 agent 间通信复杂度
- 专业 agent 的 SOUL.md 继续独立演进，报告 agent 仅读取脚本输出，不修改任何专业 agent 文件

**实施要点**：

- 新增 `diagnosis_kind_config.yaml`，定义每个 kind 对应的：`rules_skill`、`focus_codes`（从对应规则集的 code 列表提取）、`viz_templates`（可视化模板引用）、`query_template`（InS 查询模板引用）
- SOUL.md 中维护 kind → config 映射表，故障事件选择表单的 `focus_codes` 选项根据选中的 kind 动态加载
- `query_diagnosis.py` 和 `diagnosis_features.py` 通过 CLI 参数（`--kind`、`--rules-skill`、`--focus-codes`）接收配置，无需修改脚本内部逻辑
- 可视化层：基础图表（证据链柱状图）通用；设备特定图表（轴心轨迹、PV 示功图）通过 `viz_templates` 字段引用预定义的 ECharts option 片段

**设备类型映射示例**（diagnosis_kind_config.yaml）：

```yaml
kinds:
  centrifugal_pump:
    rules_skill: pump-fault-diagnosis
    family: pump
    focus_codes: [cavitation, bearing_wear, seal_leak, impeller_damage, misalignment]
    viz_templates: [pump_pv_diagram, vibration_spectrum]
  steam_turbine:
    rules_skill: vibration-fault-diagnosis
    family: rotating
    focus_codes: [unbalance_1x, misalignment_2x, oil_whirl, rub, crack]
    viz_templates: [orbit_plot, bode_plot, vibration_spectrum]
  reciprocating_compressor:
    rules_skill: reciprocating-fault-diagnosis
    family: reciprocating
    focus_codes: [valve_leak, rod_drop, ring_wear, pulsation, knock]
    viz_templates: [pv_indicator, rod_position, vibration_spectrum]
```

**替代方案**：

- agent 级委托（ai-report--diagnosis 调用 fault-diagnosis--* agent）→ 引入 agent 间通信复杂度，且专业 agent 的 SOUL.md 包含交互式流程（sub-device-selector），不适合报告聚合场景
- 复制脚本逻辑到 report agent 内部 → 代码重复，违反 DRY

## Risks / Trade-offs

- **[风险] 多设备聚合时脚本链执行时间长** → 缓解：Basic 限制 5 设备，Pro 限制 20 设备，Ultra 限制 50 设备；超时时生成部分报告并标注
- **[风险] 规则集不完整导致漏诊** → 缓解：报告中明确标注规则集名称和版本，未匹配的证据链保留在报告中供人工审查
- **[风险] Ultra LSTM 模型缺失导致回退** → 缓解：检测 ONNX 模型文件，缺失时自动回退到 Pro 并设置 `model_fallback: true` 标志
- **[风险] 事件驱动调度与手动诊断冲突** → 缓解：事件触发和手动触发使用相同的去重窗口，避免重复
- **[风险] diagnosis_kind_config.yaml 与专业 agent 的规则集不同步** → 缓解：配置中 `rules_skill` 和 `focus_codes` 直接引用规则集文件，规则集更新时只需同步更新配置
- **[权衡] 不修改 fault-diagnosis--* agent** → 它们继续作为交互式单设备诊断入口，ai-report--diagnosis 作为报告聚合入口，两者独立演进；脚本层共享但 agent 层隔离

## Migration Plan

无破坏性变更，新增功能向后兼容：
1. 现有 `export_report.py` 已支持 `diagnosis` 类型，仅需扩展渲染函数
2. 现有 `report_scripts.yaml` 已注册 `diagnosis_analysis`，仅需补充其他脚本声明
3. 现有 `fault-diagnosis--*` agent 不受影响

## Open Questions

- 是否需要支持"历史诊断对比"模式（将当前诊断与历史同类故障对比）？当前设计未包含，可作为后续迭代
- 是否需要诊断报告的团队协作功能（多人审阅、批注）？超出当前范围
