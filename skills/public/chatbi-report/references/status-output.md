# chatbi-report Status and Output Reference

Read this when rendering final output, writing `status.json`, or deciding what to show the user.

## User-facing output

The user-facing deliverables are:

- Chinese progress messages after each step.
- Chinese checkpoint summaries, questions, and options.
- Final Chinese status summary with key metrics and next action.
- `report.md` and `report.docx` shared with the user.

Do not force `runlog.md` or `status.json` paths into the final reply.
Do not paste raw `status.json` to the user.

## Internal artifacts

| Artifact | Audience | Purpose |
|---|---|---|
| `<stem>.runlog.md` | Agent / troubleshooting | audit trail, recovery context, checkpoint decisions |
| `<stem>.status.json` | Agent / orchestrator / automation | machine-readable status contract |
| `<stem>.report.md` | user | report body, also echo or summarize in chat |
| `<stem>.report.docx` | user | downloadable final report |

`runlog.md` content should be Chinese-first if retained.

## Runlog example

```markdown
# chatbi-report runlog

- Step 1 lint：成功，错误=0，警告=2
- Step 1.5 lint checkpoint：用户确认继续，错误=0，警告=2
- Step 2 parse：成功，章节=1，报表=1，指标=1
- Step 3 query：成功，成功指标=4，失败=0，输出=/mnt/user-data/outputs/input.query.json
- Step 3.5 query checkpoint：用户确认继续，成功=4，总数=4
- Step 4 assemble-wide：成功，行=4，列=7，输出=/mnt/user-data/outputs/input.wide.json
- Step 8a validate：重试，spec=2025利润同比，retry=1/1，原因=example mismatch
- Step 8d describe：成功，report=0，输出=/mnt/user-data/outputs/input.description.report-0.txt
- Step 8d.5 描述 checkpoint：用户确认继续，成功=1，总数=1
- Step 9 render：成功，md=/mnt/user-data/outputs/input.report.md，docx=/mnt/user-data/outputs/input.report.docx
```

## Number sources

Do not guess numbers from memory. Read the corresponding output files after each step.

| Step | Source | Count extraction |
|---|---|---|
| 1 | bash stderr | count `ERROR` and `WARN` rows |
| 1.5 | same as Step 1 | errors/warnings for question and context |
| 2 | `<stem>.parsed.json` | sections, reports, `all_idx_ids` |
| 3 | `<stem>.query.json` | unique successful `idx_id`; failed results |
| 3.5 | same as Step 3 | `ok / total` for question/options/context |
| 4 | `<stem>.wide.json` | row count and column count excluding metadata keys |
| 6 | `<stem>.ir.json` | spec count |
| 8a | stdout/stderr | `OK: validated` rows and `FAIL:` rows |
| 8b | `<stem>.computed.*.json` | computed result file count |
| 8c | `<stem>.wide.json` | keys added by computed columns |
| 8d | `<stem>.description.report-*.txt` | files generated; sentinel means failure |
| 8d.5 | description files + `<stem>.parsed.json` | generated/failed count, report titles, original prompts, generated text |

## `status.json` schema

`assemble_status.py` writes:

```json
{
  "status": "success | partial | error",
  "exit_step": "1 | 1.5 | 2 | 3 | 3.5 | 4 | 5 | 6 | 7 | 8a | 8b | 8c | 8d | 8d.5 | 9",
  "error_class": null | "F1" | "F19" | "CHATBI-*" | "STEP*_ERROR" | "USER_ABORTED",
  "error_detail": "...",
  "outputs": {"json": "...", "docx": "...", "md": "..."},
  "metrics": {
    "queried_count": 0,
    "query_failures": 0,
    "computed_count": 0,
    "compute_validation_failures": 0,
    "descriptions_generated": 0,
    "description_failures": 0,
    "llm_calls": 0,
    "duration_seconds": 0.0
  }
}
```

Whole-number steps may be JSON numbers for compatibility. Non-integer checkpoint ids such as `8d.5` are strings.

## Status decision

- `success`: `error_class is None` and all failure metrics are 0.
- `partial`: `error_class is None` and one or more failure metrics are > 0.
- `error`: `error_class` is set.

## Error classes

- `null`: success or partial.
- `F1` / `F19` / `CHATBI-*`: template structure error from lint/parse.
- `STEP*_ERROR`: step-level runtime error.
- `USER_ABORTED`: user stopped at checkpoint `1.5`, `3.5`, or `8d.5`; `error_detail` must include the checkpoint summary and next action.

## Sentinels

| Marker / error | Meaning | Handling |
|---|---|---|
| `⚠️QUERY_FAILED` | Step 3 failed this indicator | keep marker; pipeline may continue to partial |
| `⚠️COMPUTE_FAILED` | Step 8a retry still failed | keep marker in computed column; pipeline may continue to partial |
| `⚠️DESCRIPTION_FAILED` | Step 8d retry still failed | keep marker in description paragraph; pipeline may continue to partial |
| `F1` | template structure error | stop at lint/parse; user fixes template |
| `F19` | missing `> 机构:` or `> 时期:` block | stop; user fills context blocks |
| `CHATBI-*` | template constraint error or warning | follow `md_lint.py` output |
| Step 8a exit 1 | generated compute function failed validation | use stderr in second codegen prompt; retry once |

## Final reply template

```text
状态：success | partial | error
停止步骤：Step N
产物：
- Markdown 报表：已分享 /mnt/user-data/outputs/<stem>.report.md
- DOCX 报表：已分享 /mnt/user-data/outputs/<stem>.report.docx

关键指标：
- SQLBot 查询：{ok}/{total} 成功
- 计算列：{ok}/{total} 成功
- 描述段落：{ok}/{total} 成功
- 自动重试：{retry_count} 次
```

If `partial`, list each degraded item and sentinel. If `error`, list blocking step, concise error summary, and next action.

For `USER_ABORTED`, say which checkpoint stopped the run and what the user should edit before rerunning:

- Step 1.5: fix sample lint issues.
- Step 3.5: review SQLBot data/config.
- Step 8d.5: edit the original `> 描述:` block.
