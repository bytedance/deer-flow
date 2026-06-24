---
name: chatbi-report
identifier: chatbi-report
version: 0.1.0
description: |
  Generate structured JSON, backfilled Markdown, and DOCX from a Markdown
  报表样张：`<th>` cells carry `data-idx` (SQLBot indicator id) + Chinese
  display name；computed columns carry `data-compute` Python source.
  Auto-fills cells, applies unit conversion, runs LLM-generated compute
  per spec, then renders to `.md` / `.docx` / `.status.json`.

  Triggers: "生成报表 / 生成 chatbi 报表 / 跑一下样张 / 回填 data-idx
  样张 / 出一份 docx 报表"; "render chatbi report", "fill data-idx
  template".

  Do NOT use for: 自由文本表格（没有 `data-idx` 属性）、纯统计分析
  (use data-analysis)、旧式 `{{BAS_xxx}}` 占位符样张（已下线）。
---

# chatbi-report Skill

从带 `data-idx` 属性的 Markdown 样张生成结构化 JSON、回填 MD 和 DOCX。

## 触发匹配规则（Agent 加载后必读）

> 本节是**给 LLM 的执行指令**，不是给人类阅读的。

**Step 1 — 匹配判断**：用户消息含以下任一条件时加载本 Skill：
- 给出一份 `.md` 文件且文件含 `<th data-idx="..."` 或 `<th ... data-compute="...">`
- 含动词："生成报表 / 跑样张 / 回填模板 / 出 docx / 生成 chatbi"
- 含英文："render report", "fill template", "generate chatbi report"

**反例（不要触发本 skill）**：
- 自由文本表格 / Markdown 不含 `data-idx` 属性 → 改用 data-analysis 或直接回复
- 旧式 `{{BAS_xxx}}` 文本占位符样张 → 已下线，告知用户改用新模板
- 纯统计分析（pivot/groupby Excel）→ 改用 data-analysis

**Step 2 — 复杂度模式**：

| Mode | 触发 | 执行 |
|------|------|------|
| **lint-only** | "检查 / 校验 / lint 一下样张" | 仅 step 1（`md_lint.py`），输出 LintReport，结束 |
| **full** | "生成 / 跑 / 回填"（默认） | 完整 9 步流水线 |
| **skip-docx** | "只要 JSON / 不要 docx" | 1–8 步 + step 9 仅 `render_markdown.py` + `assemble_status.py` |

**Step 3 — 绝不主动扩大范围**：不主动给数据解读、不主动改样张结构、不主动加列。

## 9 步工作流契约

每一步的命令与产物固定如下。步骤 1–6 与 8a/8b/9 全部是 **bash CLI 子进程**（沙箱中不可达 LLM）。**只有 step 7 是 agent-turn LLM step**。

| Step | 类型 | 命令 / 责任方 | 产物 |
|---|---|---|---|
| 1. lint | bash | `python scripts/md_lint.py <upload.md>` | exit code + LintReport |
| 2. parse | bash | `python scripts/parse_md.py <upload.md> --out report.parsed.json` | `report.parsed.json` |
| 3. query | bash | `python scripts/sqlbot_client.py query --idx-ids ... --out report.query.json` | `report.query.json` |
| 4. assemble wide | bash | `python scripts/compute.py assemble-wide --query report.query.json --parsed report.parsed.json --out report.wide.json` | `report.wide.json` |
| 5. unit convert | bash | `python scripts/unit_conversion.py --in report.wide.json --out report.wide.json` | wide 内 cells 转 Decimal 字符串 |
| 6. extract IR | bash | `python scripts/compute.py extract-ir --parsed report.parsed.json --out report.ir.json` | `report.ir.json`（**静态，零 LLM**） |
| **7. codegen** | **agent-turn** | **lead agent 调 LLM**（读 `prompts/compute_codegen.md` + `report.ir.json`，逐 spec 生成函数源码，**用 `write_file` 工具落盘**） | `report.compute.<slug>.py` × N |
| **8a. validate** | bash | `python scripts/compute.py validate --source ... --function ... --df ... --example-input ... --example-expected ...` | exit 0/1 |
| **8b. evaluate** | bash | `python scripts/compute.py evaluate --source ... --function ... --df ... --out report.computed.<slug>.json` | `report.computed.<slug>.json` × N |
| 9. render + status | bash | `python scripts/render_markdown.py ...` + `python scripts/render_docx.py ...` + `python scripts/assemble_status.py ...` | `report.{md,docx,status.json}` |

## 关键不变量

- **Step 7 是唯一的 agent-turn LLM step**。step 1–6 与 8a/8b/9 全部是 bash CLI 子进程，**沙箱中不可达 LLM**。
- **Step 7 失败重试在 agent-turn 内做**：agent 读 step 8a 的 stderr，决定要不要再调一次 LLM 生成新版源码。bash 脚本不参与重试调度。**最多重试 1 次**；再失败则该 spec 标记 `⚠️COMPUTE_FAILED` 进入 step 9。
- **Step 3 query 失败**：单元格保留 `⚠️QUERY_FAILED` 标记，流水线继续。
- **`data-idx` 是唯一指标锚点**：不要从 `idx_name` 或正文文案反推。中文显示名从 `<th>` 文本读取，**不调 SQLBot**。

## 退出 status

完成（或中断）时，`assemble_status.py` 写出 `report.status.json`：

```json
{
  "status": "success | partial | error",
  "exit_step": 1-9,
  "error_class": null | "F1..F20",
  "error_detail": "...",
  "outputs": {"json": "...", "docx": "...", "md": "..."},
  "metrics": {
    "queried_count": 0, "query_failures": 0,
    "computed_count": 0, "compute_validation_failures": 0,
    "llm_calls": 0, "duration_seconds": 0.0
  }
}
```

- `success`：`error_class` 为 None 且无查询/计算失败
- `partial`：`error_class` 为 None 但 `query_failures > 0` 或 `compute_validation_failures > 0`
- `error`：`error_class` 设置（F1..F20）
