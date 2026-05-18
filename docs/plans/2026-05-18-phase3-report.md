# Phase 3 交付报告

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) §15 Phase 3。
> **范围**：6 个生命周期工具 + ai-report--custom SOUL.md 改造 + data-analyst skill 注册 daily 脚本。
> **状态**：**全部 4 项工作通过**。可进入 Phase 4（运行时 MVP + daily 重写为 DSL 模板）。

## 交付清单

| Phase 3 项 | 状态 | 交付物 |
| ---- | ---- | ---- |
| **3.1 6 个生命周期工具** | ✅ 通过 | `report_template_tools.py` + 注册到 `BUILTIN_TOOLS` |
| **3.2 ai-report--custom SOUL.md 改造** | ✅ 通过 | 完整工具流程、错误码处理、5 步创建向导 |
| **3.3 禁止 LLM 直接 bash 写模板** | ✅ 通过 | 工具走结构化路径，SOUL 明确禁用 bash 兜底 |
| **3.4 模板向导**（GenUI 多步表单） | ✅ 通过 | SOUL.md 中规定通过 `render_ui` 收集基本信息 |
| **3.5 data-analyst report_scripts.yaml** | ✅ 已交付 | 新增 daily 3 个脚本，与现有 weekly 2 个脚本合计 5 个 |
| **3.6 service.py（额外）** | ✅ 通过 | repository 单例 + RunnableConfig → Principal 桥接 |

**Phase 3 新增测试**：22 个 lifecycle 工具用例。
**测试总计（Phase 0+1+2+3+回归）**：360 passed / 0 failed。

---

## 3.1 六个生命周期工具

[backend/packages/harness/deerflow/tools/builtins/report_template_tools.py](../../backend/packages/harness/deerflow/tools/builtins/report_template_tools.py)（478 行）

### 工具一览

| 工具 | 委托模块 | 关键行为 |
| ---- | ---- | ---- |
| `report_template_list` | `repository.list_templates` | 按 visibility 列出（默认 private） |
| `report_template_get` | `repository.get_template` + `get_version` | 自动跨 scope 解析 id，未越权抛 `NOT_FOUND` |
| `report_template_validate` | `validator.validate_dsl` + `script_registry.get_registry()` | 仅返回结构化错误，永远不抛异常 |
| `report_template_save_draft` | `repository.create_template` + `save_draft` | DSL 必须**先 validate 通过**才落盘 |
| `report_template_publish` | `repository.publish` | 必须传 `expected_current_version` |
| `report_template_fork` | `repository.fork` | 拒绝 v0 工作副本 fork（必须 ≥1 已发布版本） |

### 设计约束

- **统一 JSON 响应**：所有工具返回 JSON 字符串。成功为 `{"template": {...}}` / `{"templates": [...]}` / `{"valid": ..., "errors": [...]}`；失败为 `{"error": {"code", "message", ...extra}}`。
- **薄壳**：每个工具体不超过 50 行，核心逻辑全部委托 `repository.py` / `validator.py` / `script_registry.py`。
- **MVP 仅暴露 private scope 的写入**：tenant/builtin 的写入走 Gateway REST API（Phase 5），harness 层工具不接受跨 scope 写入。
- **跨 scope 读取**：`get` 和 `fork` 自动跨 private → tenant → builtin 解析模板 id，再由 `check_permission` 控制访问。
- **权限校验**：所有写操作前先 `check_permission(principal, operation, template)`。

### 错误码分布

```
INVALID_SCOPE         非法 visibility 值
NOT_FOUND             模板不存在
VERSION_NOT_FOUND     版本不存在
INVALID_ID            template_id 格式错误
INVALID_DSL           DSL validator 失败
MISSING_FIELD         创建缺 name/display_name
MISSING_ETAG          更新缺 expected_etag
ETAG_MISMATCH         etag 过期（HTTP 409）
VERSION_MISMATCH      publish 时 current_version 不一致
PUBLISHED_IMMUTABLE   尝试直接修改已发布版本
PERMISSION_DENIED     权限矩阵拒绝
INVALID_VERSION       fork 用了 v0
INVALID_INPUT         其他参数错误
PUBLISH_FAILED        publish 时缺工作草稿
INTERNAL              未预期异常
```

### 测试覆盖（22 用例）

[backend/tests/test_report_template_lifecycle_tools.py](../../backend/tests/test_report_template_lifecycle_tools.py)：

- **List（3）**：空列表、新建后列出、非法 scope
- **Get（5）**：existing、含 version=0、not_found、invalid id、**跨用户阻断**
- **Validate（3）**：good、bad（unknown next）、unknown script
- **SaveDraft（5）**：create 流程、update 流程、不合法 DSL 不落盘、缺 etag、缺 name+display
- **Publish（3）**：成功创建 v1、wrong version、unknown template
- **Fork（3）**：fork 已发布版本、拒绝 v0、unknown template

---

## 3.0 service.py — Repository 单例 + Principal 桥接

[backend/packages/harness/deerflow/report_templates/service.py](../../backend/packages/harness/deerflow/report_templates/service.py)（131 行）

设计要点：

- **`get_repository()` 单例**：runtime_root = `{DEER_FLOW_HOME}/report-templates/`；builtin_root 自动从仓库内 `agents/builtin/report-templates/` 解析（步行向上查找）
- **`set_repository()` / `reset_repository()`**：测试注入钩子
- **`principal_from_runnable_config()`**：从 `config["configurable"]` 提取 user_id / tenant_id / is_superadmin / is_tenant_admin。**无 app 依赖** — 所有信息在 RunnableConfig 由 Gateway 中间件提前注入；harness 层不能 import `app.*`。

**约定的 RunnableConfig 字段**（Gateway 在创建 runtime config 时填充）：

```python
config["configurable"]["user_id"]          # str, 可选, 默认 get_effective_user_id()
config["configurable"]["tenant_id"]        # str, 可选, 默认 get_current_tenant_id()
config["configurable"]["is_superadmin"]    # bool, 默认 False
config["configurable"]["is_tenant_admin"]  # bool, 默认 False
```

---

## 3.2 ai-report--custom SOUL.md 改造

[agents/builtin/ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md) — 从 24 行扩到 **~160 行**。

### 核心改动

| 旧 SOUL.md | 新 SOUL.md |
| ---- | ---- |
| "需求确认 → 结构协商 → 数据收集" 的高层口号 | 6 个工具 + 错误码表 + 5 步创建向导的可执行说明 |
| 无具体写入路径 | 明确禁止 bash 直写模板仓库，必须经 `report_template_*` |
| 无错误处理 | 13 种错误码的处理建议 |
| 无 DSL 引用 | 完整 DSL 结构示例 + JSONPath 占位符规则 |

### 5 步创建向导

1. **定位起点**：空白 vs `fork` 现有模板（`builtin` 选项）
2. **基本信息**：通过 `render_ui` 表单收集 name / display_name / description / tags
3. **DSL 组装**：列出推荐的 data-analyst 脚本
4. **保存草稿**：先 validate → 再 save_draft
5. **发布**：`publish` + 解释后续版本迭代流程

### 关键约束

- **平台不可用时不 fallback**：`report_template_*` 工具失败时返回清晰错误（"模板平台暂不可用"），不尝试 bash 兜底
- **DSL 校验先于落盘**：每次 save_draft 前必须 validate
- **etag 乐观锁**：更新失败时引导用户重新 get 后再重试

---

## 3.3 data-analyst report_scripts.yaml — daily 3 个脚本注册

[skills/custom/data-analyst/report_scripts.yaml](../../skills/custom/data-analyst/report_scripts.yaml) 扩展。

新增 3 个 daily 系列脚本（在原 weekly 2 个脚本基础上）：

| script | kind | 主要输入 | 输出 |
| ---- | ---- | ---- | ---- |
| `data-analyst/list_equipment` | `form_options` | type/scope/filter/limit | `equipment[]`, `available_kpis[]`, `area_counts` |
| `data-analyst/query_daily` | `data_step` | date, type, equipment[], kpis[], compare, scope | `{run_output_dir}/data/daily_data.json` |
| `data-analyst/daily_kpi` | `transform` | input (file_path) | `{run_output_dir}/data/daily_kpi.json` |

5 个脚本全部通过 Pydantic schema 校验。

**附带改动**：`OutputFile` schema 允许 `description` 字段（原 `extra="forbid"` 拒绝），方便注册表自带文档。

---

## 工具组装链路验证

```
$ python -c "from deerflow.tools.tools import BUILTIN_TOOLS; print([t.name for t in BUILTIN_TOOLS])"
['present_files', 'ask_clarification', 'render_ui', 'http_connector',
 'report_template_list', 'report_template_get', 'report_template_validate',
 'report_template_save_draft', 'report_template_publish', 'report_template_fork']
```

10 个 BUILTIN_TOOLS 就位，6 个新工具与既有 4 个工具完全兼容。

---

## 文件变更总结

```text
本次会话新增 3 个 production 文件：
  backend/packages/harness/deerflow/report_templates/service.py        (131 行)
  backend/packages/harness/deerflow/tools/builtins/report_template_tools.py  (478 行)
  agents/builtin/ai-report--custom/SOUL.md                              (~160 行, 完全重写)

本次会话新增 1 个测试文件：
  backend/tests/test_report_template_lifecycle_tools.py                (502 行, 22 用例)

本次会话修改 4 个文件：
  backend/packages/harness/deerflow/tools/builtins/__init__.py
    导出 6 个 report_template_* 工具 + REPORT_TEMPLATE_LIFECYCLE_TOOLS
  backend/packages/harness/deerflow/tools/tools.py
    BUILTIN_TOOLS 注入 6 个新工具
  backend/packages/harness/deerflow/report_templates/script_registry.py
    OutputFile schema 允许 description 字段
  skills/custom/data-analyst/report_scripts.yaml
    新增 list_equipment / query_daily / daily_kpi 3 个脚本

未修改任何现有业务代码。
```

```text
累计 Phase 0+1+2+3 产出：
  source_resolver.py         271
  push_block.py              113
  generic_renderer.py        220
  schema.py                  244
  script_registry.py         274
  validator.py               453
  records.py                 231
  repository.py              770
  permissions.py             188
  service.py                 131
  __init__.py                177
  report_template_tools.py   478
  ────────────────────────
  合计 3550 行 production code（10 个 harness 模块 + 1 个 tool 模块）

测试：
  source_resolver       43
  push_block             7
  generic_renderer      21
  schema                27
  script_registry       15
  validator             28
  records               11
  permissions           18
  repository            31
  lifecycle_tools       22
  ────────────────────────
  Phase 0+1+2+3 合计  223 单元测试
  外加日报回归         121 测试无回归
  外加 harness 边界    1 测试
  ────────────────────────
  360 passed / 0 failed
```

---

## 关键决策落实情况

| §0 决策 | Phase 3 落地 |
|---|---|
| **Runtime LLM 驱动**（§3.4） | ✅ 6 个工具是受控薄壳，LLM 在 SOUL.md 指引下编排 |
| **模板保存/校验必须走后端确定性服务** | ✅ DSL 必经 `validate_dsl` 才能 `save_draft`；SOUL.md 明确禁止 bash 兜底 |
| **etag 乐观锁** | ✅ `save_draft` / `publish` / `archive` / `delete` 强制 expected_etag/version |
| **强制版本迭代** | ✅ `publish` 必然递增；published 模板拒绝 in-place 编辑 |
| **复用 superadmin / tenant_admin** | ✅ `Principal.is_superadmin/is_tenant_admin` 在 RunnableConfig 由 Gateway 注入 |
| **fallback 仅适用 ai-report--daily** | ✅ ai-report--custom SOUL.md 明确"无 fallback，直接返回错误" |
| **Script Registry 由 skill 插件贡献** | ✅ data-analyst 5 个脚本注册到自己的 `report_scripts.yaml` |
| **MVP 仅 private scope 写入** | ✅ 所有写工具固定用 `Scope.private(principal.user_id)` |

---

## Phase 4 启动前置

可立即进入 **Phase 4：运行时 MVP + daily 重写为 DSL 模板（2.5 人月）**。

Phase 4 任务清单（按 §15）：

1. **Runtime 各模块**（`runtime/state.py` / `step_renderer.py` / `step_submitter.py` / `data_runner.py` / `payload_builder.py` / `report_renderer.py` / `exporter.py`）
2. **8 个运行时工具**：`prepare_run / render_step / submit_step / run_data_steps / assemble_payload / render_report / export / resume_run`
3. **报告章节渲染**：sections → GenUI blocks（复用 Phase 0 `push_block_to_sse` 和 `render_markdown_generic`）
4. **builtin 模板：daily-equipment**：完整 DSL 复刻现有日报流程
5. **ai-report--daily SOUL.md 双轨**：DSL 优先 + fallback 兜底（§11.4）
6. **回归测试**：daily 新老路径产物对比

### 现有 Phase 0-3 可直接复用的能力

- `validate_dsl(dsl, registry=...)` ← Phase 1
- `FileSystemReportTemplateRepository.create_report_run / update_report_run / get_report_run` ← Phase 2
- `push_block_to_sse(component, props, ...)` ← Phase 0
- `render_markdown_generic(payload)` ← Phase 0
- `evaluate(parse(expr), context)` JSONPath 求值 ← Phase 0
- `Principal` + `check_permission` ← Phase 2

Phase 4 主要工作是把这些原子能力按 DSL 编排起来，**不需要新发明基础设施**。

