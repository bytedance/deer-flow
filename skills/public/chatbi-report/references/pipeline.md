# chatbi-report Pipeline Reference

Read this when running the full `chatbi-report` workflow or changing its step contract.

## State machine

Run forward only:

```text
1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide → 6 extract-ir
→ 7 codegen → 8a validate → 8b evaluate → 8c apply-computed
→ 8d describe → 8d.5 description checkpoint
→ 9 render/status
```

Note: Step 5 (unit-convert) was removed — `unit_conversion.py` is a library
(`convert_unit()` + `SCALE_FACTOR`), not a CLI. Unit conversion is folded into
Step 4 `assemble-wide` and the per-idx `unit` field on `<th data-idx>`.

- `lint-only`: `1 → 1.5` when lint has findings, then stop.
- `skip-docx`: same as full, but Step 9 skips `render_docx.py`.
- Do not add Step 6.5 IR preview. Compute review happens after Step 8c, where actual values and failures are known.

## Step types

| Type | Meaning | Steps |
|---|---|---|
| `bash` | deterministic CLI in sandbox | 1, 2, 3, 4, 6, 8a, 8b, 8c, 9 |
| `agent-turn-LLM` | lead agent writes files using LLM output | 7, 8d |
| `agent-turn-checkpoint` | lead agent calls `ask_clarification` and waits for user | 1.5, 3.5, 8d.5 |

## Step definitions

| Step | Type | Command / owner | Output |
|---|---|---|---|
| 1 lint | bash | `python /mnt/skills/public/chatbi-report/scripts/md_lint.py /mnt/user-data/uploads/<file>.md` | exit code + LintReport |
| 1.5 lint checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog line |
| 2 parse | bash | `python /mnt/skills/public/chatbi-report/scripts/parse_md.py /mnt/user-data/uploads/<file>.md --out /mnt/user-data/outputs/<stem>.parsed.json` | `<stem>.parsed.json` |
| 3 query | bash | `python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query --parsed /mnt/user-data/outputs/<stem>.parsed.json --mock --out /mnt/user-data/outputs/<stem>.query.json` | `<stem>.query.json` |
| 3.5 query checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog line |
| 4 assemble-wide | bash | `python /mnt/skills/public/chatbi-report/scripts/compute.py assemble-wide --query /mnt/user-data/outputs/<stem>.query.json --parsed /mnt/user-data/outputs/<stem>.parsed.json --out /mnt/user-data/outputs/<stem>.wide.json` | `<stem>.wide.json` (cells already converted to Decimal per `unit` field) |
| 6 extract-ir | bash | `python /mnt/skills/public/chatbi-report/scripts/compute.py extract-ir --parsed /mnt/user-data/outputs/<stem>.parsed.json --out /mnt/user-data/outputs/<stem>.ir.json` | `<stem>.ir.json` |
| 7 codegen | agent-turn-LLM | read `prompts/compute_codegen.md` + `<stem>.ir.json`; write `<stem>.compute.<slug>.py` | compute source files |
| 8a validate | bash | `python /mnt/skills/public/chatbi-report/scripts/compute.py validate --source <compute.py> --function <name> --df <wide.json> --example-input ... --example-expected ...` | exit 0/1 |
| 8b evaluate | bash | `python /mnt/skills/public/chatbi-report/scripts/compute.py evaluate --source <compute.py> --function <name> --df <wide.json> --name '<ComputeIR.name>' --out <computed.slug>.json` | computed JSON files |
| 8c apply-computed | bash | `python /mnt/skills/public/chatbi-report/scripts/compute.py apply-computed --wide <wide.json> --computed-dir <outputs> --stem <stem>` | updated `<stem>.wide.json` |
| 8d describe | agent-turn-LLM | read `prompts/description_gen.md` + `<wide.json>`; write `<stem>.description.report-<idx>.txt` for each parsed `description_prompt` | description text files |
| 8d.5 description checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog line + optional status abort |
| 9 render/status | bash | `render_markdown.py` + optional `render_docx.py` + `assemble_status.py` | report MD/DOCX/status/runlog |

## Retry budget

| Step | Automatic retry / repair limit | After limit |
|---|---:|---|
| 1 lint | 0 | stop, show lint errors and fixes |
| 2 parse | 0 | stop, show parse error and fix |
| 3 query | SQLBot client internal retry only | failed cells become `⚠️QUERY_FAILED`; pipeline continues after 3.5 user decision |
| 4 assemble-wide | 0 | stop, show raw error |
| 7 codegen | one initial draft per spec | 8a decides retry |
| 8a validate | one re-codegen per spec | failed column becomes `⚠️COMPUTE_FAILED`; continue |
| 8d describe | one regenerate per report | failed description file contains `⚠️DESCRIPTION_FAILED`; continue |
| 9 render/status | 0; if only a description file is missing, rerun that report's Step 8d once | stop on remaining failure |

Checkpoints `1.5`, `3.5`, and `8d.5` are not retry loops. If the user stops, the run ends with `USER_ABORTED`; the user edits the template/config and reruns.

Step 3.5 always triggers, even when `ok == 0` — fail-fast is disabled (per
2026-06-27 policy reversal). The user picks between partial-with-sentinel
and stop-and-investigate at every query checkpoint.

## Progress messages

Send one short Chinese progress update after every completed step.

| Step | Template |
|---|---|
| 1 | `📋 Lint 完成：{n_err} 错误 / {n_warn} 警告` |
| 1.5 | `🚦 Checkpoint：{n_err} 错误 / {n_warn} 警告，等用户确认` |
| 2 | `📄 解析完成：{n_sec} 章节、{n_rep} 报表、{n_idx} 个指标` |
| 3 | `🔍 SQLBot 查询：{ok}/{total} 指标成功{fail_detail}` |
| 3.5 | `🔍 Checkpoint：{ok}/{total} 指标成功，等用户确认` |
| 4 | `📐 宽表拼装：{rows} 行 × {cols} 列` |
| 6 | `🧬 抽取 IR：{n} 个计算 spec` |
| 7 | `🧠 正在为 {n} 个计算列生成 Python 代码…` |
| 8a | `✅ 校验 {ok}/{total} 通过` or `⚠️ 第 {i} 个失败：{stderr[:60]}` |
| 8b | `🧮 evaluate：{ok}/{total} spec 成功` |
| 8c | `📊 已合并 {n} 个计算列到宽表` |
| 8d | `📝 描述生成：{ok}/{total} 成功` |
| 8d.5 | `🚦 Checkpoint：描述 {ok}/{total} 成功，等用户确认` |
| 9 | `🎉 报表已生成：report.md / report.docx（{status}）` |
