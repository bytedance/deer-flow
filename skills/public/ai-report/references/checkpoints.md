# ai-report Checkpoints Reference

Read this before running or editing any of the six checkpoints:
`0/1.5`, `3.5`, `8d.5`, `12`, `13`.

## Common contract

All checkpoints use the built-in tool:

```text
ask_clarification(question, clarification_type, context, options)
```

- `clarification_type`: always `risk_confirmation`.
- The tool is intercepted by `ClarificationMiddleware`; do not try to pause
  with bash stdin.
- User choice decides whether the pipeline continues, jumps, or ends with
  `USER_ABORTED`.

## Common branches

User chooses continue / approve:

- Append a Chinese runlog line such as `Step X.Y ... checkpoint：用户确认继续，...`.
- Continue to the next non-checkpoint step.

User chooses stop / reject:

- Append a Chinese runlog line such as `Step X.Y ... checkpoint：用户选择停下，...`.
- Return `{"approval_status": "draft", "stopped_at": "checkpoint_X.Y"}` from
  `DesignPipeline.run_section`.
- No row written to `approved_runs`.
- Section is resumable: a fresh design run picks up from the next section.

## Checkpoint 0 (lint, before design)

- **Trigger**: when `md_lint.py` reports errors.
- **Skip**: when lint is clean.
- **Summary**: first 5 errors + first 5 warnings with file/section locations.
- **Question**: `Lint 失败 {n_err} 处。继续生成报表？`
- **Options**: `["continue", "stop"]`
- **Runlog**: `Step 0 lint checkpoint：用户确认继续|用户选择停下，错误={n_err}，警告={n_warn}`
- **Stop next action**: tell the user to fix the sample MD and rerun.

## Checkpoint 1.5 (lint pass, before sections)

- **Trigger**: informational after lint pass. Always shown if Step 0 was
  skipped (no errors) so the user sees that lint ran.
- **Summary**: `n_err=0, n_warn={n}`.
- **Question**: `Lint pass {n_warn} warning。继续生成报表？`
- **Options**: `["continue", "stop"]`
- **Runlog**: `Step 1.5 lint checkpoint：用户确认继续|用户选择停下，警告={n_warn}`

## Checkpoint 3.5 (query done)

- **Trigger**: always, even when `ok == 0`. Fail-fast is disabled.
- **Summary**:
  - `ok / total` indicator count from `metric_facts.status`
  - failed `idx_id` list and reasons (from `metric_facts.error_message`)
  - first 2 wide rows sample (when `ok > 0`)
  - key `org_contexts` + `time_info` metadata
  - if all failed, common reason (SQLBot unreachable / permission /
    network) and likely fix
- **Question**:
  - `ok > 0`: `SQLBot 取数完成：{ok}/{total} 指标成功。继续生成报表？`
  - `ok == 0`: `SQLBot 取数全部失败：0/{total}。继续用 sentinel 占位生成 partial 报表？`
- **Options**:
  - `ok > 0`: `["continue", "stop"]`
  - `ok == 0`: `["continue（partial，用 ⚠️QUERY_FAILED 占位）", "stop"]`
- **Runlog**: `Step 3.5 query checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`
- **Stop next action**: tell the user to check SQLBot endpoint /
  credentials / `org_contexts` and rerun.

## Checkpoint 8d.5 (description done)

- **Trigger**: when at least one report has `description_prompt` set
  (post-parse_md, stored in `report_tables.parsed_payload`).
- **Skip**: silently when no `description_prompt` exists across all
  sections.
- **Summary**:
  - report title
  - original `> 描述:` prompt text (if any — currently always None for
    ai-report's Phase 1 templates, since `description_prompt` is reserved
    for future `> 描述:` blocks)
  - generated description text, or `⚠️DESCRIPTION_FAILED`
- **Question**: `描述段落已生成：{ok}/{total} 成功。继续渲染最终报表？`
- **Options**: `["continue", "stop"]`
- **Runlog**: `Step 8d.5 description checkpoint：用户确认继续|用户选择停下，成功={ok}，总数={total}`
- **Stop next action**: tell the user to edit the original `> 描述:` block
  and rerun.
- **Do not** accept a new prompt in the same run, regenerate in-run, or
  edit the uploaded MD.

## Checkpoint 12 (preview approve)

- **Trigger**: always, after Step 11 describe. This is the only
  approval-gate before saving to `approved_runs`.
- **Summary**:
  - preview dict (title, headers, rows, description)
  - all sentinels observed so far (`⚠️QUERY_FAILED`, `⚠️CAST_FAILED`,
    `⚠️COMPUTE_FAILED`)
  - status preview (`ok` if no sentinels, else `partial`)
- **Question**: `Section preview 准备好。approve？`
- **Options**: `["approve", "modify", "reject"]`
- **Runlog**: `Step 12 preview checkpoint：用户 approve|reject|modify，sentinels={n}`
- **Stop next action on reject**: tell the user to edit the source MD's
  data/calc blocks and rerun. Do NOT accept inline edits.
- **Stop next action on modify**: currently same as reject (modify is
  reserved for future in-pipeline regenerate-and-retry).

## Checkpoint 13 (post-section)

- **Trigger**: always, after `save_approved_run` succeeds.
- **Summary**: section N approved, status, sentinels.
- **Question**: `Section {n} approved。继续下一节？`
- **Options**: `["continue", "jump", "preview", "done"]`
  - `continue`: proceed to next section's Step 2.
  - `jump`: skip remaining sections (useful when later sections have known
    bad data — runtime will render only approved ones).
  - `preview`: re-show the just-approved section's preview dict.
  - `done`: stop the design run; runtime can render whatever is approved.
- **Runlog**: `Step 13 post-section checkpoint：用户 {reply}，section={n}`

## Scenario acceptance checklist

- Checkpoint 0: errors present → ask; errors absent → skip silently.
- Checkpoint 1.5: lint passed → ask once (informational).
- Checkpoint 3.5: triggers on every section, `ok == 0` is not a skip.
- Checkpoint 8d.5: skip when no `description_prompt` exists; never edit
  the source MD to add one mid-run.
- Checkpoint 12: reject writes no `approved_runs` row; resume picks up
  from this section on next design run.
- Checkpoint 13: `done` does NOT throw; the design run exits cleanly and
  runtime CLI picks up whatever is approved so far.