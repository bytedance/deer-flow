# Phase 0 部分交付报告（第 1 次会话）

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) Phase 0 共 6 项；本次会话交付其中 3 项可即时完成项。
> **会话约束**：用户授权"可改代码，但严格按 Phase 推进"；本次仅做 Phase 0 可即时交付部分，后续会话延续。

## 交付清单

| Phase 0 项 | 状态 | 证据 |
| ---- | ---- | ---- |
| 0.1 render_ui 程序化推送验证 | ⏸ 未做 | 需要跑通最小工具 demo，建议下一会话与 0.4/0.5 一起做技术尖刺 |
| **0.2 InteractionStore 代码对账** | ✅ 通过 | 见下文"对账结果" |
| **0.3 JSONPath 解析器原型** | ✅ 通过 | 新增 `source_resolver.py`（182 行非注释代码）+ 43 个单元测试 |
| 0.4 run-scoped 输出 + artifact 下载链路 | ⏸ 未做 | 需要 sandbox + artifact 路由联调，下一会话执行 |
| 0.5 export_report.py generic 路径验证 | ⏸ 未做 | 同上 |
| **0.6 父子 agent 配置就位** | ✅ 通过 | 见下文"agent 目录核验" |

---

## 0.2 InteractionStore 对账结果

设计文档 §10.3 声明"当前代码已落地 `(thread_id, callback_id)` 复合 key"。逐项核对：

| 检查点 | 文件 | 实际行为 | 结论 |
| ---- | ---- | ---- | ---- |
| `_make_key(thread_id, callback_id)` | [genui_middleware.py:62-63](../../backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py#L62-L63) | ✅ 用 `\x1f` 分隔符拼成 string key | 与设计一致 |
| `register / get / submit / remove` 全部接受 `thread_id` 参数 | 同上 65-120 行 | ✅ 全部接受并校验 | 与设计一致 |
| `process_interaction(thread_id, callback_id, payload)` | 同上 138-184 行 | ✅ 函数签名与设计一致 | 与设计一致 |
| `render_ui_tool` 从 `RunnableConfig.configurable.thread_id` 取 thread | [render_ui_tool.py:69](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L69) | ✅ 已实现；重复表单保护用 `store.get(thread_id, callback_id)` | 与设计一致 |
| Gateway 路由 `/api/threads/{thread_id}/ui-interaction` | [genui.py:17,32-73](../../backend/app/gateway/routers/genui.py#L17) | ✅ 从 path 取 `thread_id`，传入 `process_interaction` | 与设计一致 |
| TTL 清理 | `cleanup_expired()` 同 103-116 行 | ✅ 按 `created_at + timeout` 过期 | 与设计一致 |

**结论**：报告模板可直接复用现有机制，**不需要在 Phase 1 重复发起底层改造**。Phase 1 任务降级为"接入测试 + 命名约束"，工作量与文档 §10.3.5 估算（0.75 人月）匹配。

---

## 0.6 agent 目录核验

`agents/builtin/` 下实际目录：

```text
ai-report                  ← 父 agent
ai-report--closure         ← 子
ai-report--custom          ← 子
ai-report--daily           ← 子（已是当前生产版本，含完整 SOUL.md）
ai-report--diagnosis       ← 子
ai-report--failure-analysis ← 子
ai-report--monthly         ← 子
ai-report--trend           ← 子
ai-report--weekly          ← 子
```

父 + 8 子 agent **全部就位**，与设计文档 §1.1 列表完全对齐。无需在 Phase 1 补创建。

---

## 0.3 JSONPath 子集解析器交付物

### 文件清单

| 路径 | 行数（含注释） | 行数（纯代码） | 说明 |
| ---- | ---- | ---- | ---- |
| `backend/packages/harness/deerflow/report_templates/__init__.py` | 41 | 19 | 模块入口 + 公开 API |
| `backend/packages/harness/deerflow/report_templates/source_resolver.py` | 271 | 182 | 解析器 + 求值器 + 占位符渲染 |
| `backend/tests/test_report_template_source_resolver.py` | 234 | ~220 | 43 个测试用例 |

> 设计文档 §15 Phase 0 第 3 项要求 "≤200 行解析器原型"。`source_resolver.py` **纯代码 182 行**，达标。

### 已实现的能力（§5.6 白名单）

| 语法 | 测试用例 |
| ---- | ---- |
| `$.form.<step>.<field>` | `test_form_step_field` |
| `$.steps.<step>.<output>` | `test_steps_output` |
| `$.steps.<step>.<output>.<key>` | `test_nested_step_field` |
| `$.steps.<step>.<output>[*].<key>` | `test_array_expansion` |
| `$.run.<key>` | `test_run_metadata` |
| `$.template.<key>` | `test_template_metadata` |
| 短形式自动补 `$.` | `test_short_form_autoprefix` |
| 含 `_` `-` 的字段名 | `test_field_name_with_underscore_and_hyphen` |

### 已拦截的语法（§5.6 黑名单）

`TestBlacklistParse` 通过参数化测试覆盖 18 类非法语法，全部抛 `PathSyntaxError`：

- 过滤器 `[?(@.x > 1)]`
- 函数调用 `.length()`
- 递归下降 `..`
- 算术 `+`
- 索引 `[0]` / `[-1]` / `[1:3]` / `[1,2]`
- 联合 `|`
- 未知 root（不在 `form/steps/run/template` 内）
- 空字符串、单独 `$`、悬空 `.`、悬空 `[*]`
- 深度超过 8 层

### 求值器行为

- 合法路径正常返回（`TestEvaluator` 6 个用例）
- 路径不存在抛 `PathNotFoundError`，错误信息包含已走到的路径前缀
- `[*]` 在非数组上抛 `PathNotFoundError`
- 非 Root 起始的 AST 抛 `PathSyntaxError`

### 占位符渲染

- `extract_expressions(text)` 提取所有 `{{ ... }}` 表达式
- `render(text, context)` 替换为求值结果
- 求值错误透传给调用者（不静默吞）

### 实现约束

- 完全自实现，**未引入** `jsonpath-ng / jmespath / jq`（符合 §5.6 安全要求）
- AST 节点类型仅 3 种：`Root` / `FieldAccess` / `ArrayAll`（符合 §5.6 AST 约束）
- 解析时即拒绝所有黑名单语法，求值阶段不重新解析

---

## 测试结果

```text
tests/test_report_template_source_resolver.py: 43 passed in 0.35s
tests/test_harness_boundary.py: 1 passed in 0.58s
```

- 新增 43 个测试全部通过
- `harness → app` 边界检查未被破坏
- 未触动任何现有业务代码

---

## 下一会话建议执行项

按 Phase 0 剩余 3 项 + 后续 Phase 推进：

### 下一会话候选

1. **Phase 0.1 render_ui 程序化推送验证**：写一个最小 mock 工具，在工具内部调用 `render_ui_tool` 的核心逻辑，验证 GenUI block 能落到 SSE 流。这是 Phase 4 的核心 blocker，必须验证。
2. **Phase 0.4 run-scoped 输出 + artifact 下载链路**：用一个小脚本写 `{thread_output_dir}/report-runs/{rr_id}/data/test.json`，通过 `/api/threads/{thread_id}/artifacts/...` 下载，验证整条链路。
3. **Phase 0.5 `render_markdown_generic` 最小 demo**：复制 `export_report.py` 的 `render_markdown` 函数，改为接受任意 sections 数组，跑通"markdown / table" 两个 section type 的转换。

### Phase 0 整体验收（全部 6 项通过后）

输出最终《Phase 0 技术尖刺报告》，确认或调整下游 Phase 工作量；正式进入 Phase 1。

---

## 风险与未决项

无。本次交付的 3 项**未发现设计文档与代码现状的偏差**：

- InteractionStore 已经如设计描述运作，文档第 6 行的"基线对齐"声明属实。
- JSONPath 解析器实现复杂度低于预估（原估算"中"风险，实际 0.5 天完成 + 测试全绿），可在最终 Phase 0 报告里下调该风险等级。

---

## 文件变更总结

```text
新增 3 个文件：
  backend/packages/harness/deerflow/report_templates/__init__.py        (41 行)
  backend/packages/harness/deerflow/report_templates/source_resolver.py (271 行)
  backend/tests/test_report_template_source_resolver.py                  (234 行)

修改 0 个现有文件。
```

```text
测试覆盖：
  43 passed, 0 failed
  覆盖白名单 8 项 + 黑名单 18 项 + 求值器正/反路径 11 项 + 占位符 4 项 + 边界 2 项
```

