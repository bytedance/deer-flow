# chatbi-report Checkpoints Reference

Read this before running or editing Step 1.5, 3.5, or 8d.5.

## Common contract

All checkpoints use the built-in tool:

```text
ask_clarification(question, clarification_type, context, options)
```

- `clarification_type`: always `risk_confirmation`.
- The tool is intercepted by `ClarificationMiddleware`; do not try to pause with bash stdin.
- User choice decides whether the pipeline continues or ends with `USER_ABORTED`.

## Common branches

User chooses continue:

- Append a Chinese runlog line such as `Step X.Y ... checkpoint：用户确认继续，...`.
- Continue to the next non-checkpoint step.

User chooses stop:

- Append a Chinese runlog line such as `Step X.Y ... checkpoint：用户选择停下，...`.
- Write status via `assemble_status.py`:
  - `status = error`
  - `exit_step = <checkpoint>` such as `8d.5`
  - `error_class = USER_ABORTED`
  - `error_detail` includes checkpoint summary and a concrete next action.
- End with the final reply template from `status-output.md`.

## Step 1.5 lint checkpoint

- **Trigger**: `errors > 0 || warnings > 0`; skip when lint is clean. In `lint-only`, this is the only checkpoint.
- **Summary**: first 5 errors + first 5 warnings, with locations.
- **Question**: `LintReport：{n_err} 错误 / {n_warn} 警告。是否继续生成报表？`
- **Options**: `["继续", "停下（我去修样张）"]`
- **Runlog**: `Step 1.5 lint checkpoint：用户确认继续|用户选择停下，错误={n_err}，警告={n_warn}`

## Step 3.5 query checkpoint

- **Trigger**: always, even when `queried_count` is 0. Fail-fast is disabled.
- **Summary**:
  - `ok / total` indicator count
  - failed `idx_id` list and reasons
  - sample values from the first 2 rows per report, formatted as a Markdown table (see below)
  - key period/org metadata when available
  - if all failed, common failure reason and likely SQLBot/network/permission checks
- **Sample table format** (per report; unit goes in the column header; pick one orientation that fits):
  - N 机构 × 2 时期（最常见）：

    | 机构 | 2024（万元） | 2025（万元） |
    |---|---|---|
    | 王益联社 | 495.83 | 322.78 |
    | 印台联社 | 525.43 | 350.62 |

  - N 机构 × M 时期（>2 时期）：每行一机构，每列一时期。
  - K 指标 × M 时期（多指标时）：每行一机构 × 指标组合，每列一时期；或拆成每指标一张子表，避免列过宽。
- **Questions**:
  - `ok > 0`: `SQLBot 取数完成：{ok}/{total} 指标成功。是否继续生成报表？`
  - `ok == 0`: `SQLBot 取数全部失败：0/{total}。是否继续用 sentinel 占位生成 partial 报表？`
- **Options**:
  - `ok > 0`: `["继续", "停下（数据需复核）"]`
  - `ok == 0`: `["继续（partial，用 ⚠️QUERY_FAILED 占位）", "停下（我去查 SQLBot）"]`
- **Runlog**: `Step 3.5 query checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`

## Step 8d.5 description checkpoint

- **Trigger**: when the parsed template contains at least one `> 描述:` block.
- **Skip**: if no report has `description_prompt`, silently skip Step 8d.5.
- **Summary**:
  - report title
  - original `> 描述:` prompt
  - generated description text, or `⚠️DESCRIPTION_FAILED`
- **Question**: `描述段落已生成：{ok}/{total} 成功。是否满意并继续渲染最终报表？`
- **Options**: `["满意，继续", "不满意，停下修改描述提示词"]`
- **Runlog**: `Step 8d.5 描述 checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`
- **Stop next action**: tell the user to modify the original template's `> 描述:` block and rerun.
- **Do not** accept a new prompt in the same run, regenerate in-run, or edit the uploaded template.

## Scenario acceptance checklist

- Step 8d.5: with descriptions, show title, prompt, and generated text or sentinel.
- Step 8d.5: continue enters Step 9.
- Step 8d.5: stop writes `USER_ABORTED`, `exit_step = 8d.5`, and points to the original `> 描述:` block.
- Step 8d.5: no `> 描述:` blocks skips silently.
