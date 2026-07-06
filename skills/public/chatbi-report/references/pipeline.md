# chatbi-report Pipeline Reference

Read this when running the full `chatbi-report` workflow or changing its step contract.

## State machine (Phase 1 / Phase 2 split)

The pipeline is wrapped by a single `Orchestrator` class in `scripts/pipeline.py`.
Phase 1 (steps 1–6) and Phase 2 (steps 8a–9) run in-process. The 2 LLM steps
(7 codegen, 8d describe) are agent-external between phases. Three checkpoints
(1.5 lint, 3.5 query, 8d.5 description) emit a `CheckpointSignal` on the last
line of stdout that the agent maps to `ask_clarification`.

```text
# Agent calls pipeline.py phase1
[orchestrator] 1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
                → 4 assemble-wide → 6 extract-ir
[agent] reads ir.json + description_prompts; writes compute sources + description files
# Agent calls pipeline.py phase2
[orchestrator] 8a validate → 8b evaluate → 8c apply-computed
                → 8d attach descriptions → 8d.5 description checkpoint
                → 9 render markdown + docx + status.json
```

Note: Step 5 (unit-convert) was removed — `unit_conversion.py` is a library
(`convert_unit()` + `SCALE_FACTOR`), not a CLI. Unit conversion is folded into
Step 4 `assemble-wide` and the per-idx `unit` field on `<th data-idx>`.

- `lint-only`: `1 → 1.5` when lint has findings, then stop.
- `skip-docx`: same as full, but Step 9 skips `render_docx.py`.
- Do not add Step 6.5 IR preview. Compute review happens after Step 8c, where actual values and failures are known.

## Step table

| Step | Type | Owner | Output |
|---|---|---|---|
| 1 lint | in-process | `Orchestrator.run_phase_1` | metrics only |
| 1.5 lint checkpoint | dataclass emit | `Orchestrator.run_phase_1` | `CheckpointSignal("1.5", ...)` if errors |
| 2 parse | in-process | `Orchestrator.run_phase_1` | `<stem>.parsed.json` |
| 3 query | in-process | `Orchestrator.run_phase_1` | `<stem>.query.json` |
| 3.5 query checkpoint | dataclass emit | `Orchestrator.run_phase_1` | `CheckpointSignal("3.5", ...)` if any failure (2026-06-27 policy reversal: always trigger) |
| 4 assemble-wide | in-process | `Orchestrator.run_phase_1` | `<stem>.wide.json` |
| 6 extract-ir | in-process | `Orchestrator.run_phase_1` | `<stem>.ir.json` |
| 7 codegen | agent LLM | lead agent | compute source files |
| 8a validate | in-process | `Orchestrator.run_phase_2` | per-source pass/fail → sentinel |
| 8b evaluate | in-process | `Orchestrator.run_phase_2` | per-source computed dict |
| 8c apply-computed | in-process | `Orchestrator.run_phase_2` | updated wide.per_report |
| 8d attach descriptions | in-process | `Orchestrator.run_phase_2` | `report.description_text` per report (via `render_markdown.attach_description_files`) |
| 8d.5 description checkpoint | dataclass emit | `Orchestrator.run_phase_2` | `CheckpointSignal("8d.5", ...)` if any failure |
| 9 render + status | in-process | `Orchestrator.run_phase_2` | `report.md`, `report.docx`, `status.json` |

## CheckpointSignal → ask_clarification mapping

See spec `docx/superpowers/specs/2026-07-06-chatbi-report-rewrite-design.md`
§"CheckpointSignal → `ask_clarification` 映射" for the fixed mapping table
(do not invent alternatives). The lead agent maps each `step` value to a
specific `ask_clarification(..., clarification_type="risk_confirmation", ...)`
call. User replies are routed back into the pipeline:

- "继续" → re-invoke `phase1` (or `phase2`) with `--skip-lint-checkpoint`,
  `--skip-query-checkpoint`, etc. as appropriate. These set `ForceContinue`
  per spec §"用户回复路由".
- "停止" → write `status.json` with `error_class=USER_ABORTED` via
  `assemble_status.write_status`, then stop.

## Wire format

`pipeline.py` stdout last line is JSON, four kinds:

- `{"kind": "phase1_result", "result": {...}}` — Phase 1 complete, proceed to agent LLM work (Step 7 + 8d)
- `{"kind": "phase2_result", "result": {...}}` — Phase 2 complete, report rendered
- `{"kind": "checkpoint", "step": "1.5" | "3.5" | "8d.5", "metrics": {...}, "artifacts": {...}, "message": "..."}` — call `ask_clarification` per the mapping table
- `{"kind": "phase_aborted", "step": "...", "reason": "USER_ABORTED"}` — emitted by the agent (not by pipeline.py) when the user stops at a checkpoint

Non-last stdout lines (if any) are progress messages. Errors → stderr traceback
+ exit code != 0.

The agent parses the last line via:

```python
last_line = result.stdout.strip().splitlines()[-1]
payload = json.loads(last_line)
if payload["kind"] == "checkpoint":
    ask_clarification(...)
elif payload["kind"] == "phase1_result":
    # do LLM work, then re-invoke with phase2
    ...
```

## Sidecar metrics

`status.json` schema is spec-pinned: 8 flat metrics keys only (see
`assemble_status.write_status`). Detailed per-step metrics from the
Orchestrator (1_lint, 2_parse, 3_query, 4_assemble, 6_ir, 8a_validate, 8b_evaluate,
8c_apply, 8d_describe) are written to a sidecar `orchestrator-metrics.json`
in the same `out_dir`. The sidecar is for debugging and is not consumed by
the agent or the user.

## Retry budget

The new design has no per-step retry budget. Phase 1 either completes or
emits a `CheckpointSignal`; Phase 2 either completes or emits a
`CheckpointSignal` (only at 8d.5). Compute and description failures do not
abort — they mark cells as `⚠️COMPUTE_FAILED` or `⚠️DESCRIPTION_FAILED`
and the pipeline continues to `report.md` / `report.docx` / `status.json`
with `error_class=None`.

Checkpoints `1.5`, `3.5`, and `8d.5` are not retry loops. If the user stops,
the run ends with `USER_ABORTED`; the user edits the template/config and
reruns.

Step 3.5 always triggers, even when `ok == 0` — fail-fast is disabled (per
2026-06-27 policy reversal). The user picks between partial-with-sentinel
and stop-and-investigate at every query checkpoint.

## Progress messages

Send one short Chinese progress update after every completed phase, sourced
from the wire-format `metrics` payload:

| Phase | Template |
|---|---|
| 1 (success) | `📋 Phase 1 完成：{n_err} 错误 / {n_warn} 警告，{n_sec} 章节、{n_rep} 报表、{n_idx} 指标` |
| 1.5 | `🚦 Checkpoint：{n_err} 错误 / {n_warn} 警告，等用户确认` |
| 3.5 | `🔍 Checkpoint：{ok}/{total} 指标成功，等用户确认` |
| 2 (success) | `🎉 报表已生成：report.md / report.docx（{status}）` |
| 8d.5 | `🚦 Checkpoint：描述 {ok}/{total} 成功，等用户确认` |
