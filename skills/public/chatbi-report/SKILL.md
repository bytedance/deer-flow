---
name: chatbi-report
version: 0.1.0
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

This skill is checkpoint-heavy. The user must explicitly confirm lint findings,
SQLBot query results, and generated descriptions when those checkpoints trigger.

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

## Modes

| Mode | Trigger | Behavior |
|---|---|---|
| `lint-only` | user asks to check/lint/validate the sample only | run Step 1, then Step 1.5 if findings exist |
| `full` | default for generate/run/fill/render requests | run the full pipeline with all checkpoints |
| `skip-docx` | user asks for JSON/Markdown only or says no DOCX | run full pipeline but skip DOCX rendering in Step 9 |

## Sandbox paths

| Type | Path |
|---|---|
| user upload | `/mnt/user-data/uploads/<file>.md` |
| intermediate JSON | `/mnt/user-data/outputs/<stem>.{parsed,query,wide,ir}.json` |
| run ledger | `/mnt/user-data/outputs/<stem>.runlog.md` |
| compute source/result | `/mnt/user-data/outputs/<stem>.compute.<slug>.py`, `/mnt/user-data/outputs/<stem>.computed.<slug>.json` |
| description text | `/mnt/user-data/outputs/<stem>.description.report-<idx>.txt` |
| final report | `/mnt/user-data/outputs/<stem>.report.md`, `/mnt/user-data/outputs/<stem>.report.docx` |
| charts | `/mnt/user-data/outputs/<stem>.charts.json`, `/mnt/user-data/outputs/<stem>.charts/*.png` |
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

## Pipeline quick view

```text
1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide → 6 extract-ir
→ 7 codegen → 8a validate → 8b evaluate → 8c apply-computed
→ 8c.5 chart-gen
→ 8d describe → 8d.5 description checkpoint
→ 9 render/status
```

Note: Step 5 (unit-convert) was removed — `unit_conversion.py` is a library
(`convert_unit()` + `SCALE_FACTOR`), not a CLI. Unit conversion is folded into
Step 4 `assemble-wide` and the per-idx `unit` field on `<th data-idx>`.

Key points:

- Step 3.5 always triggers, even when `ok == 0` — fail-fast is disabled (per
  2026-06-27 policy reversal). The user picks between partial-with-sentinel
  and stop-and-investigate at every query checkpoint.
- Do not add an IR-preview checkpoint before codegen.
- Step 8d.5 triggers only when at least one report has a `> 描述:` block.
- Checkpoints use `ask_clarification(..., clarification_type="risk_confirmation", ...)`.
- If a user stops at Step 8d.5, tell them to edit the original `> 描述:` block and rerun.
- Do not accept in-run replacement prompts or modify uploaded source templates.

## Output rules

User-facing outputs are Chinese progress messages, checkpoint summaries, final
Chinese status summary, `report.md`, and `report.docx`.

- Echo generated `report.md` content in chat when short; summarize and share the
  file when long.
- Share `report.md` and `report.docx` with the user.
- Do not paste raw `status.json`.
- Do not force `status.json` or `runlog.md` paths into the final user reply.
- Mention internal paths only when troubleshooting or when the user asks.

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
