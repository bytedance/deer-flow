---
name: blocking-io-guard
description: Ensure async-path backend code that could block the asyncio event loop is protected by a teeth-verified runtime anchor in tests/blocking_io/. Use when changing backend Python under app/, packages/harness/deerflow/, or scripts/, when running a blocking-IO triage round over the whole repo, or when a reviewer/CI asks for blocking-IO coverage. Runs a deterministic scan (changed-lines or full-repo), routes each candidate, drafts/extends an anchor, and proves it fails when the blocking IO regresses.
---

# Blocking-IO Guard Skill

Help a contributor ship backend async changes together with the runtime anchor
that lets DeerFlow's blocking-IO CI gate actually see the new code. The dynamic
detector only catches blocking IO on paths a test executes — this skill closes
that gap, either for your own diff or for a repo-wide triage round.

Read `references/good-anchor-rules.md` before writing any anchor.
`references/sop-skeleton.md` documents the generic shape (for future reuse); the
operational steps below are the blocking-IO instance.

## When to use

- Your change touches Python under `backend/app/`,
  `backend/packages/harness/deerflow/`, or `backend/scripts/` and may run on
  the async event loop (Mode A). If unsure, run Step 0 — it answers
  deterministically.
- You are doing a maintenance triage round over the existing codebase
  (Mode B).

## SOP (router)

### Step 0 — Scope (deterministic, L1)

**Mode A — your own diff** (default, pre-PR). From repo root:

```bash
uv run --project backend python scripts/scan_changed_blocking_io.py --base origin/main
```

Lists blocking-IO candidates that fall on lines your change added/modified.
If empty, stop: this change has no blocking-IO surface.

**Mode B — full-repo triage round.** From repo root:

```bash
uv run --project backend python scripts/detect_blocking_io_static.py --format json
```

Produces the complete structured finding list. Work HIGH priority first; do
not start MEDIUM until every HIGH is dispositioned (fixed, guarded, or
recorded NO-ACTION). Batch a round to a handful of findings so each lands
reviewable.

Both modes emit the same JSON shape per finding: `priority`, `location`
(path/line/function), `blocking_call` (category/operation/symbol),
`event_loop_exposure`, `reason`, `code`.

### Step 1 — Judge each candidate (router)

Read the code around each candidate and route it:

- **Already offloaded** (`asyncio.to_thread`, `run_in_executor`, async client) →
  **GUARD**: add/extend an anchor that locks the offload so a future edit cannot
  move it back onto the loop.
- **On the loop, not offloaded** → **FIX+ANCHOR**: offload the production code
  (your fix), then add an anchor that guards it.
- **Not actually exposed / acceptable** (rare: L1 false positive, startup-only
  code) → **NO-ACTION**: record one line of why.
- **Cross-file caveat**: static reachability is same-file only
  (`ASYNC_REACHABLE_SAME_FILE`). If the candidate is a *sync helper*, check for
  async callers in other files (codegraph or `git grep`) before deciding
  NO-ACTION.

### Step 2 — Check existing anchors

Look in `backend/tests/blocking_io/` for a test that drives the production async
entry point reaching this candidate's branch.

- Covers this branch already → go to Step 4 (re-verify teeth).
- Covers the entry point but not this branch (e.g. happy path covered,
  cleanup/404/409 not) → **extend** that anchor.
- None → create one from `templates/anchor.template.py`.

### Step 3 — Generate / extend the anchor

Follow `references/good-anchor-rules.md`. Drive the *specific* branch (e.g. force
the create failure that hits the cleanup `shutil.rmtree`). Never bypass the
blocking surface with a test-only `asyncio.to_thread` wrapper.

### Step 4 — Verify teeth (mandatory; also the anchor-vs-rule discriminator)

1. Reintroduce the block (GUARD: temporarily revert the offload; FIX+ANCHOR: run
   against the pre-fix code).
2. Run `cd backend && make test-blocking-io` (or target the one test). It **must
   go RED**.
3. Restore the fix. It **must go GREEN**.

If you reintroduced a real block and the gate stayed **GREEN**, Blockbuster has
no rule for that primitive. That is the **RULE** route — see
`references/good-anchor-rules.md` for the admission criteria. Never add a rule
without the fails-to-fail anchor as evidence, and never add one merely because
a path is untested (that case needs an anchor, not a rule).

### Step 5 — Deliver

Commit the anchor(s) with your change; `make test-blocking-io` green. In the PR,
note: candidates found, each disposition, and the teeth evidence (red→green).
Include the reason for any NO-ACTION. A new Blockbuster rule, if any, goes in
its own commit with the evidence from Step 4.
