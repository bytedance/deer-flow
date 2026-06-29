# chatbi-report Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user checkpoints after computed columns and generated descriptions, and clarify that `runlog.md` and `status.json` are internal artifacts rather than default user-facing outputs.

**Architecture:** Most behavior is orchestrated by the `chatbi-report` skill instructions, so the primary change is to `SKILL.md`. The script change is limited to `assemble_status.py`: preserve existing integer `exit_step` JSON values for steps like `2` and `9`, while accepting non-integer checkpoint identifiers such as `1.5`, `8c.5`, and `8d.5` as strings. Tests lock down both the new checkpoint ids and the existing integer-step compatibility.

**Tech Stack:** Python 3.12, pytest, Markdown skill instructions, existing `ask_clarification(..., clarification_type="risk_confirmation", ...)` checkpoint mechanism.

## Global Constraints

- Do not add Step 6.5 IR preview; compute review happens after Step 8c.
- Step 8c.5 triggers after `apply-computed` only when computed spec total is greater than 0; if total is 0, skip it silently.
- Step 8d.5 triggers whenever the template contains at least one `> 描述:` block.
- Step 8d.5 does not support in-run prompt editing or temporary prompt overrides.
- If the user stops at Step 8d.5, instruct them to modify the original template's `> 描述:` block and rerun.
- `runlog.md` is an internal run ledger / troubleshooting artifact, not a default user deliverable; if retained, its content should be Chinese-first.
- `status.json` is a machine-readable contract for Agent / orchestrator use; do not paste its JSON or force its path into user-facing final replies.
- Do not commit unless the user explicitly asks for a commit.

---

## File Structure

- Modify: `skills/public/chatbi-report/scripts/assemble_status.py`
  - Responsibility: write the structured `report.status.json` machine contract.
  - Required change: make `exit_step` support checkpoint ids like `8c.5` and `8d.5` without changing existing integer-step JSON output.

- Modify: `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`
  - Responsibility: unit tests for status schema and status decision logic.
  - Required change: cover `USER_ABORTED` at `8c.5` and `8d.5`, while preserving existing integer-step assertions for `2` and `9`.

- Modify: `skills/public/chatbi-report/SKILL.md`
  - Responsibility: executable skill contract for the lead agent.
  - Required change: add Step 8c.5 / 8d.5 checkpoint instructions; update output presentation, runlog/status responsibilities, status schema, final reply template, progress feedback, and number extraction rules.

- Test only: `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`
  - No new test file is required.

---

### Task 1: Make status exit steps checkpoint-safe

**Files:**
- Modify: `skills/public/chatbi-report/scripts/assemble_status.py:31-58`
- Modify: `skills/public/chatbi-report/scripts/tests/test_assemble_status.py:10-69`

**Interfaces:**
- Consumes: `write_status(out_path: str, *, exit_step, error_class: str | None, error_detail: str, outputs: dict[str, str | None], metrics: dict[str, Any]) -> None`
- Produces: `report.status.json` with existing integer steps serialized as JSON numbers, and non-integer step ids serialized as strings, preserving values like `9`, `2`, `"8c.5"`, and `"8d.5"`.

- [ ] **Step 1: Write failing tests for checkpoint exit steps**

Add these tests to `skills/public/chatbi-report/scripts/tests/test_assemble_status.py` after `test_write_status_error_when_error_class_set`:

```python
def test_write_status_user_aborted_at_compute_checkpoint(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step="8c.5",
        error_class="USER_ABORTED",
        error_detail="计算列处理完成：1/2 成功。请修改原始样张里的 `> 计算:` 块后重跑。",
        outputs={"json": None, "docx": None, "md": None},
        metrics={
            "queried_count": 4,
            "query_failures": 0,
            "computed_count": 1,
            "compute_validation_failures": 1,
            "descriptions_generated": 0,
            "description_failures": 0,
            "llm_calls": 2,
            "duration_seconds": 3.5,
        },
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["exit_step"] == "8c.5"
    assert data["error_class"] == "USER_ABORTED"
    assert "计算列处理完成" in data["error_detail"]
    assert data["metrics"]["compute_validation_failures"] == 1


def test_write_status_user_aborted_at_description_checkpoint(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step="8d.5",
        error_class="USER_ABORTED",
        error_detail="描述段落已生成：1/1 成功。请修改原始样张里的 `> 描述:` 块后重跑。",
        outputs={"json": None, "docx": None, "md": None},
        metrics={
            "queried_count": 4,
            "query_failures": 0,
            "computed_count": 2,
            "compute_validation_failures": 0,
            "descriptions_generated": 1,
            "description_failures": 0,
            "llm_calls": 3,
            "duration_seconds": 4.2,
        },
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["exit_step"] == "8d.5"
    assert data["error_class"] == "USER_ABORTED"
    assert "描述段落已生成" in data["error_detail"]
    assert data["metrics"]["descriptions_generated"] == 1
```

Keep existing assertions that expect integer exit steps unchanged:

```python
assert data["exit_step"] == 9
```

and:

```python
assert data["exit_step"] == 2
```

These assertions protect compatibility for existing consumers that treat whole-number steps as JSON numbers.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
rtk pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -q
```

Expected: FAIL because `write_status()` currently type-hints `exit_step: int`, serializes `int(exit_step)`, and cannot parse `"8c.5"`.

- [ ] **Step 3: Implement minimal status serialization change**

In `skills/public/chatbi-report/scripts/assemble_status.py`, add a small helper near `_decide_status`:

```python
def _serialize_exit_step(exit_step: str | int) -> str | int:
    text = str(exit_step)
    if text.isdigit():
        return int(text)
    return text
```

Then change `write_status` and CLI parsing to accept string checkpoint ids while preserving integer JSON values.

Replace the current `write_status` signature and payload `exit_step` line with:

```python
def write_status(
    out_path: str,
    *,
    exit_step: str | int,
    error_class: str | None,
    error_detail: str,
    outputs: dict[str, str | None],
    metrics: dict[str, Any],
) -> None:
    """以规格强制的形态持久化 report.status.json。"""
    payload = {
        "status": _decide_status(error_class, metrics),
        "exit_step": _serialize_exit_step(exit_step),
        "error_class": error_class,
        "error_detail": error_detail,
        "outputs": dict(outputs),
        "metrics": {
            "queried_count": int(metrics.get("queried_count", 0)),
            "query_failures": int(metrics.get("query_failures", 0)),
            "computed_count": int(metrics.get("computed_count", 0)),
            "compute_validation_failures": int(metrics.get("compute_validation_failures", 0)),
            "descriptions_generated": int(metrics.get("descriptions_generated", 0)),
            "description_failures": int(metrics.get("description_failures", 0)),
            "llm_calls": int(metrics.get("llm_calls", 0)),
            "duration_seconds": float(metrics.get("duration_seconds", 0.0)),
        },
    }
```

Replace the CLI argument definition:

```python
parser.add_argument("--exit-step", required=True, type=int)
```

with:

```python
parser.add_argument("--exit-step", required=True)
```

- [ ] **Step 4: Run focused status tests and verify they pass**

Run:

```bash
rtk pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -q
```

Expected: PASS for all tests in `test_assemble_status.py`.

- [ ] **Step 5: Run a CLI smoke check for decimal checkpoint ids**

Run:

```bash
rtk python skills/public/chatbi-report/scripts/assemble_status.py \
  --out /tmp/chatbi-status-8c5.json \
  --exit-step 8c.5 \
  --error-class USER_ABORTED \
  --error-detail '计算 checkpoint 停下' \
  --outputs '{"json": null, "docx": null, "md": null}' \
  --metrics '{"queried_count": 1, "query_failures": 0, "computed_count": 0, "compute_validation_failures": 1, "descriptions_generated": 0, "description_failures": 0, "llm_calls": 1, "duration_seconds": 1.0}'
```

Expected output contains:

```text
OK: wrote status -> /tmp/chatbi-status-8c5.json
```

Then inspect the file manually if needed; `exit_step` should be the JSON string `"8c.5"`.

Run this second smoke check for integer-step compatibility:

```bash
rtk python skills/public/chatbi-report/scripts/assemble_status.py \
  --out /tmp/chatbi-status-9.json \
  --exit-step 9 \
  --error-detail '' \
  --outputs '{"json": null, "docx": null, "md": null}' \
  --metrics '{"queried_count": 1, "query_failures": 0, "computed_count": 0, "compute_validation_failures": 0, "descriptions_generated": 0, "description_failures": 0, "llm_calls": 1, "duration_seconds": 1.0}'
```

Expected output contains:

```text
OK: wrote status -> /tmp/chatbi-status-9.json
```

If inspected, `/tmp/chatbi-status-9.json` should contain numeric JSON `"exit_step": 9`, not string `"9"`.

- [ ] **Step 6: Do not commit unless explicitly asked**

No commit command should be run during implementation unless the user explicitly requests it.

---

### Task 2: Update the skill state machine and checkpoint contract

**Files:**
- Modify: `skills/public/chatbi-report/SKILL.md:79-188`

**Interfaces:**
- Consumes: existing skill sections `流水线契约`, `状态机`, `步骤类型`, `步骤定义`, `Checkpoint 通用契约`, and `重试预算`.
- Produces: executable agent instructions for Step 8c.5 and Step 8d.5.

- [ ] **Step 1: Update the state machine text**

In `skills/public/chatbi-report/SKILL.md`, replace the state machine block with:

```text
1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide → 5 unit-convert → 6 extract-ir
→ 7 codegen → 8a validate → 8b evaluate → 8c apply-computed
→ 8c.5 compute checkpoint → 8d describe → 8d.5 description checkpoint
→ 9 render/status
```

- [ ] **Step 2: Update step type table**

Change the `agent-turn-checkpoint` row to include the new steps:

```markdown
| `agent-turn-checkpoint` | lead agent 调 `ask_clarification` 暂停流水线等用户确认 | 1.5, 3.5, 8c.5, 8d.5 |
```

- [ ] **Step 3: Update step definition table**

Insert this row after Step 8c:

```markdown
| **8c.5. compute checkpoint** | **agent-turn-checkpoint** | 详见下文 "Checkpoint 通用契约" + "Step 8c.5 专属" | 用户回复 + runlog 一行 + 可选 status 中断 |
```

Replace the Step 8d row with:

```markdown
| **8d. describe** | **agent-turn-LLM** | lead agent 读 `description_gen.md` + `<wide.json>`，若 parsed 含 `description_prompt` 逐 report 生成描述，**必须用 `write_file` 落盘到精确路径 `<stem>.description.report-<idx>.txt`** | `<stem>.description.report-<idx>.txt` × N |
```

Insert this row after Step 8d:

```markdown
| **8d.5. description checkpoint** | **agent-turn-checkpoint** | 详见下文 "Checkpoint 通用契约" + "Step 8d.5 专属" | 用户回复 + runlog 一行 + 可选 status 中断 |
```

- [ ] **Step 4: Update checkpoint common contract wording**

In `Checkpoint 通用契约`, keep the existing tool and middleware wording, but update the response branch wording to include new checkpoint ids and internal artifact language:

```markdown
**响应分支**（所有 checkpoint 共用）：

- 用户选「继续」：runlog 追加中文台账行（含 `Step X.Y ... checkpoint：用户确认继续` 和关键计数），进入下一非 checkpoint step。
- 用户选「停下」：runlog 追加中文台账行（含 `Step X.Y ... checkpoint：用户选择停下` 和关键计数），调 `assemble_status.py` 写：
  - `status = error`
  - `exit_step = X.Y`（checkpoint 编号；整数步骤仍可为 JSON number，非整数 checkpoint 如 `8c.5` 为 string）
  - `error_class = USER_ABORTED`
  - `error_detail` 含 checkpoint 中文摘要 + 用户可执行的下一步
  按"最终回复模板"三态收口，**不要静默吞掉**。
```

- [ ] **Step 5: Add Step 8c.5 dedicated section**

Add this section after Step 3.5 dedicated section:

```markdown
#### Step 8c.5 compute checkpoint 专属

- **触发条件**：Step 8c 后如果 `total > 0` 则触发（无论计算列全部成功、部分失败还是全部失败）；如果 `total = 0`，静默跳过 Step 8c.5，直接进入 Step 8d 或 Step 9。
- **摘要内容**（≤ 600 字）：
  - `ok / total`：成功计算列数 / 总计算列数
  - 失败计算列名称与失败原因（如 `compute_validation_failed`、`compute_smoke_failed`、`compute_codegen_failed`）
  - 每个 report 前 2 行的计算列值预览
  - 如存在失败：说明继续后 `⚠️COMPUTE_FAILED` 会保留进最终报表，最终状态可能是 `partial`
- **question 模板**：
  - 至少一个成功（`ok > 0`）：`计算列处理完成：{ok}/{total} 成功。是否继续生成描述和最终报表？`
  - 全失败（`ok == 0 && total > 0`）：`计算列全部失败：0/{total}。是否继续用 ⚠️COMPUTE_FAILED 占位生成 partial 报表？`
- **options**：
  - 至少一个成功：`["继续", "停下（我去修计算定义）"]`
  - 全失败：`["继续（partial，用 ⚠️COMPUTE_FAILED 占位）", "停下（我去修计算定义）"]`
- **runlog 模板**：`Step 8c.5 计算 checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`
- **停下时下一步**：提示用户修改原始样张里的 `> 计算:` 块后重跑。
```

- [ ] **Step 6: Add Step 8d.5 dedicated section**

Add this section after Step 8c.5:

```markdown
#### Step 8d.5 description checkpoint 专属

- **触发条件**：样张中存在至少一个 `> 描述:` 块时总是触发；没有描述需求时静默跳过。
- **摘要内容**（≤ 800 字）：
  - 每个 report 的标题
  - 原始 `> 描述:` prompt
  - 已生成的描述文本；生成失败时展示 `⚠️DESCRIPTION_FAILED`
- **question 模板**：`描述段落已生成：{ok}/{total} 成功。是否满意并继续渲染最终报表？`
- **options**：`["满意，继续", "不满意，停下修改描述提示词"]`
- **runlog 模板**：`Step 8d.5 描述 checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`
- **停下时下一步**：提示用户修改原始样张里的 `> 描述:` 块后重跑。
- **禁止行为**：同一次运行内不接受新 prompt 重新生成，也不回写上传的原始样张。
```

- [ ] **Step 7: Update retry budget note**

Replace:

```markdown
`1.5` / `3.5` 是 user checkpoint，不在此预算表内——它们的"重试"语义是用户重新发起跑。
```

with:

```markdown
`1.5` / `3.5` / `8c.5` / `8d.5` 是 user checkpoint，不在此预算表内——它们的"重试"语义是用户修改样张或配置后重新发起跑。
```

- [ ] **Step 8: Add checkpoint scenario checklist**

Add this checklist near the checkpoint sections or final verification guidance in `SKILL.md` so implementation reviewers can verify behavior without inventing cases later:

```markdown
Checkpoint 场景验收：

- Step 8c.5：`total > 0 && ok > 0` 时展示成功/失败摘要，用户选「继续」后进入 Step 8d。
- Step 8c.5：`total > 0 && ok == 0` 时展示全失败摘要，用户选「继续」后用 `⚠️COMPUTE_FAILED` 进入 partial 路径。
- Step 8c.5：用户选「停下」时写 `USER_ABORTED`，`exit_step = 8c.5`，提示修改原始 `> 计算:` 块后重跑。
- Step 8c.5：`total = 0` 时静默跳过，不展示空 checkpoint。
- Step 8d.5：存在 `> 描述:` 块时展示 report 标题、原始 prompt、生成描述或 `⚠️DESCRIPTION_FAILED`。
- Step 8d.5：用户选「满意，继续」后进入 Step 9。
- Step 8d.5：用户选「不满意」时写 `USER_ABORTED`，`exit_step = 8d.5`，提示修改原始 `> 描述:` 块后重跑。
- Step 8d.5：不存在 `> 描述:` 块时静默跳过。
```

- [ ] **Step 9: Validate Markdown text locally**

Run:

```bash
rtk grep -n '8c\.5\|8d\.5\|Step 6\.5' skills/public/chatbi-report/SKILL.md
```

Expected:

- Multiple matches for `8c.5` and `8d.5`.
- No instruction that says Step 6.5 should be added.

- [ ] **Step 10: Do not commit unless explicitly asked**

No commit command should be run during implementation unless the user explicitly requests it.

---

### Task 3: Update user-facing output and internal artifact responsibilities

**Files:**
- Modify: `skills/public/chatbi-report/SKILL.md:71-77`
- Modify: `skills/public/chatbi-report/SKILL.md:225-243`
- Modify: `skills/public/chatbi-report/SKILL.md:288-357`

**Interfaces:**
- Consumes: existing `输出呈现`, `运行台账`, `status.json schema`, and `最终回复模板` sections.
- Produces: Chinese-first user output contract and machine/internal artifact contract.

- [ ] **Step 1: Update output presentation section**

Replace the current `## 输出呈现` bullet list with:

```markdown
## 输出呈现

- 用户侧输出以对话中的中文进度、checkpoint 摘要、最终中文状态总结，以及 `report.md` / `report.docx` 为主。
- 在最终回复中展示 `status`、停止步骤、关键 metrics、降级项和下一步建议，但不要粘贴 `status.json` 原文。
- 在对话中回显生成的 `report.md` 内容；如果内容过长，展示摘要并通过文件分享完整版本。
- 对 `report.docx` 和完整 `report.md` 调用 `present_files` 分享给用户下载。
- `runlog.md` 是内部运行台账 / 排障材料，默认不作为用户交付物展示；只有用户要求排查或需要定位异常时才提示路径。
- `status.json` 是 Agent / 编排器读取的机器契约，不作为用户交付物展示，最终回复不强制列出路径。
- 如果状态是 `partial`，明确列出查询失败数、计算校验失败数或描述生成失败数，并说明对应单元格 / 列 / 段落已保留 sentinel。
- 不主动做数据解读、不主动建议新增分析维度；用户追问再处理。
```

- [ ] **Step 2: Update progress feedback table**

Add these rows to the progress feedback table:

```markdown
| 8c.5 | `🚦 Checkpoint：计算列 {ok}/{total} 成功，等用户确认` |
| 8d.5 | `🚦 Checkpoint：描述 {ok}/{total} 成功，等用户确认`（仅当 `> 描述:` 块存在时） |
```

- [ ] **Step 3: Update runlog section to Chinese internal ledger**

Replace the first sentence under `### 运行台账` with:

```markdown
创建并持续更新 `/mnt/user-data/outputs/<stem>.runlog.md`。这是内部运行台账 / 排障材料，不是默认用户交付物；内容中文优先。每完成一步或发生重试，追加一条记录：
```

Replace the example runlog block with:

```markdown
# chatbi-report runlog

- Step 1 lint：成功，错误=0，警告=2
- Step 1.5 lint checkpoint：用户确认继续，错误=0，警告=2
- Step 2 parse：成功，章节=1，报表=1，指标=1
- Step 3 query：成功，成功指标=4，失败=0，输出=/mnt/user-data/outputs/input.query.json
- Step 3.5 query checkpoint：用户确认继续，成功=4，总数=4
- Step 4 assemble-wide：成功，行=4，列=7，输出=/mnt/user-data/outputs/input.wide.json
- Step 8a validate：重试，spec=2025利润同比，retry=1/1，原因=example mismatch
- Step 8c.5 计算 checkpoint：用户确认继续，成功=2，总数=3
- Step 8d describe：成功，report=0，输出=/mnt/user-data/outputs/input.description.report-0.txt
- Step 8d.5 描述 checkpoint：用户确认继续，成功=1，总数=1
- Step 9 render：成功，md=/mnt/user-data/outputs/input.report.md，docx=/mnt/user-data/outputs/input.report.docx
```

Remove this sentence if present:

```markdown
最终回复必须包含 runlog 路径。
```

- [ ] **Step 4: Update number extraction table**

Add rows:

```markdown
| 8c.5 | `<stem>.wide.json` + compute status / `<stem>.computed.*.json` | 统计计算 spec 总数、成功数、失败数；抽取每个 report 前 2 行计算列预览 |
| 8d.5 | `<stem>.description.report-*.txt` + `<stem>.parsed.json` | 数描述文件成功/失败；读取 report 标题、原始 `description_prompt`、生成文本 |
```

- [ ] **Step 5: Update failure handling bullets**

Replace the checkpoint bullet:

```markdown
- **checkpoint（1.5 / 3.5）用户选「停下」**：写 `status=error / exit_step=checkpoint / error_class=USER_ABORTED`，按"最终回复模板"三态收口。
```

with:

```markdown
- **checkpoint（1.5 / 3.5 / 8c.5 / 8d.5）用户选「停下」**：写 `status=error / exit_step=<checkpoint> / error_class=USER_ABORTED`，在最终回复中用中文说明 checkpoint 摘要和用户下一步；不要要求用户打开 `status.json`。
```

- [ ] **Step 6: Update status schema section**

Change the schema field:

```json
"exit_step": "1 | 1.5 | 2 | 3 | 3.5 | 4-9"
```

To:

```json
"exit_step": "1 | 1.5 | 2 | 3 | 3.5 | 4 | 5 | 6 | 7 | 8a | 8b | 8c | 8c.5 | 8d | 8d.5 | 9"
```

Add this paragraph after the schema:

```markdown
`status.json` 是 Agent / 编排器读取的机器契约，不面向人类直接展示。最终回复应读取其中关键字段，转成中文摘要给用户，不粘贴 JSON 原文，也不强制展示路径。
```

- [ ] **Step 7: Update final reply template**

Replace the artifact list in the final reply template with:

```text
产物：
- Markdown 报表：已分享 /mnt/user-data/outputs/<stem>.report.md
- DOCX 报表：已分享 /mnt/user-data/outputs/<stem>.report.docx
```

Remove these lines from the user-facing template:

```text
- Status: /mnt/user-data/outputs/<stem>.status.json
- Runlog: /mnt/user-data/outputs/<stem>.runlog.md
```

Add this note after the template:

```markdown
`status.json` 和 `runlog.md` 默认不作为用户交付物展示；只有排障需要或用户主动索要时，才说明内部路径。
```

- [ ] **Step 8: Validate wording with literal search**

Run:

```bash
rtk grep -n '最终回复必须包含 runlog 路径\|Status: /mnt/user-data/outputs\|Runlog: /mnt/user-data/outputs\|status.json.*原文' skills/public/chatbi-report/SKILL.md
```

Expected:

- No match for `最终回复必须包含 runlog 路径`.
- No match for `Status: /mnt/user-data/outputs`.
- No match for `Runlog: /mnt/user-data/outputs`.
- A match is acceptable only if it says not to paste `status.json` 原文.

- [ ] **Step 9: Do not commit unless explicitly asked**

No commit command should be run during implementation unless the user explicitly requests it.

---

### Task 4: Run focused verification

**Files:**
- Test: `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`
- Inspect: `skills/public/chatbi-report/SKILL.md`

**Interfaces:**
- Consumes: Task 1 script/test changes and Task 2-3 skill documentation changes.
- Produces: verification evidence for the changed status contract and skill wording.

- [ ] **Step 1: Run status tests**

Run:

```bash
rtk pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the broader chatbi-report script test subset if time permits**

Run:

```bash
rtk pytest skills/public/chatbi-report/scripts/tests -q
```

Expected: all tests pass. If failures occur outside `test_assemble_status.py`, inspect whether they are pre-existing from the current working tree before changing unrelated files.

- [ ] **Step 3: Verify checkpoint wording exists**

Run:

```bash
rtk grep -n '8c\.5 compute checkpoint\|8d\.5 description checkpoint\|Step 8c\.5\|Step 8d\.5' skills/public/chatbi-report/SKILL.md
```

Expected: matches in state machine, step definition table, checkpoint dedicated sections, progress feedback, and final reply guidance.

- [ ] **Step 4: Verify removed user-facing internal artifact requirements**

Run:

```bash
rtk grep -n '最终回复必须包含 runlog 路径\|Status: /mnt/user-data/outputs\|Runlog: /mnt/user-data/outputs' skills/public/chatbi-report/SKILL.md
```

Expected: zero matches.

- [ ] **Step 5: Check working tree diff before reporting**

Run:

```bash
rtk git diff -- skills/public/chatbi-report/SKILL.md skills/public/chatbi-report/scripts/assemble_status.py skills/public/chatbi-report/scripts/tests/test_assemble_status.py
```

Expected: diff only touches the implementation files from this plan. Check the design spec separately only if you intentionally changed it during planning.

- [ ] **Step 6: Report verification results**

Report:

```text
验证结果：
- test_assemble_status.py: PASS/FAIL
- scripts/tests subset: PASS/FAIL/未运行（说明原因）
- SKILL.md checkpoint wording: PASS/FAIL
- internal artifact wording removed: PASS/FAIL
```

- [ ] **Step 7: Do not commit unless explicitly asked**

No commit command should be run during implementation unless the user explicitly requests it.
