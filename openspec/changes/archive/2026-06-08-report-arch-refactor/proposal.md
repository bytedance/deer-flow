## Why

Builtin 三报（日报/周报/月报）的执行流程是固定的（scope → equipment → kpis → data → render → export），但当前被强制走 DSL 模板引擎的状态机（`pending → awaiting_step → ready_for_data → ...`），导致：

1. **Deep-link 直达脆弱**：LLM 必须精确遵循 SOUL.md 中的 8 步执行序列，跳过 `render_step` 直接调 `submit_step`，任何幻觉都会触发 `before_step` 脚本调用 Organize API 失败，最终引发 `GraphRecursionError`。
2. **不必要的抽象层**：~7100 行 DSL 模板引擎代码（状态机、schema 验证、step 渲染/提交、data runner、payload builder）为固定流程服务，增加了调试复杂度和出错面。
3. **SOUL.md 膨胀**：每个 report agent 的 SOUL.md 包含 ~30 行 deep-link 直达约束规则（禁止 render_step、禁止 before_step、必须按序列执行），这些规则本质上是在用自然语言硬编码执行流程——既然流程固定，不如直接在代码中硬编码。

同时，用户自定义报告场景确实需要 DSL 模板引擎的灵活性（动态 form_steps、可配置 data_steps、自定义 sections）。因此不能完全删除 DSL 引擎，而是将它限定为自定义报告专用的可选层。

## What Changes

- **新增 Direct Report Executor**：为 builtin 三报创建独立的直执行模块，绕过 DSL 状态机，直接调用 Skill 脚本（`query_daily.py` → `daily_kpi.py` → `export_report.py`）。
- **重构 SOUL.md**：简化 builtin agent 的 SOUL.md，移除 deep-link 直达约束规则（不再需要教 LLM 绕过 DSL 状态机），改为直执行工具的调用说明。
- **DSL 模板引擎降级为自定义报告专用**：保留完整 DSL 引擎代码，但 builtin 三报不再使用。DSL 引擎仅在用户通过模板市场创建自定义模板时激活。
- **Deep-link 参数处理简化**：builtin 报告的 deep-link 参数直接映射为直执行函数的参数，不再需要转换为 DSL `submit_step` 的 payload。
- **Blueprint 模板 fork 机制**：用户可从 builtin 报告的 blueprint fork 出自定义变体，fork 后的模板走 DSL 引擎执行，与 builtin 直执行路径完全隔离。

## Capabilities

### New Capabilities
- `builtin-report-direct-executor`: Builtin 报告直执行器，绕过 DSL 状态机，直接编排 Skill 脚本调用链。覆盖日报/周报/月报三种报告类型的参数解析、脚本调用、产物导出。
- `custom-report-template-engine`: 自定义报告 DSL 模板引擎（从现有 report_templates 模块重构），仅服务用户创建的自定义模板。包括模板存储、DSL 运行时、GenUI 表单渲染。
- `report-executor-routing`: 报告执行路由，根据 agent 类型（builtin vs custom）选择直执行或 DSL 引擎路径。通过 agent config 中的 `executor_type` 字段路由。

### Modified Capabilities
- `report-deep-link-direct`: Builtin 报告的 deep-link 直达从"教 LLM 绕过 DSL 状态机"改为"直执行函数直接消费参数"，简化为参数解析 + 直执行调用。
- `template-blueprint`: Blueprint fork 后生成的自定义模板明确走 DSL 引擎路径，与 builtin 直执行路径分离。Blueprint 定义中增加 `executor_type` 标记。

## Impact

- **Backend code**:
  - 新增 `backend/packages/harness/deerflow/report_executor/` 模块（直执行器）
  - 修改 `agents/builtin/ai-report--*/SOUL.md`（简化 deep-link 规则）
  - 修改 `backend/packages/harness/deerflow/tools/builtins/report_template_runtime_tools.py`（增加路由逻辑）
  - DSL 引擎代码（`report_templates/runtime/`）保留不删，但 builtin agent 不再调用
- **Agent config**:
  - `agents/builtin/ai-report--*/config.yaml` 新增 `executor_type: direct` 字段
- **Tests**:
  - 新增直执行器单元测试
  - 修改 deep-link 集成测试（验证直执行路径）
  - DSL 引擎测试保留（服务自定义报告场景）
- **Breaking changes**: 无外部 API 变更，内部重构对前端透明
