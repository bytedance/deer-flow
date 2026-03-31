# GREEN LOG - DeerFlow Core Hardening

- Date: `2026-03-31`
- Phase: `GREEN`
- Scope: `P1 output profile contract refactor in deep_research.py`

## Commands

```bash
python -m py_compile backend/packages/harness/deerflow/pilot/deep_research.py backend/tests/test_deep_research_pilot.py scripts/run_deep_research_pilot.py
```

```bash
docker run --rm -v D:/project/research-agentic/deer-flow:/repo -w /repo/backend docker-gateway sh -lc "PYTHONPATH=.:packages/harness /app/backend/.venv/bin/python -m pytest tests/test_deep_research_pilot.py -q"
```

## Result

- `8 passed`
- No failing test in `backend/tests/test_deep_research_pilot.py`

## What is now green

1. Canonical profile contract accepts `default`, `founder`, `operator`.
2. Legacy aliases `founder_memo` and `operator_memo` normalize to canonical names.
3. `--profile` is the primary CLI parameter; legacy `--output-profile` remains compatible.
4. Operator summary shaping still strips metadata-heavy lines after profile normalization.
