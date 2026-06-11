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

Layer 2 also hosts **cross-stack contract scenarios** — the dangerous class
where a backend change silently breaks a frontend assumption and *both sides'
unit tests stay green*. See below.

## Cross-stack scenario: multi-run render order (`multi-run-order.spec.ts`)

Regression guard for issue **#3352** (after context compression, refreshing a
thread rendered history out of order). Root cause was a front-back desync:
backend `RunManager.list_by_thread` returns runs **newest-first** (PR #2932),
while the frontend (`core/threads/hooks.ts`) iterated runs and **prepended** each
loaded page — inverting chronological order once the checkpoint no longer held
the older messages. The backend ordering test was green throughout, and the
frontend regression unit test hardcodes "backend returns newest-first" in a mock,
so only a *real frontend against a real backend* catches the desync.

This scenario does **not** record a conversation. It uses a **test-only seeder**
(`tests/seed_runs_router.py`, mounted on the replay gateway only when
`DEERFLOW_ENABLE_TEST_SEED=1`) to stand up a thread with ≥2 runs and per-run
message events — and deliberately **no checkpoint**, which is the #3352
precondition: it forces the frontend's per-run reload path to be the sole source
of truth so the ordering bug becomes observable. The seeder writes through the
gateway's own run/event stores using the request's auth context, so the real
`list_by_thread` → `/runs/{id}/messages` → prepend path runs live. Reverting the
#3354 frontend fix turns this spec red.

## How replay works

`tests/replay_provider.py::ReplayChatModel` returns recorded assistant turns keyed
by a **normalized hash of the model caller + conversation**. The conversation is
human / ai / tool messages — role, text, tool-call name+args; with
`<system-reminder>`, dates, UUIDs, tmp paths stripped. The caller is the stable
source of the model call (`lead_agent`, `middleware:title`, `suggest_agent`,
`subagent:*`, etc.). A miss raises loudly rather than passing silently.

**The system prompt is excluded from the match key.** The lead-agent system
prompt is a living, frequently-edited implementation detail — its wording changes
across PRs (e.g. #3195 added a "File Editing Workflow" section). Hashing it would
make every fixture go stale and red-fail unrelated PRs the moment anyone edits the
prompt. The conversation flow (user input → tool calls → results → answer) is the
stable contract that identifies a recorded turn. The caller still stays in the
key so two different model users with identical conversation text do not compete
for the same replay bucket. (This mirrors how open-design's mock picker keys on
the user prompt, not the system internals.) Combined with pinning skills +
extensions empty and disabling memory/summarization
(`tests/_replay_fixture.py::build_config_yaml`), a fixture replays the same across
machines, days, prompt edits, and CI. Replaying needs **no API key**.

A swallowed hash-miss keeps the SSE *event shapes* identical (the gateway wraps it
into a normal assistant error message), so the Layer-1 golden can't catch a miss
by shape alone — it inspects `replay_provider.replay_misses()` and fails loud
instead. Layer-2 already fails on a miss (the recorded turns never render).

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
