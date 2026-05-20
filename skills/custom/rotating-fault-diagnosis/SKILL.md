---
name: rotating-fault-diagnosis
description: Use this skill when the user wants the rotating machinery diagnosis entry scripts isolated from data-analyst. This skill wraps the rotating diagnosis CLI entry points without modifying `skills/custom/data-analyst/`.
metadata:
  emoji: "⚙️"
---

# Rotating Fault Diagnosis

Use this skill to invoke the rotating diagnosis entry scripts under its own skill boundary.

## When to Use This Skill

Use this skill when the user:

- Needs the rotating machinery diagnosis pipeline entry scripts
- Wants the rotating diagnosis flow kept separate from `data-analyst`
- Needs a stable wrapper for the real rule runtime, payload mapping, or report export

## Preconditions

- The workspace contains `skills/custom/data-analyst/`
- The runtime can execute `python3`
- The current user token is available as `INS_ACCESS_TOKEN` or `--access-token`
- `INS_BASE_URL` may be provided via `config.yaml` or left at the tool default

## Execution Rules

- Prefer the wrapper scripts in this skill directory
- Do not modify `skills/custom/data-analyst/`
- Prefer `run_rotating_rule_diagnosis.py` → `build_rotating_report_payload.py` → `export_report.py`
- Return the underlying script output directly unless the user asks for summarization

## Scripts

- `scripts/run_rotating_rule_diagnosis.py`
- `scripts/build_rotating_report_payload.py`
- `scripts/export_report.py`
- `scripts/query_diagnosis.py`
- `scripts/diagnosis_features.py`
- `scripts/run.sh`

## Notes

- This skill is a boundary wrapper for the rotating diagnosis entry points
- It keeps the Agent-facing scripts separate while reusing the existing implementation under the hood
