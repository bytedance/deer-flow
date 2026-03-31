# RED LOG - DeerFlow Core Hardening

- Date: `2026-03-31`
- Phase: `RED`
- Scope: `P1 output profile contract refactor in deep_research.py`

## Command

```bash
docker run --rm -v D:/project/research-agentic/deer-flow:/repo -w /repo/backend docker-gateway sh -lc "PYTHONPATH=.:packages/harness /app/backend/.venv/bin/python -m pytest tests/test_deep_research_pilot.py -q"
```

## Result

- Status: `FAILED`
- Summary: `3 failed, 5 passed`

## Failing tests

1. `test_builds_prompt_and_persists_artifact_result`
   - `output_profile="founder"` rejected by validation.
2. `test_normalizes_legacy_profile_aliases`
   - legacy `founder_memo` not normalized to canonical `founder`.
3. `test_operator_profile_short_summary_ignores_metadata_lines`
   - `output_profile="operator"` rejected by validation.

## Diagnosis

Current contract only accepts `default`, `founder_memo`, `operator_memo`.
Task brief requires canonical modes compatible with `--profile=founder` and `--profile=operator`.
