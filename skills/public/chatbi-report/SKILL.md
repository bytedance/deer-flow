---
name: chatbi-report
version: 0.3.0
description: |
  Generate structured JSON, backfilled Markdown, and DOCX from a Markdown
  报表样张 whose HTML th cells carry data-idx indicators, `{{虚拟名}}`
  computed columns, or `> 描述:` narrative prompts. Use this skill whenever
  the user asks to generate/run/fill a chatbi report sample, render a data-idx
  template, produce a DOCX report, or review intermediate SQLBot/compute/
  description checkpoints. Do NOT use for free-form tables without data-idx or
  computed placeholders, pure Excel/statistical analysis, audio/video, or files
  that only need ordinary reading.
---

# chatbi-report Skill

Generate a structured report from a Markdown sample: lint and parse the template,
query SQLBot data, assemble a wide table, generate and validate computed columns,
optionally generate descriptions, then render `report.md` / `report.docx`.

This skill supports two execution modes:

- **Phase 1 → Phase 2（默认）**：先 `pipeline phase1`，再 `pipeline phase2`。checkpoint 通过 JSON 信号触发，agent 用 `--skip-*` 参数继续。
- **Step-by-step**：每步独立 bash CLI，有 3 个 checkpoint 交互点（lint / query / description）

## Trigger rules

Load this skill when the user asks to generate, run, fill, or render a chatbi
report from a Markdown sample, especially when the file contains any of:

- `<th data-idx="...">`
- `{{虚拟名}}` or legacy `{{BAS_xxx}}`
- `> 计算:`
- `> 描述:`

Common phrases:

- `生成报表`, `生成 chatbi 报表`, `跑样张`, `回填模板`, `出 docx`, `跑一下这个 md`
- `render report`, `fill template`, `generate chatbi report`

Do not trigger for:

- free-form Markdown tables with no `data-idx` and no computed placeholders
- pure statistics or spreadsheet analysis, use data-analysis instead
- ordinary file reading or summary where no report generation is requested
- changing the skill itself, unless the user explicitly asks to edit this skill

## Mode selection

| User request | Mode to use |
|---|---|
| 默认场景（无特殊说明） | `pipeline phase1` → `pipeline phase2` |
| 用户明确说"安保模式"、"checkpoint 模式"、"一步步跑" | `step-by-step` |
| 用户只说"检查一下样张" / "lint 一下" | `lint-only`（见下） |
| 用户说"不要 docx" | `pipeline phase2 --skip-docx` |

## Sandbox paths

| Type | Path |
|---|---|
| user upload | `/mnt/user-data/uploads/<file>.md` |
| intermediate JSON | `/mnt/user-data/outputs/<stem>.{parsed,query,wide,ir}.json` |
| run ledger | `/mnt/user-data/outputs/<stem>.runlog.md` |
| compute source/result | `/mnt/user-data/outputs/<stem>.compute.<slug>.py`, `/mnt/user-data/outputs/<stem>.computed.<slug>.json` |
| description text | `/mnt/user-data/outputs/<stem>.description.report-<idx>.txt` |
| final report | `/mnt/user-data/outputs/<stem>.report.md`, `/mnt/user-data/outputs/<stem>.report.docx` |
| final status | `/mnt/user-data/outputs/<stem>.status.json` |
| scripts | `/mnt/skills/public/chatbi-report/scripts/*.py` |
| prompts | `/mnt/skills/public/chatbi-report/prompts/{compute_codegen.md,description_gen.md}` |
| references | `/mnt/skills/public/chatbi-report/references/*.md` |

Use these absolute sandbox paths when running the skill. Do not assume the current
working directory is the skill directory.

## Reference loading

Read only the reference needed for the current decision:

| Need | Read |
|---|---|
| exact pipeline steps, commands, retries, progress messages | `references/pipeline.md` |
| checkpoint questions/options/branches for 1.5, 3.5, 8d.5 | `references/checkpoints.md` |
| final reply, status schema, runlog, sentinel handling, metric sources | `references/status-output.md` |
| template format, SQLBot modes, troubleshooting, user fix guidance | `references/template-troubleshooting.md` |

For a normal full run, read `pipeline.md`, `checkpoints.md`, and
`status-output.md` before Step 1. Read `template-troubleshooting.md` when lint,
parse, SQLBot, compute, description, or DOCX issues need explanation.

---

## Mode A: Phase 1 → Phase 2（默认）

Run the full pipeline via `pipeline phase1` → `pipeline phase2`.
When lint or query issues occur, `phase1` returns a checkpoint signal JSON
(`{"kind": "checkpoint", ...}`); the agent re-invokes with `--skip-lint-checkpoint`
or `--skip-query-checkpoint` after the user picks "继续".

```bash
# Phase 1: lint → parse → query → assemble-wide → extract-ir
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  phase1 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock                    # use built-in profit_yoy.json fixture (same as --mock-fixture example/mock_sqlbot/profit_yoy.json)

# Or specify custom fixture path explicitly
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  phase1 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock-fixture /path/to/fixture.json

# Phase 2: validate → evaluate → apply-computed → describe → render
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  phase2 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --compute-source COL_NAME=/mnt/user-data/outputs/<stem>.compute.<slug>.py \
  --descriptions-dir /mnt/user-data/outputs

# Skip DOCX rendering
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  phase2 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --compute-source COL_NAME=/mnt/user-data/outputs/<stem>.compute.<slug>.py \
  --descriptions-dir /mnt/user-data/outputs \
  --skip-docx
```

For mock mode, use `--mock` (uses built-in `example/mock_sqlbot/profit_yoy.json`) or `--mock-fixture /path/to/fixture.json`.
For real SQLBot, set env vars and the `RealSQLBotClient` is used implicitly.

**Wire format（stdout last line, JSON）:**

`phase1` returns:
```json
{"kind": "phase1_result", "result": {"parsed": "...", "wide": "...", "ir": "...", "metrics": {...}}}
```
or a checkpoint signal:
```json
{"kind": "checkpoint", "step": "1.5", "message": "lint 发现 N 错误", "metrics": {...}}
```

`phase2` returns:
```json
{"kind": "phase2_result", "result": {"report_md": "...", "report_docx": "...", "status_json": "...", "metrics": {...}}}
```

On any error the script prints `FAIL: <exc>` to stderr and exits 1.

---

## Mode B: Step-by-step（checkpoint 模式）

Run each step as an independent bash CLI. Three user checkpoints require
`ask_clarification` before proceeding.

### Pipeline quick view

```text
1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide → 6 extract-ir
→ 7 codegen (agent LLM writes compute source files)
→ 8a validate → 8b evaluate → 8c apply-computed
→ 8d describe (agent LLM writes description text files) → 8d.5 description checkpoint
→ 9 render/status
```

Step 5（unit-convert）已移除 — `unit_conversion.py` 是库（`convert_unit()` + `SCALE_FACTOR`），
单位换算内联到 Step 4 `assemble-wide` 和 `<th data-idx>` 的 `unit` 字段。

### Step commands

| Step | Command |
|---|---|
| 1–6 Phase 1 | `python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase1 --md <file>.md --out-dir /mnt/user-data/outputs` |
| 8a–9 Phase 2 | `python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase2 --md <file>.md --out-dir /mnt/user-data/outputs --compute-source COL=/path/to/compute.py --descriptions-dir /mnt/user-data/outputs` |
| lint only | `python /mnt/skills/public/chatbi-report/scripts/md_lint.py /mnt/user-data/uploads/<file>.md` |

### Step 7 & 8d: Agent LLM turns (handled by agent, not pipeline.py)

**Step 7 codegen** — agent reads `prompts/compute_codegen.md` + `<stem>.ir.json`，用 LLM 生成 Python 代码，写到 `<stem>.compute.<slug>.py`，然后传给 Phase 2 的 `--compute-source` 参数。

**Step 8d describe** — agent reads `prompts/description_gen.md` + `<stem>.wide.json`，用 LLM 生成描述文本，写到 `<stem>.description.report-<idx>.txt`，然后 Phase 2 通过 `--descriptions-dir` 读取。

### Checkpoints

- **Step 1.5**：lint 有错误或警告时触发，选项：`["继续", "停下（我去修样张）"]`
- **Step 3.5**：查询完成后始终触发（fail-fast 已禁用），选项：`["继续", "停下（数据需复核）"]`
- **Step 8d.5**：描述生成完成后有失败时触发，选项：`["满意，继续", "不满意，停下修改描述提示词"]`

详情见 `references/checkpoints.md`。

---

## Lint-only mode

Run only Step 1 lint. If lint has errors or warnings, present the Step 1.5 checkpoint.

```bash
python /mnt/skills/public/chatbi-report/scripts/md_lint.py /mnt/user-data/uploads/<file>.md
```

---

## Output rules

User-facing outputs are Chinese progress messages, checkpoint summaries, final
Chinese status summary, `report.md`, and `report.docx`.

- Echo generated `report.md` content in chat when short; summarize and share the
  file when long.
- Share `report.md` and `report.docx` with the user.
- Do not paste raw `status.json`.
- Do not force `status.json` or `runlog.md` paths into the final user reply.
- Mention internal paths only when troubleshooting or when the user asks.

## Error handling

**pipeline phase1/phase2 模式**：任何 step 抛异常，脚本打印 `FAIL: <exc>` 到 stderr 并退出 1。Agent 必须将错误格式化输出给用户，不得尝试修复。

**step-by-step 模式**：每个 bash step 返回非零 exit code 时，agent 必须：
1. 停止后续步骤
2. 将该 step 的 stderr / 错误输出直接呈现给用户
3. 不得生成代码修改任何文件来修复错误

### 严厉禁止的行为

- **生成代码自动修复**：当 lint 报错、compute 失败、SQLBot 查询失败时，禁止 agent 生成 Python/bash 代码尝试"修好"模板或重新跑该步骤
- **修改用户上传的模板**：`/mnt/user-data/uploads/<file>.md` 不可写
- **修改 skill 自身脚本**：`/mnt/skills/public/chatbi-report/scripts/*` 不可写
- **静默忽略错误**：不得在用户不知情的情况下跳过失败步骤继续跑

### 正确做法 vs 错误做法

| 场景 | 正确做法 | 错误做法（禁止） |
|---|---|---|
| lint 有 3 个错误 | 停止，输出 `md_lint.py` 的错误列表，告诉用户去修模板 | 生成代码修模板然后重跑 |
| SQLBot query 失败 | 停止，输出 query 错误，告诉用户检查 SQLBot | 生成代码重试或换 endpoint |
| compute validate 失败 | 停止，输出 stderr，告诉用户检查生成的代码 | 直接修改 `<stem>.compute.<slug>.py` 然后重跑 |
| parse 报错 | 停止，输出 parse 错误，告诉用户检查 MD 结构 | 生成代码修 MD 语法然后重跑 |

### 错误输出格式

遇到 `FAIL: <exc>` 错误时，agent 必须输出：

```
[Step X 错误]
错误信息：<exc 的内容>
建议操作：<用户需要做什么来修复>

请修复后重新运行。
```

## Safety and scope

During a report run, only write `/mnt/user-data/outputs/<stem>.*`.

Do not modify these unless the user explicitly asks to edit the skill or template:

- `/mnt/skills/public/chatbi-report/SKILL.md`
- `/mnt/skills/public/chatbi-report/scripts/*`
- `/mnt/skills/public/chatbi-report/prompts/*`
- `/mnt/user-data/uploads/<file>.md`

Do not add analysis dimensions, columns, or business interpretation unless the
user asks. Preserve sentinels `⚠️QUERY_FAILED`, `⚠️COMPUTE_FAILED`, and
`⚠️DESCRIPTION_FAILED` so partial output remains auditable.
