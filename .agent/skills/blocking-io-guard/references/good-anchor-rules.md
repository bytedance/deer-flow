# Good anchor rules + teeth (blocking-IO fill)

Distilled from `backend/docs/BLOCKING_IO_DETECTION.md`. An anchor lives in
`backend/tests/blocking_io/`; the suite's conftest runs each test under the
strict Blockbuster gate scoped to `app.*` / `deerflow.*`.

The examples in this file and in `templates/` are all filesystem-flavored.
They demonstrate how to *write* the test, not what the SOP covers: the same
rules apply to every category the detector reports (FILE_IO, HTTP,
SUBPROCESS, SLEEP), and the acceptance criterion is always the teeth check
below — never similarity to an example.

## A good anchor

- Calls the **real production async entry point** — not a low-level helper,
  unless that helper *is* the entry point production executes.
- Does **not** bypass the blocking surface with a test-only
  `asyncio.to_thread` / `run_in_executor` wrapper.
- Uses **real local filesystem** inputs when the bug shape is filesystem IO.
- Mocks **only** the external dependency boundary (network service, third-party
  saver), never the offload being guarded.
- Drives the **specific branch** you are protecting (error / cleanup / 404 /
  409), not just the happy path.

## Teeth (the acceptance test)

An anchor only counts if the gate actually fires when the code blocks:

1. Reintroduce the block (revert the offload, or run pre-fix code).
2. `cd backend && make test-blocking-io` → the anchor **must fail** (RED).
3. Restore the fix → the anchor **must pass** (GREEN).

A green-on-happy-path anchor with no proven red is fake coverage. Don't ship it.

## The RULE route (rare; strict admission criteria)

Blockbuster's built-in rules cover the common blocking primitives well. The
two deliberate openings in this SOP are:

1. **Coverage opening** (the normal case): the rules already see the
   primitive — you only need an anchor so runtime detection executes the real
   business path and CI prevents regression.
2. **Rule opening** (rare): you reintroduced a *real* block and the gate
   stayed GREEN — Blockbuster has no rule for that primitive.

A project rule lives in `_PROJECT_BLOCKING_RULES` inside
`backend/tests/support/detectors/blocking_io_runtime.py` and changes detection
for the **entire** blocking-IO suite — global blast radius. Admission criteria
for adding one:

- You have the **fails-to-fail anchor** as evidence: a good anchor (per the
  rules above) that drives a genuinely blocking path and stays green. No
  evidence, no rule.
- The primitive is a real blocking call (verified against its implementation
  or docs), not a false positive of the static detector.
- The rule ships in its **own commit**, naming the primitive, the anchor that
  exposed the gap, and the suite-wide impact. Run the full
  `make test-blocking-io` suite after adding it — a new rule can turn other
  previously-green tests red, and each such red is either a real latent bug
  (fix it) or rule overreach (narrow the rule).
- If you are not in a position to own that blast radius (e.g. external
  contributor), escalate to a maintainer with the evidence instead.

**Never add a runtime rule just because a path is untested** — that case needs
an anchor, not a rule.
