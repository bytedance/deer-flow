# ai-report Pipeline Reference

Read this when running the full `ai-report` workflow or changing its step contract.

## State machine

```text
0 lint → 1 lint checkpoint
→ 2 parse → 3 query → 3.5 query checkpoint
→ 4 assemble-wide (DuckDB PIVOT + Decimal unit-convert)
→ 6 extract-ir → 7 codegen (agent-turn-LLM) → 8a validate → 8b evaluate → 8c apply-computed
→ 10 unit_convert (Python Decimal precision pass on aggregate values)
→ 11 describe (agent-turn-LLM) → 11.5 description checkpoint
→ 12 preview checkpoint → 13 save approved run → 13.5 post-section checkpoint
→ 14 render markdown → 15 render docx → 16 status + 中文回执
```

Step numbers intentionally diverge from chatbi-report where ai-report needs
extra steps. Step 10 (unit_convert) is separate from Step 4 (assemble-wide)
because ai-report handles multi-row header inheritance of `data_unit` (parent
→ leaf cells); Step 4 does the basic PIVOT in DECIMAL(38,10) precision and
Step 10 does the post-PIVOT Python Decimal pass on aggregate / computed columns.

## Step types

| Type | Meaning | Steps |
|---|---|---|
| `bash` | deterministic CLI in sandbox | 0, 2, 3, 4, 6, 8a, 8b, 8c, 10, 13, 14, 15, 16 |
| `agent-turn-LLM` | lead agent writes files using LLM output | 7, 11 |
| `agent-turn-checkpoint` | lead agent calls `ask_clarification` and waits for user | 1, 3.5, 11.5, 12, 13.5 |

## Step definitions

| Step | Type | Command / owner | Output |
|---|---|---|---|
| 0 lint | bash | `python /mnt/skills/public/ai-report/scripts/md_lint.py /mnt/user-data/uploads/<file>.md` | LintReport to stdout |
| 1 lint checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply |
| 2 parse | bash | `python /mnt/skills/public/ai-report/scripts/parse_md.py --md /mnt/user-data/uploads/<file>.md --out /mnt/user-data/outputs/<stem>.parsed.json` | `<stem>.parsed.json` |
| 3 query | bash | `python /mnt/skills/public/ai-report/scripts/sqlbot_client.py query --parsed /mnt/user-data/outputs/<stem>.parsed.json --mock\|--base-url ... --out /mnt/user-data/outputs/<stem>.query.json` | `<stem>.query.json` |
| 3.5 query checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply |
| 4 assemble-wide | bash | `python /mnt/skills/public/ai-report/scripts/assemble_wide_duckdb.py --parsed <stem>.parsed.json --query <stem>.query.json --out /mnt/user-data/outputs/<stem>.wide.json` | `<stem>.wide.json` (DuckDB PIVOT, DECIMAL precision, failed cells = None) |
| 6 extract-ir | bash | `python /mnt/skills/public/ai-report/scripts/compute.py extract-ir --parsed <stem>.parsed.json --out /mnt/user-data/outputs/<stem>.ir.json` | `<stem>.ir.json` |
| 7 codegen | agent-turn-LLM | read `prompts/compute_codegen.md` + `<stem>.ir.json`; write `<stem>.compute.<slug>.sql` | DuckDB SQL files |
| 8a validate | bash | `python /mnt/skills/public/ai-report/scripts/compute.py validate --sql <file> --wide <stem>.wide.json [--example-input ... --example-expected ...]` | exit 0/3 |
| 8b evaluate | bash | `python /mnt/skills/public/ai-report/scripts/compute.py evaluate --sql <file> --wide <stem>.wide.json --name <col> --out <stem>.computed.<slug>.json` | computed JSON files |
| 8c apply-computed | bash | `python /mnt/skills/public/ai-report/scripts/compute.py apply-computed --wide <stem>.wide.json --computed <stem>.computed.<slug>.json --out <stem>.wide.merged.json` | updated `<stem>.wide.json` |
| 10 unit_convert | bash | `python /mnt/skills/public/ai-report/scripts/unit_convert.py apply --wide <stem>.wide.merged.json --headers <stem>.parsed.json --out <stem>.wide.final.json` | Decimal-converted `<stem>.wide.json` |
| 11 describe | agent-turn-LLM | read `prompts/description_gen.md` + `<stem>.wide.final.json`; write `<stem>.description.<slug>.txt` | description text files |
| 11.5 description checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply |
| 12 preview checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply |
| 13 save approved run | bash | `python /mnt/skills/public/ai-report/scripts/save_approved_run.py --input <stem>.approved.json --db-path /mnt/ai-report-data/duckdb` | `approved_runs` row |
| 13.5 post-section checkpoint | agent-turn-checkpoint | see `checkpoints.md` | user reply |
| 14 render markdown | bash | `python /mnt/skills/public/ai-report/scripts/render_markdown.py --report-id <id> --db-path /mnt/ai-report-data/duckdb --out-dir /mnt/ai-report-data` | `<report_id>.report.md` |
| 15 render docx | bash | `python /mnt/skills/public/ai-report/scripts/render_docx.py --report-id <id> --db-path /mnt/ai-report-data/duckdb --out-dir /mnt/ai-report-data` | `<report_id>.report.docx` |
| 16 status + 回执 | bash | `python /mnt/skills/public/ai-report/scripts/assemble_status.py --report-id <id> --db-path /mnt/ai-report-data/duckdb --out /mnt/ai-report-data/<id>.status.json` | `<report_id>.status.json` + 中文回执 |

## Retry budget

| Step | Automatic retry / repair limit | After limit |
|---|---:|---|
| 0 lint | 0 | stop, show lint errors and fixes |
| 2 parse | 0 | stop, show parse error and fix |
| 3 query | SQLBot client internal retry only (3× exp) | failed cells become sentinels; pipeline continues after 3.5 user decision |
| 4 assemble-wide | 0 | stop, show PIVOT error |
| 6 extract-ir | 0 | stop, show regex mismatch |
| 7 codegen | one initial draft per spec | 8a decides retry (max 1) |
| 8a validate | one re-codegen per spec | failed column becomes `⚠️COMPUTE_FAILED`; continue |
| 8b evaluate | 0 | eval errors → `⚠️COMPUTE_FAILED`; continue |
| 10 unit_convert | 0 | stop, show Decimal parse error |
| 11 describe | one regenerate per report | failed description file contains `⚠️DESCRIPTION_FAILED`; continue |
| 13 save | 0 | stop, show DuckDB error |
| 14-16 render | 0; if only description missing, rerun Step 11 once | stop on remaining failure |

Checkpoint steps (1, 3.5, 11.5, 12, 13.5) are not retry loops. If user stops,
the section ends with `USER_ABORTED`; user edits the source MD and reruns.

Step 3.5 always triggers, even when `ok == 0` — fail-fast disabled
(per 2026-06-27 policy reversal). The user picks between partial-with-sentinel
and stop-and-investigate at every query checkpoint.