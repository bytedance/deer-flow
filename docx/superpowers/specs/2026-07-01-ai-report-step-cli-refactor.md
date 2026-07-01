# ai-report Step-CLI Refactor — Design Spec

**Date**: 2026-07-01
**Status**: Draft (awaiting user review)
**Owners**: ai-report skill maintainers
**Related memory**: [[ai-report-new-skill-not-replacement]], [[ai-report-global-duckdb-path]], [[ai-report-phase1-unit-sandbox]], [[ai-report-layout-aware-data-unit]], [[ai-report-chatbi-style-md-blocks]], [[chatbi-report-fail-fast-query]], [[no-skill-parallel-orchestrators]]

## Background

`skills/public/ai-report/scripts/design_pipeline.py` currently exposes a
monolithic `run_report(store, sqlbot, md_path)` API plus three module-level
injection seams (`_llm_codegen`, `_llm_describe`, `_checkpoint`) that raise
`NotImplementedError` by default. The runtime (`runtime_pipeline.py`)
analogously ships a single `RuntimePipeline.run_report(report_id)` CLI.

The contract assumes the caller (lead agent) can:

1. Hold in-process Python state (Store, MockSQLBotClient, monkey-patched hooks).
2. Reach back to the lead agent's tool surface from inside the script
   (the `ask_clarification` tool cannot be invoked from a `bash` subprocess).

In practice, DeerFlow's lead agent has only `bash` + a top-level
`ask_clarification` — no shared in-process Python bridge. The mismatch
forces callers to either write bespoke wrappers (e.g. the deleted
`_orchestrator/` directory) or fail at the first checkpoint with
`NotImplementedError`. This spec replaces the monolithic pipeline with the
step-by-step CLI pattern that `chatbi-report` already uses successfully.

## Goals

1. **No in-process Python bridge required.** Every step is a CLI script
   invocable via `bash`. The lead agent orchestrates by sequencing CLI calls
   and inserting `ask_clarification` calls between steps.
2. **Mirrors `chatbi-report` architecture.** State machine, step types
   (`bash` / `agent-turn-LLM` / `agent-turn-checkpoint`), and contract names
   align 1:1 with `skills/public/chatbi-report/references/pipeline.md`.
3. **`Decimal(38,10)` precision preserved across all steps.** Arithmetic,
   PIVOT, and unit conversion stay inside DuckDB SQL; no `float` round-trips.
4. **Phase 1 sentinel contract preserved.** Failing cells render as empty;
   `approved_runs.sentinels` carries `⚠️QUERY_FAILED` / `⚠️CAST_FAILED`
   / `⚠️COMPUTE_FAILED` codes (matches `build_status` by-code aggregator).
5. **DuckDB and approved-run storage stay global** (`/mnt/ai-report-data/duckdb`).
   Intermediate JSON files move to per-thread `/mnt/user-data/outputs/<stem>.*`
   to match `chatbi-report` and to give each thread its own scratch space.

## Non-Goals

- No change to SQLBot wire format (1:1 mirror of chatbi-report).
- No code reuse from `chatbi-report/`; ai-report scripts remain independent.
- No new analysis dimensions, columns, or business interpretation.
- No migration of historical data — prior `approved_runs` rows stay in the
  global DuckDB; only the production code path changes.
- No changes to the `SKILL.md` frontmatter description or trigger rules
  (only the body and references are rewritten).

## Architecture

### State machine (mirrors chatbi-report)

```text
0 lint → 1 lint checkpoint
→ 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide (DuckDB PIVOT + decimal unit-convert)
→ 6 extract-ir → 7 codegen (agent-turn-LLM) → 8a validate → 8b evaluate → 8c apply-computed
→ 10 unit_convert (Python Decimal precision pass on aggregate values)
→ 11 describe (agent-turn-LLM) → 11.5 description checkpoint
→ 12 preview checkpoint → 13 save approved run → 13.5 post-section checkpoint
→ 14 render markdown → 15 render docx → 16 build status + 中文回执
```

Step numbers intentionally diverge from chatbi-report where ai-report needs
extra steps (10 unit_convert is separate from 4 assemble-wide because
ai-report handles multi-row header inheritance — see
[[ai-report-layout-aware-data-unit]]).

### Step table (canonical contract)

| Step | Type | Owner | Input | Output | Exit codes / sentinels |
|---|---|---|---|---|---|
| 0 lint | bash | `scripts/md_lint.py` | `<md>` | stdout LintReport | `0`=clean, `1`=errors |
| 1 lint checkpoint | agent-turn-checkpoint | lead agent | LintReport | user reply | continue / stop |
| 2 parse | bash | `scripts/parse_md.py` | `<md>` | `<stem>.parsed.json` | `0`, errors → stop |
| 3 query | bash | `scripts/sqlbot_client.py query` | `<stem>.parsed.json` | `<stem>.query.json` | `0`, transient retry (3× exp), `SQLBotError`→`⚠️QUERY_FAILED` |
| 3.5 query checkpoint | agent-turn-checkpoint | lead agent | query summary | user reply | continue (with sentinel) / stop |
| 4 assemble-wide | bash | `scripts/assemble_wide_duckdb.py` | `query.json` + `parsed.json` | `<stem>.wide.json` | `0`; widen failures → `⚠️CAST_FAILED` |
| 6 extract-ir | bash | `scripts/extract_ir_duckdb.py` | `parsed.json` | `<stem>.ir.json` | `0` |
| 7 codegen | agent-turn-LLM | lead agent | `ir.json` + `prompts/compute_codegen.md` | `<stem>.compute.<slug>.sql` (DuckDB SQL, not Python) | one initial + one retry |
| 8a validate | bash | `scripts/compute.py validate` | `compute.sql` + `wide.json` | validate report | `0`=OK, `1`→retry (max 1) then `⚠️COMPUTE_FAILED` |
| 8b evaluate | bash | `scripts/compute.py evaluate` | `compute.sql` + `wide.json` | `computed.<slug>.json` | `0`, eval errors → `⚠️COMPUTE_FAILED` |
| 8c apply-computed | bash | `scripts/compute.py apply-computed` | `wide.json` + `computed/*.json` | `wide.json` (updated) | `0` |
| 10 unit_convert | bash | `scripts/unit_convert.py apply` | `wide.json` + `parsed.json` (headers_2d) | `wide.json` (updated) | `0`; Decimal precision locked |
| 11 describe | agent-turn-LLM | lead agent | `wide.json` + `prompts/description_gen.md` + description_prompt | `<stem>.description.<slug>.txt` | one regenerate → `⚠️DESCRIPTION_FAILED` |
| 11.5 description checkpoint | agent-turn-checkpoint | lead agent | description summary | user reply | continue / stop |
| 12 preview checkpoint | agent-turn-checkpoint | lead agent | preview dict | user reply | approve / modify / reject |
| 13 save approved run | bash | `scripts/save_approved_run.py` | preview + sentinels | `approved_runs` row (DuckDB) | `0` |
| 13.5 post-section | agent-turn-checkpoint | lead agent | section summary | user reply | continue / jump / preview / done |
| 14 render markdown | bash | `scripts/render_markdown.py --report-id <id> --db-path ...` | (reads `approved_runs` from DuckDB) | `<report_id>.report.md` | `0` |
| 15 render docx | bash | `scripts/render_docx.py --report-id <id> --db-path ...` | (reads `approved_runs` from DuckDB) | `<report_id>.report.docx` | `0` |
| 16 status + 回执 | bash | `scripts/assemble_status.py --report-id <id> --db-path ...` | (reads `approved_runs` from DuckDB) | `<report_id>.status.json` + 中文回执 | `0` |

The "agent-turn-LLM" rows are run by the lead agent itself: it reads the
prompt, reads the input file, calls `create_chat_model`, writes the
artifact. The "agent-turn-checkpoint" rows are pure `ask_clarification`
calls in the agent process — no subprocess needed.

### Files

#### Deleted (2)

- `scripts/design_pipeline.py` — monolithic `DesignPipeline` class, internal
  hooks (`_llm_codegen` / `_llm_describe` / `_checkpoint`), `run_section()`,
  module-level `run_report()`.
- `scripts/runtime_pipeline.py` — monolithic `RuntimePipeline` class and CLI.

#### Added CLI (4 existing files gain `def main()`)

- `scripts/parse_md.py` → `--md <path> --out <path>` writes
  `<stem>.parsed.json` (sections, all_idx_ids, org_contexts, time_info,
  headers_2d, compute_block_md, description_prompt). Calls existing
  `parse_markdown()` unchanged.
- `scripts/compute.py` → 5 subcommands mirroring chatbi-report's CLI:
  - `compute.py assemble-wide --query ... --parsed ... --out <wide.json>`
  - `compute.py extract-ir --parsed ... --out <ir.json>`
  - `compute.py validate --sql <file> --wide <json> [--example-input ...] [--example-expected ...]`
  - `compute.py evaluate --sql <file> --wide <json> --name <col> --out <computed.json>`
  - `compute.py apply-computed --wide <json> --computed-dir <dir>`
- `scripts/assemble_status.py` → `--db-path ... --report-id ...` writes
  `<report_id>.status.json` and prints 中文回执 (mirrors Step 16).
- `scripts/unit_convert.py` → new `apply` subcommand:
  `unit_convert.py apply --wide ... --headers <parsed.json> --out ...`.
  Reuses existing `apply_units()` library.

#### Added (new files)

- `scripts/assemble_wide_duckdb.py` — DuckDB-native wide-table assembler
  (replaces the in-memory pandas logic from chatbi-report). PIVOT path:
  `SELECT branch_num, MAX(CASE WHEN period=... THEN numeric_value END) ...`
  with `MAX(DECIMAL)` to preserve precision. Output JSON schema matches
  chatbi-report's `<stem>.wide.json`.
- `scripts/extract_ir_duckdb.py` — reads `> 计算:` blocks from
  `parsed.json` (already decoded by `parse_md.py`) and writes the same
  ComputeIR JSON chatbi-report would. No SQL execution.
- `scripts/save_approved_run.py` — small CLI around
  `Store.save_approved_run()` so Step 13 can run via `bash`.

#### Unchanged (already CLI-ready)

- `scripts/md_lint.py` (already has CLI; verify Step 0 contract).
- `scripts/sqlbot_client.py` (`query` subcommand already present).
- `scripts/render_markdown.py` (already CLI).
- `scripts/render_docx.py` (already CLI).
- `scripts/duckdb_store.py` — library, no CLI needed.

#### Documentation (3 files)

- `SKILL.md` — body rewritten as the 17-step state machine + step table;
  frontmatter `description` and `触发匹配规则` retained verbatim. Section
  "Pipeline 快速预览" replaced by reference to `references/pipeline.md`.
- `references/pipeline.md` — full rewrite as a step × `{type, command,
  output}` table mirroring chatbi-report.
- `references/checkpoints.md` — keep content; renumber references from
  `8d.5` to `11.5` (description) and split preview/post-section into `12` /
  `13.5`.

#### Tests (rewrite)

- `tests/test_e2e_sample.py` → rewrite to drive the new step CLIs
  via `subprocess.run([sys.executable, "scripts/parse_md.py", ...])` and
  assert on intermediate JSON + final outputs. Existing assertions on
  5-section approval, status='ok', document content stay.
- `tests/test_runtime_pipeline.py` → delete; cover the same contract via
  `tests/test_render_markdown.py`, `tests/test_render_docx.py`,
  `tests/test_assemble_status.py` updates.
- `tests/test_design_pipeline.py` → delete; split into per-step tests
  (`test_parse_md.py`, `test_compute.py`, `test_save_approved_run.py`).
- New: `tests/test_assemble_wide_duckdb.py`,
  `tests/test_extract_ir_duckdb.py` — lock the DuckDB Decimal precision
  (Phase 1 invariant).

## Data contracts

### Output paths (per-thread + global split)

| Artifact | Path | Owner | Lifetime |
|---|---|---|---|
| `<stem>.parsed.json` | `/mnt/user-data/outputs/<stem>.parsed.json` | Step 2 | per-thread |
| `<stem>.query.json` | `/mnt/user-data/outputs/<stem>.query.json` | Step 3 | per-thread |
| `<stem>.wide.json` | `/mnt/user-data/outputs/<stem>.wide.json` | Steps 4, 8c, 10 | per-thread |
| `<stem>.ir.json` | `/mnt/user-data/outputs/<stem>.ir.json` | Step 6 | per-thread |
| `<stem>.compute.<slug>.sql` | `/mnt/user-data/outputs/<stem>.compute.<slug>.sql` | Step 7 | per-thread |
| `<stem>.computed.<slug>.json` | `/mnt/user-data/outputs/<stem>.computed.<slug>.json` | Step 8b | per-thread |
| `<stem>.description.<slug>.txt` | `/mnt/user-data/outputs/<stem>.description.<slug>.txt` | Step 11 | per-thread |
| DuckDB file | `/mnt/ai-report-data/duckdb/ai-report.duckdb` | global | persistent across threads |
| `<report_id>.design.md` | `/mnt/ai-report-data/<report_id>.design.md` | Step 13 | persistent |
| `<report_id>.report.md` | `/mnt/ai-report-data/<report_id>.report.md` | Step 14 | persistent |
| `<report_id>.report.docx` | `/mnt/ai-report-data/<report_id>.report.docx` | Step 15 | persistent |
| `<report_id>.status.json` | `/mnt/ai-report-data/<report_id>.status.json` | Step 16 | persistent |

`<stem>` matches `make_report_id(md_path)[:16]` (or the full hash; pick one
in the plan and lock via test).

### Intermediate JSON schemas

`<stem>.parsed.json`, `<stem>.query.json`, `<stem>.wide.json`,
`<stem>.ir.json` schemas match chatbi-report's `<stem>.{parsed,query,wide,ir}.json`
schemas byte-for-byte. A test
(`tests/test_intermediate_schemas.py`) locks this equivalence.

### Approved-run row (unchanged)

Step 13 writes via `Store.save_approved_run()` — the existing schema
(`wide_table`, `computed_columns`, `descriptions`, `sentinels`, `status`)
is preserved.

## Agent orchestration contract

The lead agent, when triggered to run ai-report:

1. Reads `SKILL.md` to learn the high-level shape and load the right
   `references/*.md` based on the user's ask.
2. Sequentially runs step CLIs via `bash`:
   ```text
   python /mnt/skills/public/ai-report/scripts/md_lint.py <md>
   python /mnt/skills/public/ai-report/scripts/parse_md.py <md> --out <parsed.json>
   python /mnt/skills/public/ai-report/scripts/sqlbot_client.py query --parsed <parsed.json> --mock --out <query.json>
   ...
   ```
3. Between data-producing CLI steps, calls `ask_clarification` for each
   checkpoint (Steps 1, 3.5, 11.5, 12, 13.5), with the exact Chinese
   question and options from `references/checkpoints.md`.
4. For Steps 7 and 11, the agent itself reads `prompts/compute_codegen.md`
   (or `description_gen.md`), reads the relevant JSON, calls
   `create_chat_model` via the LLM tool surface, and writes the artifact
   to the indicated path. Failure path: missing artifact → `⚠️COMPUTE_FAILED`
   or `⚠️DESCRIPTION_FAILED`.

Failure handling per step is identical to chatbi-report's table (see
`references/pipeline.md` § "Retry budget" in this design).

## Test strategy

### Unit + integration

- Existing unit tests for `parse_md`, `compute` (function-level) stay and
  gain a CLI wrapper.
- New `tests/test_assemble_wide_duckdb.py`: locks PIVOT result against a
  fixture with known `BAS_0263@2023`/`BAS_0263@2024` rows and verifies
  Decimal precision (no `float` cast).
- New `tests/test_extract_ir_duckdb.py`: locks ComputeIR JSON shape.

### End-to-end (rewrite)

- `tests/test_e2e_sample.py` becomes: drive Steps 0 → 16 as CLI invocations,
  assert on `<report_id>.report.md`, `<report_id>.report.docx`,
  `<report_id>.status.json`, and DuckDB `approved_runs` rows.
- Run with `pytest tests/test_e2e_sample.py -v` from `skills/public/ai-report/`.

### Verification commands

```bash
# unit
cd skills/public/ai-report && pytest tests/test_parse_md.py tests/test_compute.py \
  tests/test_assemble_wide_duckdb.py tests/test_extract_ir_duckdb.py \
  tests/test_render_markdown.py tests/test_render_docx.py \
  tests/test_assemble_status.py tests/test_sentinels.py -v

# e2e
cd skills/public/ai-report && pytest tests/test_e2e_sample.py -v

# interaction script (manually trigger every checkpoint against the
# fixture, exercising ask_clarification: simulate by piping user replies)
```

After all tests pass: `git status` should show no stray files in
`backend/.deer-flow/ai-report/_orchestrator/` (i.e. no regression to the
"_orchestrator" anti-pattern).

## Migration plan

1. **Phase A — Add CLI wrappers (additive)**: each existing function gets
   a `def main()` + argparse + `if __name__ == "__main__"` block. No
   behavior change. Existing tests still pass against the function API.
2. **Phase B — Add new step scripts**: `assemble_wide_duckdb.py`,
   `extract_ir_duckdb.py`, `save_approved_run.py`. Plus unit tests for
   each.
3. **Phase C — Rewrite SKILL.md + references**: publish the new step-by-step
   recipe. SKILL.md frontmatter description unchanged.
4. **Phase D — Rewrite tests**: `test_e2e_sample.py` switches to driving
   CLIs; delete `test_design_pipeline.py` + `test_runtime_pipeline.py`;
   split coverage into per-step tests.
5. **Phase E — Delete monolithics**: remove `design_pipeline.py` and
   `runtime_pipeline.py` in the same commit. The deletion is now safe
   because every behavior is covered by per-step tests.
6. **Phase F — Verification**: run the e2e test, screenshot final outputs,
   confirm `_orchestrator/` does not reappear.

Each phase is one commit. Phases A-D can merge without breaking callers
(monolithics still exist during A-D); E is the cutover.

## Open questions

1. **`/mnt/user-data/outputs/` permission**: per-thread dirs are created
   by `ThreadDataMiddleware` only when uploads exist. Need to confirm
   intermediate JSON writes succeed when the user only invokes ai-report
   without uploading anything. (Likely resolved by always-creating the
   `outputs/` subdir, but verify in plan.)

2. **`<stem>` derivation**: `make_report_id(md_path)` is `sha256(path)[:16]`.
   chatbi-report uses `<stem>` derived from filename. Pick one and lock
   via test.

3. **`describe` ↔ checkpoint timing**: chatbi-report's describe is Step 8d,
   before apply-computed (8c). ai-report's current pipeline runs describe
   after apply-computed + unit_convert (Step 11). The state machine in this
   spec preserves the ai-report order — confirm during plan review.

## Out-of-scope follow-ups (not in this spec)

- Add an `inputs/` schema validator for MD templates (separate spec if
  needed; current lint covers basics).
- Replace manual sandbox path resolution with `LocalSandbox` PathMapping
  reuse (deferred; not blocking this refactor).
- Redis-backed run-event tracking (separate spec).
