# ai-report Pipeline Reference

Read this when running the full `ai-report` workflow or changing its step
contract. Two pipelines share one state: the design pipeline (lead agent +
LLM, per-section) and the runtime pipeline (deterministic, per-report).

## State machine — design (per section)

Run forward only. Each `## N` H2 section is one full table block in the
report MD.

```text
0 lint → 1.5 lint checkpoint
→ 2 query (per-idx SQLBot) → 3.5 query checkpoint
→ 4 assemble-wide → 5 extract-ir
→ 6 codegen → 7 validate → 8 evaluate → 9 apply-computed
→ 10 unit_convert (Python) → 11 describe
→ 11.5 description checkpoint (only if description_prompt provided)
→ 12 preview → 10 (renamed 12) preview checkpoint
→ 14 save approved run
→ 11 (renamed 13) post-section checkpoint
```

Step numbering follows the original 14-step design. The runtime CLI does
NOT touch any step number; it only reads approved runs and renders.

## State machine — runtime (per report)

```text
R-0 existence check → R-1 list approved tables
→ R-2 build payload → R-3 render md
→ R-4 render docx → R-5 中文回执 + status.json
```

## Step types

| Type | Meaning | Steps |
|---|---|---|
| `bash` | deterministic Python in sandbox | 1, 2, 4, 5, 7, 8, 9, 10, 14, R-0..R-5 |
| `agent-turn-LLM` | lead agent calls LLM with prompt | 6 (codegen), 11 (describe) |
| `agent-turn-checkpoint` | lead agent calls `ask_clarification` | 0/1.5, 3.5, 8d.5, 12, 13 |

## Step definitions

| Step | Type | Command / owner | Output |
|---|---|---|---|
| 0 lint | bash | `python scripts/md_lint.py /mnt/ai-report-data/<file>.md` | LintReport (errors/warnings) |
| 1.5 lint checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog line |
| 2 query | bash | `DesignPipeline._step_query_metrics` (per idx, per period) | rows in `metric_facts` table |
| 3.5 query checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog line |
| 4 assemble-wide | bash | `compute.py assemble_wide` | `list[dict]` wide table |
| 5 extract-ir | bash | `compute.py extract_ir` (parse `> 计算:` blocks) | `list[ComputeIR]` |
| 6 codegen | agent-turn-LLM | `prompts/compute_codegen.md` + ComputeIR + wide sample | DuckDB SQL string |
| 7 validate | bash | `compute.py validate` (EXPLAIN + RUN + EXAMPLE, 3 layers) | ValidationResult(passed, layer, msg) |
| 8 evaluate | bash | `compute.py evaluate` (row count = wide rows) | (values, status) |
| 9 apply-computed | bash | `compute.py apply_computed` | updated wide |
| 10 unit_convert | bash | `unit_convert.py apply_units` (Python, Decimal precision) | updated wide |
| 11 describe | agent-turn-LLM | `prompts/description_gen.md` + wide rows + title | Chinese paragraph |
| 8d.5 description checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply + runlog |
| 12 preview checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply → approve/modify/reject |
| 13 post-section checkpoint | agent-turn-checkpoint | see `checkpoints.md` | continue / jump / preview / done |
| 14 save approved run | bash | `Store.save_approved_run` (transactional) | row in `approved_runs` |
| R-0 existence | bash | `Store.get_report_meta` | meta dict or None |
| R-1 list approved | bash | `Store.list_approved_tables` | list[dict] of approved runs |
| R-2 build payload | bash | `report_md.build_runtime_payload` | payload dict |
| R-3 render md | bash | `render_markdown.py` | `<report_id>.report.md` |
| R-4 render docx | bash | `render_docx.py` | `<report_id>.report.docx` |
| R-5 中文回执 | bash | `assemble_status.py build_status + format_zh_receipt` | stdout receipt + status dict |

## Retry budget

| Step | Automatic retry | After limit |
|---|---:|---|
| 0 lint | 0 | stop, show lint errors and fixes |
| 2 query | SQLBot client internal retry (3x) | failed fact → `query_failed` status; pipeline continues |
| 6 codegen | 1 (lead agent regenerates once with validate/evaluate feedback) | second failure → `⚠️COMPUTE_FAILED` sentinel; continue |
| 11 describe | 1 (runtime strips fences + reruns once) | second failure → description empty; sentinel `⚠️DESCRIPTION_FAILED` |
| 12 preview | 0 | reject → `approval_status='draft'`; no row in `approved_runs` |

Checkpoints are not retry loops. If user stops, the section run ends with
`USER_ABORTED` and no approved run is written.

Step 3.5 always triggers, even when `ok == 0` — fail-fast is disabled. The
user picks between partial-with-sentinel and stop-and-investigate at every
query checkpoint.

## Progress messages

Send one short Chinese progress update after every completed step.

| Step | Template |
|---|---|
| 0 | `📋 Lint 完成：{n_err} 错误 / {n_warn} 警告` |
| 1.5 | `🚦 Checkpoint 1.5：{n_err} 错误 / {n_warn} 警告，等用户确认` |
| 2 | `🔍 SQLBot 查询：{ok}/{total} 指标成功{fail_detail}` |
| 3.5 | `🚦 Checkpoint 3.5：{ok}/{total} 指标成功，等用户确认` |
| 4 | `📐 宽表拼装：{rows} 行 × {cols} 列` |
| 5 | `🧬 抽取 IR：{n} 个计算 spec` |
| 6 | `🧠 正在为 {n} 个计算列生成 DuckDB SQL…` |
| 7 | `✅ 校验 {ok}/{total} 通过` or `⚠️ 第 {i} 个失败：{err[:60]}` |
| 8 | `🧮 evaluate：{ok}/{total} spec 成功` |
| 9 | `📊 已合并 {n} 个计算列到宽表` |
| 10 | `🔄 单位换算：{n_changed} 列已换算到目标单位` |
| 11 | `📝 描述生成：{ok}/{total} 成功` |
| 8d.5 | `🚦 Checkpoint 8d.5：描述 {ok}/{total} 成功，等用户确认` |
| 12 | `🚦 Checkpoint 12：section preview 准备好，等用户确认` |
| 13 | `🚦 Checkpoint 13：section approved，进入下一节？` |
| 14 | `💾 approved_run 已写入 DuckDB` |
| R-0..R-5 | `🎉 报表已生成：{report_id}.report.md / {report_id}.report.docx（{status}）` |

## Do not

- Add Step 6.5 IR preview. Compute review happens after Step 8c, where actual
  values and failures are known.
- Re-run an already-approved section unless the user changes the source MD
  (hash mismatch in `reports.src_hash` triggers a fresh run automatically).
- Mix runtime steps into the design pipeline. Runtime is read-only over
  `approved_runs`.