# ai-report Status and Output Reference

Read this when rendering final output, writing `status.json`, or deciding
what to show the user.

## User-facing output

The user-facing deliverables are:

- Chinese progress messages after each step (see `pipeline.md`).
- Chinese checkpoint summaries, questions, and options
  (see `checkpoints.md`).
- Final Chinese status summary via `format_zh_receipt` (R-5 stdout).
- `<report_id>.report.md` and `<report_id>.report.docx` shared with the user.

Do not paste raw `status.json` to the user. Do not invent paths the
runtime pipeline did not actually write.

## Internal artifacts

| Artifact | Audience | Purpose |
|---|---|---|
| `<report_id>.report.md` | user | chat-shareable preview |
| `<report_id>.report.docx` | user | downloadable final report |
| `<report_id>.status.json` | agent / orchestrator | machine-readable status |
| DuckDB `approved_runs` row | agent / troubleshooting | source of truth for re-renders |

## Runlog example

Stored inside `approved_runs.runlog` (TEXT column). One Chinese line per
step the design pipeline took. Runtime pipeline does NOT write a runlog —
it reads `approved_runs` rows directly.

```markdown
# ai-report runlog

- Step 0 lint：成功，错误=0，警告=2
- Step 1.5 lint checkpoint：用户确认继续，警告=2
- Step 2 query：成功，成功=4，失败=0
- Step 3.5 query checkpoint：用户确认继续，成功=4，总数=4
- Step 4 assemble-wide：成功，行=4，列=7
- Step 5 extract-ir：成功，spec=0
- Step 11 describe：成功
- Step 12 preview checkpoint：用户 approve，sentinels=0
- Step 14 save approved run：成功，run_id=<run_id>，status=ok
```

When sentinels fire:

```markdown
- Step 2 query：成功，成功=3，失败=1（BAS_040@202603: SQLBotError code=500）
- Step 12 preview checkpoint：用户 approve，sentinels=[⚠️QUERY_FAILED]
- Step 14 save approved run：成功，run_id=<run_id>，status=partial
```

## Number sources

Do not guess numbers from memory. Read the corresponding output after each step.

| Step | Source | Count extraction |
|---|---|---|
| 0 | `LintReport.errors/warnings` | count from dataclass |
| 1.5 | same as 0 | errors/warnings for question and context |
| 2 | `Store.get_metric_facts(run_id, table_id)` | `status='ok'` count |
| 3.5 | same as 2 | `ok / total` for question/options/context |
| 4 | `assemble_wide` return | `len(rows)` and `len(row.keys())` |
| 5 | `extract_ir` return | `len(irs)` |
| 7 | `ValidationResult` | `(passed, layer, msg)` tuple |
| 8 | `(values, status)` | count non-None values for `status='ok'` |
| 10 | `apply_units` return | count cells where `unit` is in `DATA_TYPE_MAP` |
| 11 | describe response | file presence or `⚠️DESCRIPTION_FAILED` |
| 12 | preview dict | sentinels from `facts.status` + `failed_compute` |
| 14 | `approved_runs` row | `status` field |
| R-0 | `Store.get_report_meta` | `None` → not_found |
| R-1 | `Store.list_approved_tables` | `[]` → empty |
| R-5 | `format_zh_receipt(status)` | stdout, flush=True |

## `status.json` schema

`assemble_status.build_status` writes:

```json
{
  "status": "ok | partial | error | not_found | empty",
  "report_id": "<report_id>",
  "exit_step": "R-0 | R-1 | R-2 | R-3 | R-4 | R-5",
  "error_class": null | "USER_ABORTED",
  "error_detail": null | "...",
  "outputs": {"md": "/mnt/ai-report-data/<id>.report.md",
              "docx": "/mnt/ai-report-data/<id>.report.docx"},
  "sections": [{
    "section_title": "...",
    "approval_status": "approved",
    "sentinels": ["⚠️QUERY_FAILED"],
    "computed_sentinels": {}
  }],
  "metrics": {
    "queried_count": 0,
    "query_failures": 0,
    "computed_count": 0,
    "compute_validation_failures": 0,
    "descriptions_generated": 0,
    "description_failures": 0,
    "sections_approved": 0,
    "sections_partial": 0,
    "llm_calls": 0,
    "duration_seconds": 0.0
  }
}
```

Note: `status` for runtime is one of `ok | partial | error | not_found | empty`.
`not_found` and `empty` are runtime-only (no approved runs means nothing to
render). Design pipeline uses `ok | partial | error | draft` instead — see
`assemble_status.py` source for the full enum.

## Status decision

- `ok`: every section's `approved_runs.status == 'ok'`.
- `partial`: at least one section has `status='partial'` (sentinels present).
- `error`: user aborted at a checkpoint.
- `not_found`: R-0 failed (runtime only).
- `empty`: R-1 failed (runtime only).

## Sentinel codes

Sentinels are stored as ⚠️ codes in `approved_runs.sentinels` (JSON list).
`assemble_status.build_status` aggregates by code.

| Code | Meaning | Source step | Visible to user |
|---|---|---|---|
| `⚠️QUERY_FAILED` | SQLBot returned `success=false` or raised `SQLBotError` | Step 2 | yes, in 中文回执 |
| `⚠️CAST_FAILED` | SQLBot returned a value that fails `Decimal(str(...))` | Step 2 | yes, in 中文回执 |
| `⚠️COMPUTE_FAILED` | LLM codegen → validate → evaluate chain failed twice | Step 6-8 | yes, in 中文回执 |
| `⚠️DESCRIPTION_FAILED` | LLM describe returned non-Chinese or empty after one retry | Step 11 | yes, in 中文回执 |
| `⚠️LINT_FAILED` | MD failed `md_lint.py` and user did not stop at 0/1.5 | Step 0 | yes, in 中文回执 |

Sentinel codes are NEVER written into a cell. Phase 1 policy: failed cells
are `null` (in wide JSON) or `""` (in renderer output). Codes live in
`approved_runs.sentinels` only.

## Final reply template

```text
🎉 报表已生成：{report_id}.report.md / {report_id>.report.docx（{status}）

关键指标：
- 章节：{n_approved} approved / {n_partial} partial / {n_total}
- SQLBot 查询：{ok}/{total} 成功
- 计算列：{ok}/{total} 成功
- 描述段落：{ok}/{total} 成功
- 自动重试：{retry_count} 次

sentinels（如有）：
- ⚠️QUERY_FAILED × {n}
- ⚠️COMPUTE_FAILED × {n}
```

If `partial`, list each degraded item and its sentinel. If `error`, list
the blocking step, concise error summary, and next action.

For `USER_ABORTED`, say which checkpoint stopped the run and what the
user should edit before rerunning (see `checkpoints.md` for per-checkpoint
stop actions).

## What runtime CLI guarantees vs does not

| Guarantee | Why |
|---|---|
| Out files exist if exit 0 | R-3, R-4 write before R-5 |
| stdout receipt is flushed | `print(..., flush=True)` in R-5 |
| exit code 0 on partial | partial is a deliverable, not an error |
| exit code 1 on not_found/empty | user error, not silent success |

| Non-guarantee | Why |
|---|---|
| Re-render after source MD edit | runtime trusts `approved_runs`; user must rerun design |
| Atomic write of md + docx | md is written first; if docx fails, md exists but receipt is not printed. Read both files before declaring partial. |
| Docx visual fidelity across Word/LibreOffice | python-docx 1.2.0; tested on LibreOffice only |