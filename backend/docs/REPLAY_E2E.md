# Record/Replay E2E — front-back contract verification

Deterministic, **key-free** end-to-end checks that a backend change can't
silently break the frontend (and vice-versa). Two complementary layers, fed by a
single recording.

## Why

The mock-based frontend e2e hand-writes the backend's JSON/SSE, so a backend
schema or SSE change passes green ("fake green"). These layers replay a recorded
**real** run against the **real** backend (and, for Layer 2, the real frontend),
so contract drift turns the build red instead.

## The two layers

- **Layer 1 — backend golden** (`tests/test_replay_golden.py`): replays a fixture
  through the real FastAPI gateway with `ReplayChatModel` and asserts the streamed
  SSE event sequence equals a committed golden. Fast, no browser. Guards protocol
  *shape*.
- **Layer 2 — full-stack render** (`frontend/tests/e2e-real-backend/`): real
  Next.js + real gateway (replay model) + Chromium; asserts the replayed
  auto-title and a follow-up suggestion render in the browser. Guards semantic
  *render*. (Complementary to Layer 1 — neither subsumes the other.)

## How replay works

`tests/replay_provider.py::ReplayChatModel` returns recorded assistant turns keyed
by a **normalized hash** of the model input (strips `<system-reminder>`, dates,
UUIDs, tmp paths). A miss raises loudly rather than passing silently. The system
prompt is made environment-independent by pinning skills + extensions empty and
disabling memory/summarization (`tests/_replay_fixture.py::build_config_yaml`), so
a fixture replays the same across machines, days, and CI. Replaying needs **no
API key**.

## Record a new scenario (needs a real key — dev machine only)

Recording drives the **real frontend** so captured inputs match exactly what the
browser sends; fixtures contain no API key.

```bash
# 1. drive the real frontend against a real-model gateway, capturing model calls
OPENAI_API_KEY=... OPENAI_API_BASE=<openai-compatible-endpoint>/v1 \
  DEERFLOW_RECORD_OUT=/tmp/rec/turns.jsonl RECORD_MODEL=<model> \
  bash -c 'cd frontend && pnpm exec playwright test -c playwright.record.config.ts'

# 2. stitch the capture into a fixture
cd backend && uv run python scripts/build_fixture_from_jsonl.py \
  --jsonl /tmp/rec/turns.jsonl --meta /tmp/rec/turns.jsonl.meta.json \
  --out tests/fixtures/replay/<scenario>.<mode>.json --model <model>

# 3. regenerate the committed golden
DEERFLOW_WRITE_GOLDEN=1 PYTHONPATH=. uv run pytest tests/test_replay_golden.py
```

## Run (no key)

```bash
cd backend  && PYTHONPATH=. uv run pytest tests/test_replay_golden.py          # Layer 1
cd frontend && pnpm exec playwright test -c playwright.real-backend.config.ts  # Layer 2
```

## CI

`.github/workflows/replay-e2e.yml` runs both layers on changes to **either** side
of the contract (`frontend/**`, `backend/app/gateway/**`,
`backend/packages/harness/**`, fixtures). DOM assertions are the gate; the rendered
screenshot + Playwright HTML report are uploaded as a CI artifact.

## Known limitations

- Visual regression baselines are OS-specific, so they are a **local dev gate
  only** (gitignored); CI uploads the render as an artifact for human review
  instead of hard-asserting a cross-OS baseline.
- Fixtures are coupled to the recording-time prompt; if new
  environment-dependent content enters the system prompt, extend the
  normalization in `replay_provider.py` (or pin it in `build_config_yaml`).
- Re-record a scenario if the agent graph changes how many model calls it makes
  — the replay raises loudly on a hash miss pointing at the divergence.
