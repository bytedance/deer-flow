# Phase 6 交付报告 — 五种业务报告 Builtin 模板

> 设计文档：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md)
> 交付日期：2026-05-18
> 范围：趋势分析 / 故障诊断 / 失效分析 / 闭环报告 / 巡检报告

## 1. 交付目标

按设计文档 §13 + 路线图 Phase 6，给 AI Report Custom Template 平台再补五种业务报告，并以 builtin DSL 模板的形式 ship 出去，验证模板平台对差异化场景（解释性 vs 事实性、动态表单、多 transform 链）的承载能力。

P2 优先：趋势分析、故障诊断
P3 优先：失效分析、闭环报告、巡检报告

## 2. 交付清单

### 2.1 data-analyst Skill 新增 12 个脚本 stub

> 全部位于 `skills/custom/data-analyst/scripts/`，统一 import `_stub_helpers`，输出 `{output_dir}/data/<name>.json`，遇到非法输入返回结构化错误 envelope。所有解释性报告（§13.2）的 transform 都带 `findings/evidence/confidence/human_review_required: true`。

| 报告 | 数据源脚本 (data_step) | 解析脚本 (transform) |
|---|---|---|
| 趋势分析 | `query_trend.py` | `trend_analysis.py` |
| 故障诊断 | `query_fault_context.py` | `build_fault_timeline.py` + `diagnosis_analysis.py` |
| 失效分析 | `query_failure_data.py` | `failure_analysis.py` |
| 闭环报告 | `query_closure_items.py` | `closure_summary.py` |
| 巡检报告 | `query_inspection.py` | `inspection_summary.py` + `inspection_attachment_summary.py` |

所有 stub 均输出确定性合成数据，让模板可端到端验证；真实数据接入时只替换 stub 内部逻辑即可。

### 2.2 Builtin 模板（5 个）

每个模板都有 `default.yaml`（DSL v1）+ `metadata.yaml`，落在 `agents/builtin/report-templates/`：

| 目录 | display_name | 解释性 | 章节数 |
|---|---|---|---|
| `trend-equipment/` | 设备趋势分析报告 | ✓ (§13.2) | 5 |
| `diagnosis-fault/` | 故障诊断报告 | ✓ (§13.2) | 5 |
| `failure-analysis/` | 失效分析报告 | ✓ (§13.2) | 5 |
| `closure-summary/` | 问题闭环报告 |  | 5 |
| `inspection/` | 巡检报告 |  | 6 |

设计要点：
- 趋势/失效模板使用 `before_step` 调用 `list_equipment` 提供动态 KPI 选项；
- 故障诊断模板演示了一个 data_step + 多 transform（`build_fault_timeline` 与 `diagnosis_analysis` 同时消费同一 `fault_context.fault_context`）；
- 巡检模板把同一个 `inspection_data` 喂给两个 transform，分别产出"概况"和"附件汇总"，验证多 transform 收敛能力；
- 所有模板 `export.formats: [md, pdf]`，符合 §12.2（md 必选）。

### 2.3 Skill Registry 更新

`skills/custom/data-analyst/report_scripts.yaml` 新增 12 条 script 描述符，分组在新的 Phase 6 注释段下。

注：该文件在交付期间被项目内 linter 自动补入 `query_monthly` 的 `args_aliases` 字段（DSL 短名 `mom`/`yoy` → 长名 `previous_month`/`previous_year_month` 翻译）。为承接这个改动，扩展了 `ScriptDescriptorYaml` 与 `ScriptDescriptor`，加入 `args_aliases: dict[str, dict[str, str]]` 字段（默认空）。

### 2.4 Schema 微调

| 文件 | 改动 |
|---|---|
| `packages/harness/deerflow/report_templates/script_registry.py` | `ScriptDescriptorYaml` / `ScriptDescriptor` 新增 `args_aliases` 字段 |
| `tests/test_ai_report_weekly_registry.py` | 放宽 `output_files` / `outputs_schema` 校验，区分 `form_options` 与其它 kind |
| `tests/test_ai_report_weekly_export.py` | 把"非法 report_type"用例从 `monthly`（已合法）改为 `quarterly`（始终非法）|

## 3. 验证

### 3.1 builtin 模板 CI 校验

`tests/test_builtin_report_templates.py` 自动遍历 `agents/builtin/report-templates/*/default.yaml`，跑 `validate_dsl`（schema + cross-ref + JSONPath + 脚本契约）。

```
tests/test_builtin_report_templates.py::test_builtin_template_validates[closure-summary]    PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[daily-equipment]    PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[diagnosis-fault]    PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[failure-analysis]   PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[inspection]         PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[monthly-equipment]  PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[trend-equipment]    PASSED
tests/test_builtin_report_templates.py::test_builtin_template_validates[weekly-equipment]   PASSED
tests/test_builtin_report_templates.py::test_at_least_one_builtin_template_exists           PASSED
```

5 个新模板全部 zero-warning 通过校验，原有 3 个 (daily/weekly/monthly) 不回归。

### 3.2 报告模板全部测试套

```
tests/test_builtin_report_templates.py              9 passed
tests/test_ai_report_weekly_*.py                    65 passed (修复 4 处既有用例)
tests/test_report_template_schema.py                27 passed
tests/test_report_template_validator.py             28 passed
tests/test_report_template_records.py               24 passed
tests/test_report_template_routes.py                14 passed
tests/test_report_template_runtime.py               21 passed
tests/test_report_template_repository.py            26 passed
tests/test_report_template_permissions.py           25 passed
tests/test_report_template_source_resolver.py       43 passed
tests/test_report_template_lifecycle_tools.py       22 passed
tests/test_report_template_script_registry.py       15 passed
tests/test_report_template_generic_renderer.py      21 passed
tests/test_report_template_push_block.py            7 passed
                                                   ──────────
                                                    347 passed
```

### 3.3 不在本期范围的失败

主仓库 `pytest` 全跑还能看到 156 个失败用例（`test_paths_user_isolation`, `test_tenant_client`, `test_tenant_memory`, `test_uploads_router`, `test_setup_agent_tool`, `test_initialize_admin` 等）。逐项核对后这些都是与用户隔离 / 租户 / 权限初始化相关的既有问题，在 Phase 6 起手前就存在，不在本 Sprint 修复目标内。

## 4. 设计回顾与权衡

1. **Stub 优先**：业务侧的真实接入还在排期，本期把所有脚本都做成确定性 stub。好处是 DSL → 渲染端到端可跑、CI 可验证；坏处是 stub 自带数据假设（合成时序、模拟问题单），不可作为产品试点的回归基准。后续真实接入时一一替换即可，输出 schema 已锁。

2. **多 transform 拓扑**：故障诊断使用了"一份数据 → 两个 transform"（`build_fault_timeline` 和 `diagnosis_analysis` 都读 `fault_context`），巡检也类似（概况 + 附件分两个 transform 输出）。这验证了 §5.4 transform 顺序模型在非线性 DAG 上的可行性 — 后续如果有 transform 依赖前序 transform 输出的需求，DSL 已经支持。

3. **§13.2 解释性报告约束**：四份带"解释"性质的报告全部带证据 + 置信度 + `human_review_required: true`。`provenance_evidence()` helper 让每个证据项都带 `source_type / source_id / snapshot_path / checksum / time_range / retrieved_at`，UI 渲染端只需读 evidence[] 就能展示溯源链。

4. **`args_aliases` 字段**：linter 在 `query_monthly` 上补了一个 alias 映射，平台需要承接但不应让原有 builtin 模板回归。落地方式是在 schema 层新增空 default 字段，对老模板透明；DSL templates 也无需改动。alias 翻译留给 data-runner 后续实现（已在 design doc §3.3 中提及，runner 层目前未消费该字段，但 schema 已 ready）。

## 5. 文件清单

### 新增
- `skills/custom/data-analyst/scripts/_stub_helpers.py`
- `skills/custom/data-analyst/scripts/query_trend.py`, `trend_analysis.py`
- `skills/custom/data-analyst/scripts/query_fault_context.py`, `build_fault_timeline.py`, `diagnosis_analysis.py`
- `skills/custom/data-analyst/scripts/query_failure_data.py`, `failure_analysis.py`
- `skills/custom/data-analyst/scripts/query_closure_items.py`, `closure_summary.py`
- `skills/custom/data-analyst/scripts/query_inspection.py`, `inspection_summary.py`, `inspection_attachment_summary.py`
- `agents/builtin/report-templates/{trend-equipment,diagnosis-fault,failure-analysis,closure-summary,inspection}/{default.yaml,metadata.yaml}`

### 修改
- `skills/custom/data-analyst/report_scripts.yaml` — Phase 6 注册 12 条新 script
- `backend/packages/harness/deerflow/report_templates/script_registry.py` — `args_aliases` 字段
- `backend/tests/test_ai_report_weekly_registry.py` — 放宽 `form_options` 类型校验
- `backend/tests/test_ai_report_weekly_export.py` — 修正失效用例

## 6. 后续工作 (out of scope)

- 真实数据接入：用 TSDB / 工单系统 / 巡检系统的 connector 替换 stub 实现，输出 schema 保持兼容
- `args_aliases` 在 data-runner 层的具体翻译实现（design doc §3.3 已规划）
- 5 个新报告的前端样式微调（generic_renderer 已经能跑，但部分章节的 markdown / table 可以根据 UX 反馈调整）
- 既有 156 个无关失败用例的清理（路径隔离 / 租户 / 上传 / 管理员初始化）
