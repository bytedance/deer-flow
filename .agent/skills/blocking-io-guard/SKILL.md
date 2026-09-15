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
Only read `references/sop-skeleton.md` when generalizing this SOP to another
detector domain — it is not needed to execute the steps below.

## When to use

- Your change touches Python under `backend/app/`,
  `backend/packages/harness/deerflow/`, or `backend/scripts/` and may run on
  the async event loop (Mode A). If unsure, run Step 0 — it answers
  deterministically.
- You are doing a maintenance triage round over the existing codebase
  (Mode B).

## SOP (router)

### Step 0 — Scope (deterministic)

**Mode A — your own diff** (default, pre-PR). From repo root:

```bash
uv run --project backend python scripts/scan_changed_blocking_io.py --base origin/main
```

Lists blocking-IO candidates your change introduces: findings on lines the
diff added, **plus** findings that are new versus the merge base — the latter
catches a new async caller exposing an old sync helper whose blocking line is
not in the diff. The diff is `<base>...HEAD`, so **commit your work first** —
uncommitted lines are not selected.

If the list is empty, this change introduces no blocking-IO surface *that the
static detector can see in the changed files*. One residual blind spot
remains: reachability is same-file only, so a new async caller of a sync
helper **defined in another file** is invisible to both selections. If your
diff adds an async call into a helper that lives elsewhere, check that helper
manually (codegraph or `git grep`) before stopping.

**Mode B — full-repo triage round.** From repo root:

```bash
make detect-blocking-io
```

Prints a summary and writes the complete structured finding list to
`.deer-flow/blocking-io-findings.json`. Work HIGH priority first; do not start
MEDIUM until every HIGH is dispositioned (fixed, guarded, or recorded
NO-ACTION).

**Batching policy (PR sizing).** One **fix unit** per PR while any HIGH
remains: a fix unit is one root cause — usually a single HIGH, but two HIGHs
resolved by the same one-place fix belong together. Once no HIGH remains,
MEDIUM/LOW may be batched (about five per round, grouped by module or by
disposition) so each PR stays reviewable. A new Blockbuster rule is never
batched with anything — it always ships alone (see Step 5).

Both modes emit the same JSON shape per finding: `priority`, `location`
(path/line/function), `blocking_call` (category/operation/symbol),
`event_loop_exposure`, `reason`, `code`. Priority is a deterministic review
ordering, not proof of a bug — Step 1 makes the actual call.

### Step 1 — Judge each candidate (router)

Read the code around each candidate and route it:

- **Already offloaded** (`asyncio.to_thread`, `run_in_executor`, async client) →
  **GUARD**: add/extend an anchor that locks the offload so a future edit cannot
  move it back onto the loop.
- **On the loop, not offloaded** → **FIX+ANCHOR**: offload the production code
  (your fix), then add an anchor that guards it.
- **Not actually exposed / acceptable** (rare: scanner false positive,
  startup-only code) → **NO-ACTION**: record one line of why.
- **Cross-file caveat**: the scanner's async reachability is same-file only
  (`ASYNC_REACHABLE_SAME_FILE`). If the candidate is a *sync helper*, check for
  async callers in other files (codegraph or `git grep`) before deciding
  NO-ACTION.

### Step 2 — Apply the fix, then re-scan (FIX+ANCHOR only)

Offload the blocking call in production code, then re-run the Step 0 scan and
confirm the candidate no longer appears. If the offloaded call sits in a
`finally` / cleanup path, keep it best-effort and bounded (swallow-and-log,
`asyncio.wait_for`) so a failing or hung cleanup cannot mask the primary
exception. Match by the stable key
**(path, function, symbol)** — line numbers shift after edits, so never
compare by line.

- The finding must disappear. If it still shows, the fix did not remove the
  blocking pattern (e.g. the call is still a direct call, not offloaded) —
  go back before touching any test.
- GUARD / NO-ACTION routes skip this step: a residual finding there is
  *expected* (the raw call still exists inside a sync helper with the offload
  at the caller, or the exposure was judged acceptable).

This is pattern-level feedback in seconds; it complements but never replaces
Step 5 — only the runtime gate proves the event loop is actually protected.

### Step 3 — Check existing anchors

Look in `backend/tests/blocking_io/` for a test that drives the production async
entry point reaching this candidate's branch.

- Covers this branch already → go to Step 5 (re-verify teeth).
- Covers the entry point but not this branch (e.g. happy path covered,
  cleanup/404/409 not) → **extend** that anchor.
- None → create one from `templates/anchor.template.py`.

### Step 4 — Generate / extend the anchor

Follow `references/good-anchor-rules.md`. Drive the *specific* branch (e.g. force
the create failure that hits the cleanup `shutil.rmtree`). Never bypass the
blocking surface with a test-only `asyncio.to_thread` wrapper.

### Step 5 — Verify teeth (mandatory; also the anchor-vs-rule discriminator)

1. Reintroduce the block (GUARD: temporarily revert the offload; FIX+ANCHOR: run
   against the pre-fix code).
2. Run `cd backend && make test-blocking-io` (or target the one test). It **must
   go RED**.
3. Restore the fix. It **must go GREEN**.

A real block that stays GREEN means Blockbuster has no rule for that
primitive — that is the **RULE** route; see `references/good-anchor-rules.md`
for the admission criteria before adding one.

### Step 6 — Deliver

Commit the anchor(s) with your change; `make test-blocking-io` green. In the PR,
note: candidates found, each disposition, the re-scan result (Step 2), and
the teeth evidence (red→green). Include the reason for any NO-ACTION. A new
Blockbuster rule, if any, goes in its own commit with the evidence from Step 5.
