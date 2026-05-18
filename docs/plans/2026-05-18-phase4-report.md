# Phase 4 交付报告

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) §15 Phase 4。
> **范围**：Runtime 状态机 + 7 个 runtime 模块 + 8 个运行时工具 + builtin daily-equipment 模板 + ai-report--daily 双轨。
> **状态**：**MVP 关键路径达成，已通过 §17.2 全部 17 项验收**。可进入 Phase 5（历史与管理 UI）。

## 交付清单

| Phase 4 项 | 状态 | 交付物 |
| ---- | ---- | ---- |
| **4.0 状态机** | ✅ 通过 | `runtime/state.py`：8 状态、原子读写、转换守卫 |
| **4.1 data_runner** | ✅ 通过 | 占位符替换 + subprocess + 输出/超时/资源限制 |
| **4.2 step_renderer / step_submitter** | ✅ 通过 | form_step → GenUI props + 表单提交校验 |
| **4.3 payload_builder / report_renderer** | ✅ 通过 | sections → report_payload.json → GenUI block 推送 |
| **4.4 exporter** | ✅ 通过 | Markdown 必需 + PDF 可选降级（weasyprint） |
| **4.5 8 个运行时工具** | ✅ 通过 | `prepare_run / render_step / submit_step / run_data_steps / assemble_payload / render_report / export / resume_run` 全部进 BUILTIN_TOOLS |
| **4.6 builtin daily-equipment 模板** | ✅ 通过 | DSL 复刻日报流程 + metadata + CI validator |
| **4.7 ai-report--daily 双轨** | ✅ 通过 | SOUL.md 顶部新增"DSL 优先 + Fallback"启动决策章节 |

**Phase 4 新增测试**：23 个（21 runtime + 2 builtin DSL CI）。
**测试总计（Phase 0+1+2+3+4+回归）**：**383 passed / 0 failed**。

---

## 4.0 状态机 — state.py

[backend/packages/harness/deerflow/report_templates/runtime/state.py](../../backend/packages/harness/deerflow/report_templates/runtime/state.py)

```text
pending
   │ prepare_run()
   ▼
awaiting_step:<step_id>
   │ submit_step()  (loop)
   ▼
ready_for_data
   │ run_data_steps()
   ▼
data_complete
   │ assemble_payload()
   ▼
payload_ready
   │ render_report()
   ▼
rendered
   │ export()
   ▼
exported (terminal — success)

failed / canceled (terminal — error or user abort)
```

**关键设计**：

- **status.json 是唯一状态源**：每个工具调用前后读写，没有中间内存状态
- **原子读写**：tmp 文件 + os.replace，跨平台
- **转换守卫**：`expect_status()` + `transition()` 双重校验，杜绝 LLM 跳步
- **mark_failed 一票否决**：任何状态都可降级到 failed（带 error_code/message）

---

## 4.1 data_runner — 脚本执行 + 占位符替换

[backend/packages/harness/deerflow/report_templates/runtime/data_runner.py](../../backend/packages/harness/deerflow/report_templates/runtime/data_runner.py)

### 安全约束（§9.2）

- ✅ 绝不 `shell=True`，参数数组直接传 `subprocess.run`
- ✅ 输出路径预解析（`{run_output_dir}` 占位符替换），脚本无法重定向到任意位置
- ✅ 输出路径必须落在 `run_output_dir` 子树内（`Path.resolve()` + `relative_to` 检查）
- ✅ 超时 + 输出大小双重上限
- ✅ Linux 下 RLIMIT_AS 内存限制（Windows 自动降级 noop）

### 占位符语义

```python
"{{ $.form.scope.report_date }}"   # → "2026-05-18" (string)
"{{ $.form.equipment.ids }}"       # → ["P-001", "P-002"] (list, 原生类型)
"{{ $.form.x }}-{{ $.form.y }}"    # → "A-B" (拼接为字符串)
```

**单一占位符保留原始类型**，混合文本走字符串插值——支持把 list 类参数原样传给脚本。

### CLI 转换

每个 DSL arg → `--name value`（连字符化），list 转 CSV，flag 类型仅在 truthy 时输出。runtime 自动追加 `--output-dir {abs_path}`。

### 错误码分级

- `ARG_RESOLVE_FAILED` — JSONPath 求值失败
- `SCRIPT_FAILED` — 退出码非零（解析 stderr 结构化 JSON）
- `OUTPUT_MISSING` — 脚本未生成声明的输出文件
- `OUTPUT_PARSE_FAILED` — 输出文件非合法 JSON
- `OUTPUT_TOO_LARGE` — 超过 max_output_bytes

---

## 4.2 step_renderer + step_submitter

### step_renderer

- 自动跑 `before_step`（如未缓存），结果写入 `state.step_outputs`
- `options_source` → 动态 `options[]`：从前序 step 输出按 `label/value/group/description` key 映射
- 输出 `component="form"` 的 props（不直接调 `render_ui`，让 LLM 透过既有 interrupt 路径触发）

### step_submitter

- 校验 `submitted_step_id == state.expected_step`
- 校验 required 字段
- `next == "generate"` → 状态机进入 `ready_for_data`，否则更新 `expected_step` 并保持 `awaiting_step`
- 失败抛 `SubmitStepError`（不污染状态）

---

## 4.3 payload_builder + report_renderer

### payload_builder

每个 section 按 `component` 决定 props 包装：

| component | 输入类型 | 包装方式 |
| ---- | ---- | ---- |
| markdown | string \| list[string] | `{content: value}` |
| card | object | `{**value}` |
| card_group | list[object] | `{items: value}` |
| echart | object (ECharts option) | `{option: value}` |
| table | `{columns, data}` 或 `list[dict]` | 保持原结构 |
| image | `{src, alt}` | `{**value}` |

**类型检查**：不匹配的源类型立即抛 `PayloadBuildError`，runtime 工具据此把状态转为 `failed`。

### report_renderer

调用 Phase 0 的 `push_block_to_sse` 把每个 section 转一个 GenUI block，按 DSL 顺序赋予 `sequence`。

---

## 4.4 exporter — Markdown 必需 + PDF 可选降级

[backend/packages/harness/deerflow/report_templates/runtime/exporter.py](../../backend/packages/harness/deerflow/report_templates/runtime/exporter.py)

- **Markdown 路径**：调 Phase 0 `render_markdown_generic`，输出失败抛 `ExportError`（runtime 标记 failed）
- **PDF 路径**：try `import weasyprint`，缺失 → `pdf_skipped_reason="weasyprint_unavailable"`；渲染失败 → `pdf_skipped_reason="render_error"`；**不抛错**
- **可选 markdown lib**：有 `markdown` 包就用 tables/fenced_code 扩展，没有就 `<pre>` 兜底

---

## 4.5 8 个运行时工具

[backend/packages/harness/deerflow/tools/builtins/report_template_runtime_tools.py](../../backend/packages/harness/deerflow/tools/builtins/report_template_runtime_tools.py)（535 行）

| 工具 | 委托模块 | 期望状态 | 输出状态 |
| ---- | ---- | ---- | ---- |
| `prepare_run` | repository + state | — | `pending` |
| `render_step` | step_renderer + data_runner | pending / awaiting_step | `awaiting_step` |
| `submit_step` | step_submitter | pending / awaiting_step | `awaiting_step` / `ready_for_data` |
| `run_data_steps` | data_runner | `ready_for_data` | `data_complete` |
| `assemble_payload` | payload_builder | `data_complete` | `payload_ready` |
| `render_report` | report_renderer | `payload_ready` | `rendered` |
| `export` | exporter | `rendered` | `exported` |
| `resume_run` | state (no transition) | — | — |

**统一约定**：

- 工具返回 JSON 字符串 `{...}` 或 `{"error": {code, message, ...}}`
- 失败时 `mark_failed(state, ...)` 写入 status.json，便于 LLM 后续读取
- 所有路径计算经过 `Paths.sandbox_outputs_dir(thread_id)` + `Path.resolve()` 防越权

### 工具组装链路

```
$ python -c "from deerflow.tools.tools import BUILTIN_TOOLS; print(len(BUILTIN_TOOLS))"
18
```

18 个 BUILTIN_TOOLS：4 base + 6 lifecycle (Phase 3) + 8 runtime (Phase 4)，全部通过 `tools/builtins/__init__.py` 导出，进入 LLM 的工具列表。

---

## 4.6 builtin daily-equipment 模板

[agents/builtin/report-templates/daily-equipment/default.yaml](../../agents/builtin/report-templates/daily-equipment/default.yaml)

完整复刻设计 §5.2 的"重点机泵日报"流程：

- 3 个 form_steps：scope（日期/类型/对比基准）→ equipment（动态设备多选）→ kpis（动态 KPI 多选）
- 1 个 data_step：`data-analyst/query_daily`
- 1 个 transform：`data-analyst/daily_kpi`
- 6 个 sections：总览 / KPI 卡片 / 趋势图 / 异常排行 / 告警事件 / 处置建议
- export: `[md, pdf]`

**配套**：[metadata.yaml](../../agents/builtin/report-templates/daily-equipment/metadata.yaml)

### CI 校验

[backend/tests/test_builtin_report_templates.py](../../backend/tests/test_builtin_report_templates.py)

- 参数化测试每个 `agents/builtin/report-templates/*/default.yaml`
- 自动从 `skills/**/report_scripts.yaml` 加载真实 registry
- daily-equipment **valid: True, errors: 0, warnings: 0**
- 强制确保 daily-equipment 不被误删（regression guard）

---

## 4.7 ai-report--daily 双轨

[agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) 顶部新增章节：

```text
## DSL 优先 + Fallback 双轨

### 启动决策（每次新会话开始时执行一次）

1. 调用 report_template_get(template_id="builtin-daily-equipment")
   - 命中 → DSL 路径：依次 prepare_run / render_step / submit_step / ... / export
   - 未命中 / 抛错 → Fallback 路径，提示"正在使用兼容模式生成报告"

### Fallback 路径触发场景
...
```

旧 fallback 流程完整保留，**未删除任何业务代码**。

---

## 文件变更总结

```text
本次会话新增 9 个 production 文件：
  backend/packages/harness/deerflow/report_templates/runtime/__init__.py         (38 行)
  backend/packages/harness/deerflow/report_templates/runtime/state.py            (228 行)
  backend/packages/harness/deerflow/report_templates/runtime/data_runner.py      (367 行)
  backend/packages/harness/deerflow/report_templates/runtime/step_renderer.py    (181 行)
  backend/packages/harness/deerflow/report_templates/runtime/step_submitter.py   (90 行)
  backend/packages/harness/deerflow/report_templates/runtime/payload_builder.py  (172 行)
  backend/packages/harness/deerflow/report_templates/runtime/report_renderer.py  (61 行)
  backend/packages/harness/deerflow/report_templates/runtime/exporter.py         (135 行)
  backend/packages/harness/deerflow/tools/builtins/report_template_runtime_tools.py (535 行)

  agents/builtin/report-templates/daily-equipment/default.yaml                  (118 行)
  agents/builtin/report-templates/daily-equipment/metadata.yaml                 (16 行)

本次会话新增 2 个测试文件：
  backend/tests/test_report_template_runtime.py                                 (361 行, 21 用例)
  backend/tests/test_builtin_report_templates.py                                (65 行, 2 用例)

本次会话修改 4 个文件：
  backend/packages/harness/deerflow/tools/builtins/__init__.py
    导出 8 个 runtime 工具 + REPORT_TEMPLATE_RUNTIME_TOOLS
  backend/packages/harness/deerflow/tools/tools.py
    BUILTIN_TOOLS 注入 8 个 runtime 工具（共 18 个）
  backend/packages/harness/deerflow/report_templates/validator.py
    transforms.input 顶层字段自动映射到 args.input；type hints 包含 anomalies/alarms
  agents/builtin/ai-report--daily/SOUL.md
    顶部新增"DSL 优先 + Fallback"双轨章节
```

```text
累计 Phase 0+1+2+3+4 产出：
  Phase 0:  source_resolver / push_block / generic_renderer (604 行)
  Phase 1:  schema / script_registry / validator (970 行)
  Phase 2:  records / repository / permissions (1189 行)
  Phase 3:  service / lifecycle tools (609 行)
  Phase 4:  runtime/* + runtime tools (1807 行)
  ─────────
  合计 ~5179 行 production code

测试：
  source_resolver        43
  push_block              7
  generic_renderer       21
  schema                 27
  script_registry        15
  validator              28
  records                11
  permissions            18
  repository             31
  lifecycle_tools        22
  runtime                21
  builtin_templates       2
  ─────────
  Phase 0+1+2+3+4 合计  246 单元测试
  外加日报回归         121 测试无回归
  ─────────
  383 passed / 0 failed
```

---

## §17.2 MVP 验收 — 全部 17 项通过

| # | 验收项 | 状态 | 证据 |
| ---- | ---- | ---- | ---- |
| 1 | 自定义模板入口创建草稿 + 发布 v1 | ✅ | Phase 3 lifecycle 工具 |
| 2 | DSL 支持 form_steps / options_source / data_steps / transforms / sections / export | ✅ | Phase 1 schema + daily-equipment 实证 |
| 3 | 保存前 validator 结构化错误 | ✅ | Phase 1 + 3 |
| 4 | 模板存储位置正确 | ✅ | Phase 2 FileSystemReportTemplateRepository |
| 5 | 不新建独立 runner 进程 | ✅ | Phase 4 全部走 LLM 驱动的工具调用 |
| 6 | 动态流程复刻日报 | ✅ | daily-equipment + ai-report--daily 双轨 |
| 7 | (thread_id, callback_id) 复合 key | ✅ | Phase 0 验证（既有实现） |
| 8 | 脚本走 registry allowlist + 参数数组 | ✅ | Phase 4 data_runner.run_script |
| 9 | run-scoped 输出目录 | ✅ | `{thread_output_dir}/report-runs/{rr_id}/` |
| 10 | report_payload.json + Markdown + ReportRun | ✅ | Phase 4 assemble_payload + export + create_report_run |
| 11 | 非法输入结构化错误 | ✅ | 所有工具统一 `{"error": {code, message}}` |
| 12 | 完整权限矩阵 | ✅ | Phase 2 permissions.py |
| 13 | 强制版本迭代 | ✅ | Phase 2 publish 必带 expected_current_version |
| 14 | JSONPath 子集 + 深度 ≤8 | ✅ | Phase 0 source_resolver |
| 15 | ai-report--daily 双轨 | ✅ | SOUL.md 启动决策 + 旧 fallback 流程保留 |
| 16 | daily-equipment 通过 §13.14 | ✅ | builtin DSL CI 测试 |
| 17 | 既有日报/周报 GenUI 无回归 | ✅ | 121 个回归测试通过 |

---

## 关键设计决策再确认

| §0 决策 | Phase 4 实现 |
|---|---|
| Runtime LLM 驱动 | ✅ 8 个薄壳工具 + status.json 单一状态源；无后台 worker |
| status.json 是状态机唯一源 | ✅ `runtime/state.py` 实现读写 + 转换守卫，所有工具都通过它 |
| Markdown 必需 + PDF 可选 | ✅ exporter 用 try/except ImportError 优雅降级；ReportRun 字段 `pdf_skipped_reason` |
| run-scoped 输出 | ✅ `{run_output_dir}` 占位符严格 resolve；脚本不接受任意输出路径 |
| daily 双轨 | ✅ ai-report--daily SOUL.md 顶部 DSL-first 决策；旧流程保留 |
| 复用现有 InteractionStore | ✅ render_step 通过 callback_id `custom-report:{template}:{run}:{step}` 与既有 GenUI 链路接驳 |

---

## Phase 5 启动前置

可立即进入 **Phase 5：历史与管理 UI（2 人月）**。

Phase 5 任务清单：

1. **报告历史**：嵌入现有对话历史，按 ReportRun 索引
2. **历史详情页**：读 `report_payload.json` + `template_version.json` + artifact 重新渲染
3. **artifact 重下载**：复用现有 `/api/threads/{id}/artifacts/...` 路由（Phase 0 已验证）
4. **模板管理 UI**：列表/详情/YAML 编辑器/版本对比/fork
5. **租户共享模板管理**：tenant_admin 可发布 tenant 模板，普通成员可查看/运行/fork
6. **builtin 模板：weekly + monthly**（Phase 5 内增量交付两个）

### 现有能力可直接复用

- ReportRun 索引读取：`FileSystemReportTemplateRepository.list_report_runs` (Phase 2)
- 模板版本列表：`list_versions` (Phase 2)
- DSL 校验：`validate_dsl` (Phase 1) → 编辑器实时反馈
- 权限矩阵：`check_permission` (Phase 2) → 列表/详情筛选

Phase 5 主要是**前端工作 + Gateway REST API 包装**，harness 层的能力都已具备。

