# Phase 0 最终交付报告

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) Phase 0 共 6 项验证。
> **会话覆盖**：第一会话交付 0.2 / 0.3 / 0.6；本次会话交付 0.1 / 0.4 / 0.5。
> **状态**：**全部 6 项通过**。可进入 Phase 1。

## 交付清单

| Phase 0 项 | 状态 | 交付物 |
| ---- | ---- | ---- |
| **0.1 render_ui 程序化推送验证** | ✅ 通过 | `report_templates/push_block.py` + 7 个测试 |
| **0.2 InteractionStore 代码对账** | ✅ 通过 | 见首份报告，结论"基线已与设计一致" |
| **0.3 JSONPath 子集解析器原型** | ✅ 通过 | `report_templates/source_resolver.py` + 43 个测试 |
| **0.4 run-scoped 输出 + artifact 下载链路** | ✅ 通过 | 见下文"链路核查"，无需任何代码改动 |
| **0.5 export_report.py generic 路径验证** | ✅ 通过 | `report_templates/generic_renderer.py` + 21 个测试 |
| **0.6 父子 agent 配置就位** | ✅ 通过 | 见首份报告 |

**测试总计**：72 passed（含 1 个 harness 边界回归）。

---

## 0.1 render_ui 程序化推送验证

### 验证结论

LangGraph 提供的 `get_stream_writer()` + `get_config()` 是**通用 SSE 推送机制**，`render_ui_tool` 也是这套机制的消费者。报告模板运行时只要在同一 `RunnableConfig` 上下文中拿到 writer，就能把 `ui_block` 事件推到当前 thread 的 SSE 流，**无需任何 LangGraph 或 Gateway 层改造**。

### 交付的可复用 helper

[backend/packages/harness/deerflow/report_templates/push_block.py](../../backend/packages/harness/deerflow/report_templates/push_block.py)

提供 `push_block_to_sse(component, props, *, block_id, parent_id, sequence)`：

- 仅允许**非交互**组件（`markdown / table / echart / chart / card / code / timeline / image / layout`）—— 交互表单仍走 `render_ui_tool`（`GenUIInterruptMiddleware` 需要拦截）。
- 内部依次：取 `thread_id` → `get_stream_writer()` → 推 `ui_block` 事件 → `persist_block(thread_id, block)` → 推 `ui_blocks_folded` 快照事件。
- 失败明确抛 `PushBlockError`，三类错误：未知组件 / 没有 thread_id / 没有活跃 stream writer。

这是 Phase 4 中 `report_template_render_report` 工具的核心实现路径。

### 验证用例

`test_report_template_push_block.py`（7 用例）覆盖：

- 正常推 markdown block，验证 2 个 SSE 事件（`ui_block` + `ui_blocks_folded`）顺序与内容
- 自动生成 `block_id`
- table 组件接受
- 拒绝交互组件（`form` / `confirm`）
- 拒绝未知组件
- 缺 `thread_id` 时抛错
- 无活跃 stream writer 时抛错

---

## 0.4 run-scoped 输出目录 + artifact 下载链路

### 链路核查（无代码改动）

设计文档 §7.2 要求每次 ReportRun 写到 `{thread_output_dir}/report-runs/{report_run_id}/...`。验证现有 artifact 路由能下载到该路径下的文件：

1. **路由**：[backend/app/gateway/routers/artifacts.py:81](../../backend/app/gateway/routers/artifacts.py#L81) `GET /api/threads/{thread_id}/artifacts/{path:path}` —— 任意 `{path:path}`，无前缀白名单。
2. **解析**：[backend/app/gateway/path_utils.py:11](../../backend/app/gateway/path_utils.py#L11) `resolve_thread_virtual_path(thread_id, virtual_path)` 委托给：
3. **底层**：[backend/packages/harness/deerflow/config/paths.py:307](../../backend/packages/harness/deerflow/config/paths.py#L307) `Paths.resolve_virtual_path(thread_id, virtual_path, user_id)`，要求 `virtual_path` 以 `/mnt/user-data` 开头，剩余子路径任意；`Path.resolve()` + `relative_to(base)` 拦截 `../` 越权。

**结论**：URL `/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/report-runs/rr_xxx/exports/report.md` 在当前代码下**直接可用**，无需新增路由、白名单或前置校验。Phase 4 的 ReportRun 写出 `report.md` 后立即可下载。

### 安全约束的额外要求（设计 §7.1.4）

虽然路由层已防 `../`，Phase 4 实施时仍需在 runtime 入口处对 `report_run_id` / `template_id` / `user_id` / `tenant_id` 做正则校验后才拼路径——这条记入 Phase 4 工作项，**不在 Phase 0 范围**。

---

## 0.5 `render_markdown_generic` 最小 demo

### 交付物

[backend/packages/harness/deerflow/report_templates/generic_renderer.py](../../backend/packages/harness/deerflow/report_templates/generic_renderer.py)

`render_markdown_generic(payload: dict) -> str`：消费符合设计 §12.1 schema 的 `report_payload.json`，输出 Markdown 字符串。

支持的 section 组件：

| component | 输出形态 |
| ---- | ---- |
| `markdown` | 直接拼接（list 内容逐项换行） |
| `table` | 标准 Markdown 表格（接受 `{columns, data}` 或 `{rows}` 两种形态） |
| `card` | 单条 bullet：`**title**: value` + 描述 |
| `card_group` | 多条 bullet |
| `echart` | Phase 0 仅占位 `_[echart chart: line]_`；Phase 4 会改为内嵌 SVG |
| `image` | `![alt](src)` |

### 安全

所有用户字符串经 `html.escape(value, quote=False)`，防 `<script>...` 类直注。Markdown 元字符不剥离（作者意图保留）。

### 与现有 `export_report.py` 的关系

**不侵入**现有 [skills/custom/data-analyst/scripts/export_report.py](../../skills/custom/data-analyst/scripts/export_report.py)。Phase 4 决定二者关系：

- 方案 A（推荐）：generic_renderer 留在 harness 中，export_report.py 通过 `from deerflow.report_templates import render_markdown_generic` 调用，daily 路径继续走自己的 `render_markdown`，fallback 路径不动。
- 方案 B：把 generic_renderer 复制进 skill 脚本目录，让 skill 完全自包含。

Phase 4 启动前再决定。

### 验证用例

`test_report_template_generic_renderer.py`（21 用例）覆盖：

- schema 校验：拒绝非 dict、错误 schema_version、缺 sections、非 dict 的 section、未知 component
- markdown：字符串/list 两种 content、HTML 转义
- table：`{columns, data}` 形态、`{rows}` 短形态、空表、非法 row
- card / card_group：单条、多条
- echart：chart_type 占位、未知图表
- image：正常 / 缺 src
- 元数据：模板版本 + 生成时间渲染、缺失时跳过
- 完整 daily 报告形态：5 个 section 顺序正确、尾部换行

---

## 文件变更总结

```text
本次会话新增 4 个文件：
  backend/packages/harness/deerflow/report_templates/push_block.py        (113 行)
  backend/packages/harness/deerflow/report_templates/generic_renderer.py  (220 行)
  backend/tests/test_report_template_push_block.py                         (101 行)
  backend/tests/test_report_template_generic_renderer.py                   (236 行)

本次会话修改 1 个文件：
  backend/packages/harness/deerflow/report_templates/__init__.py
    (扩展 public API 至 14 项，含新的 generic_renderer 和 push_block 导出)

未修改任何现有业务代码。
```

```text
累计 Phase 0 交付（含首次会话）：
  source_resolver.py            (271 行)
  push_block.py                 (113 行)
  generic_renderer.py           (220 行)
  __init__.py                   (54 行)
  test_report_template_source_resolver.py    (234 行, 43 用例)
  test_report_template_push_block.py         (101 行, 7 用例)
  test_report_template_generic_renderer.py   (236 行, 21 用例)

测试：72 passed, 0 failed
边界：harness 不依赖 app.* 检查通过
```

---

## 风险评估调整

基于 Phase 0 实际执行结果，调整设计文档 §16 风险表中的几项严重度：

| 风险（设计 §16） | 原评估 | 调整后 | 依据 |
| ---- | ---- | ---- | ---- |
| render_ui 程序化推送路径不存在 | **高** | **低** | LangGraph `get_stream_writer()` + `get_config()` 是通用机制；helper 113 行就跑通 |
| InteractionStore 改造影响所有 GenUI 业务 | **高** | **低**（不存在改造） | 现有代码已完成复合 key，本立项无需重新发起改造 |
| JSONPath 表达式解析器实现复杂度被低估 | 中 | **低** | 182 行纯代码完成 + 43 用例全绿，无外部依赖 |
| run-scoped 输出绕过 artifact 路由 | 隐含中 | **无风险** | 现有 `resolve_virtual_path` 直接支持，无需新增路由 |
| `export_report.py` generic 路径复杂度 | 隐含中 | **低** | 220 行 + 21 用例完成原型；Phase 4 仅需要补 SVG 嵌入和 PDF 降级 |

Phase 1 工作量预估从 2 人月 → 可能落在 **1.5-1.75 人月**（去掉本以为需要做的 InteractionStore 改造）。建议在 Phase 1 启动前更新 §15 工程量。

---

## Phase 1 启动前置

可立即进入 Phase 1。Phase 1 任务清单（按 §15）：

1. **DSL Pydantic schema** (`schema.py`)
2. **JSONPath 子集解析器** — Phase 0 已完成，Phase 1 仅需在 validator 中调用 `parse()`
3. **DSL Validator** (`validator.py`) — 复用 0.3 解析器做 source 路径校验
4. **Script Registry** (`script_registry.py`) — 扫描 skill 的 `report_scripts.yaml`
5. ~~InteractionStore 改造~~ → 已自然消化（仅需补接入回归测试）
6. **回归测试**：现有 daily 流程

**预计 Phase 1 工期**：3 周（按 1 全职后端工程师），低于原 4 周估算。

---

## 决策点：是否进入 Phase 1

技术尖刺 6 项全部通过，无设计层面阻塞。可在下次会话或下一立项节点直接启动 Phase 1。

如需在进入 Phase 1 前再补充某项验证（例如真实集成测试跑通最小 daily 流程），可单独立项做"端到端 smoke test"——但**不阻塞** Phase 1 启动。

