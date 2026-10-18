# Description Reports

`scripts/run_loop.py` emits `test_results: null` when holdout is disabled.
`scripts/generate_report.py` treats it as an empty result list. Preserve training
scores and held-out query columns when test results are present.
Offline rendering and CLI regressions: `tests/skills/test_skill_creator_report.py`
at the repository root.
