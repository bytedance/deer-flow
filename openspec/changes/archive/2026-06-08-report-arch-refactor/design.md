## Context

当前所有报告（builtin 日报/周报/月报 + 自定义报告）共用一套 DSL 模板引擎。引擎提供 8 个运行时工具（`prepare_run` → `render_step` ⟷ `submit_step` → `run_data_steps` → `assemble_payload` → `render_report` → `export`），通过状态机驱动 LLM 按序调用。

Builtin 三报的执行流程是固定的：scope → equipment → kpis → data → render → export。将它们强制走 DSL 状态机导致：
- SOUL.md 需要 ~30 行 deep-link 直达约束（教 LLM 跳过 `render_step`、直接 `submit_step`）
- LLM 幻觉可能触发 `before_step` 脚本调用 Organize API 失败
- 不必要的状态管理（status.json、expected_step、state transitions）

DSL 引擎的真正价值在于自定义报告：用户通过模板市场创建模板，定义自己的 form_steps、data_steps、sections。这部分需要保留。

## Goals / Non-Goals

**Goals:**
- Builtin 三报（daily/weekly/monthly）从 DSL 状态机解耦，直执行 Skill 脚本
- 简化 builtin agent 的 SOUL.md，移除 deep-link 直达约束规则
- 保留 DSL 模板引擎完整功能，仅服务自定义报告
- 保持 deep-link 参数直达能力（参数解析 + 直执行）
- Blueprint fork 机制支持从 builtin 模板派生自定义变体

**Non-Goals:**
- 不删除 DSL 模板引擎代码（`report_templates/runtime/`）
- 不改变 Skill 脚本接口（`query_daily.py`、`daily_kpi.py`、`export_report.py` 保持不变）
- 不修改前端（直执行对前端透明，仍通过 GenUI 渲染报告）
- 不改变 DSL 模板 API（`/api/report-templates/*` 保持不变）

## Decisions

### Decision 1: 直执行工具设计 — 新增 `report_direct_*` 工具族

**选项 A**：新增专用工具 `report_direct_execute`（单工具，接受报告类型 + 参数，内部编排脚本调用）
**选项 B**：复用现有 `bash` 工具，LLM 直接调用 Skill 脚本（当前 SOUL.md 中 Round 2 回调的脚本调用方式）
**选项 C**：新增 3 个工具 `report_direct_prepare` / `report_direct_run` / `report_direct_export`（细粒度控制）

**选择：选项 A**。理由：
- 单工具接口最简单，LLM 只需一次调用
- 内部编排逻辑封装在 Python 代码中，不依赖 LLM 按序调用 bash
- 错误处理、重试、产物路径管理集中在工具内部
- 与 DSL 工具（`report_template_*`）对称，易于理解和测试

**工具签名**：
```python
@tool
def report_direct_execute(
    report_type: str,        # "daily" | "weekly" | "monthly"
    scope: dict,             # {report_date} / {week_start, date_end} / {report_month}
    equipment_type: str,     # "all" | "static_equipment" | ...
    compare_with: str,       # "previous_day" | "none" | ...
    equipment_ids: list[str] | None,
    equipment_labels: list[str] | None,
    kpi_keys: list[str] | None,
) -> str:
    """Direct execution for builtin reports. Bypasses DSL state machine."""
```

### Decision 2: 路由机制 — 基于 agent name 前缀

**选项 A**：agent config 新增 `executor_type: "direct" | "dsl"` 字段
**选项 B**：基于 agent name 前缀路由（`ai-report--daily/weekly/monthly` → direct，其他 → dsl）
**选项 C**：基于 template_id 前缀路由（`daily-equipment` → direct，`user-*` → dsl）

**选择：选项 B**。理由：
- 无需修改 agent config schema（向后兼容）
- Builtin agent name 是固定的，路由逻辑简单
- 自定义报告使用 `ai-report--custom` agent，自动走 DSL 路径
- Blueprint fork 后的自定义模板使用 `ai-report--custom`，无需额外配置

**路由位置**：在 `PassthroughParamsMiddleware` 或新增 `ReportExecutorRouter` 中实现。检查 `agent_config.name`，匹配 builtin 三报名称则注入直执行指令，否则注入 DSL 指令。

### Decision 3: SOUL.md 简化策略

**当前**：SOUL.md 包含 ~30 行 deep-link 直达约束（禁止 render_step、必须按序列执行 8 步）。
**目标**：SOUL.md 只需说明"deep-link 参数齐全时调用 `report_direct_execute` 工具"。

**简化前后对比**：
```markdown
# 当前（30+ 行）
**deep-link 直达约束（必须遵守）**
当 deep-link 参数齐全时，**禁止**调用 `report_template_render_step`...
必须按以下序列执行：
1. report_template_prepare_run(...)
2. report_template_submit_step(...)
...
严禁行为：❌ ... ❌ ...
必须行为：...

# 目标（5 行）
## Deep-Link 直达
当 `<deep_link_params>` 包含必选参数时，调用 `report_direct_execute` 工具，
传入解析后的参数。工具内部自动完成数据获取、KPI 计算、报告生成、导出。
```

### Decision 4: Blueprint fork 机制

**当前**：Blueprint 定义在 `agents/builtin/report-templates/*/default.yaml`，fork 后生成自定义模板走 DSL。
**目标**：Blueprint 增加 `executor_type` 标记。Builtin blueprint 标记为 `direct`，fork 后自动转为 `dsl`。

**实现**：
- Blueprint YAML 新增 `executor_type: direct` 字段（仅 builtin 模板）
- Fork API（`POST /api/report-templates/{id}/fork`）自动将 `executor_type` 改为 `dsl`
- Fork 后的模板使用 `ai-report--custom` agent，走 DSL 路径

### Decision 5: Deep-link 参数解析位置

**选项 A**：LLM 解析 `<deep_link_params>` 块，提取参数后调用 `report_direct_execute`
**选项 B**：中间件解析参数，直接注入工具调用（绕过 LLM 解析）

**选择：选项 A**。理由：
- 与当前架构一致（`PassthroughParamsMiddleware` 已注入 `<deep_link_params>` 块）
- LLM 负责参数校验和回退逻辑（参数缺失时渲染表单）
- 避免中间件过度复杂化

## Risks / Trade-offs

**Risk 1**: 直执行工具内部脚本调用失败时，错误信息可能不如 DSL 状态机详细
→ **Mitigation**: 工具内部捕获脚本异常，返回结构化错误（`{error: {code, message, step}}`），LLM 渲染 markdown 提示用户

**Risk 2**: Builtin 报告失去 DSL 模板的灵活性（如用户想修改 builtin 报告的 sections）
→ **Mitigation**: 用户通过 Blueprint fork 创建自定义变体，fork 后的模板走 DSL 路径，可自由修改

**Risk 3**: 两套执行路径增加维护成本
→ **Mitigation**: 直执行工具（~300 行）+ DSL 引擎（~7100 行，保持不变）。新增代码量小，DSL 引擎不修改

**Trade-off**: 直执行工具是"硬编码"流程，未来如果 builtin 报告需要动态调整流程，需要修改代码而非配置
→ **Acceptable**: Builtin 三报的流程已稳定，动态调整需求通过 fork 自定义模板满足

## Migration Plan

### Phase 1: 新增直执行工具（无破坏性）
1. 创建 `backend/packages/harness/deerflow/report_executor/` 模块
2. 实现 `report_direct_execute` 工具（内部编排 Skill 脚本）
3. 新增单元测试（覆盖 daily/weekly/monthly 三种类型）
4. 保留现有 DSL 工具，builtin agent 仍可使用

### Phase 2: 路由 + SOUL.md 简化
1. 新增 `ReportExecutorRouter` 中间件（基于 agent name 路由）
2. 简化 builtin agent 的 SOUL.md（移除 deep-link 约束，改为调用直执行工具）
3. 更新 `PassthroughParamsMiddleware` 注入逻辑（根据路由结果注入不同指令）
4. 运行现有 deep-link 测试，验证直执行路径

### Phase 3: Blueprint fork 机制
1. Blueprint YAML schema 新增 `executor_type` 字段
2. Fork API 自动转换 `executor_type: direct → dsl`
3. 更新 Blueprint 测试

### Rollback
- Phase 1 可独立回滚（新增模块，不影响现有代码）
- Phase 2 回滚：恢复 SOUL.md 旧版本，禁用 `ReportExecutorRouter`
- Phase 3 回滚：移除 `executor_type` 字段，fork API 恢复旧逻辑
