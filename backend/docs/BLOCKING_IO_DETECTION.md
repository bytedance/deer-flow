# Blocking IO detection usage and maintenance

This document describes how to use and maintain DeerFlow backend blocking-IO
detection for async event-loop safety.

The goal is narrow: find and prevent synchronous IO from blocking backend
async event-loop paths. Static and runtime detection are complementary, but
they have different jobs.

## Static detector

The static detector is the discovery tool. It scans backend source code and
reports candidate blocking-IO call sites that may need human review.

Run it from the repository root:

```bash
make detect-blocking-io
```

Or from `backend/`:

```bash
make detect-blocking-io
```

The report is written to:

```text
.deer-flow/blocking-io-findings.json
```

Use this output for review and triage. A static finding is a candidate, not
proof that production blocks the event loop at runtime. The current static
rules are intentionally broad; prefer triaging existing output before adding
new static rules.

Add a static rule only when review finds a recurring high-risk blocking
pattern that is invisible to the current detector.

## Runtime detector

The runtime detector is the CI regression guard. It uses Blockbuster to fail a
focused test when code under `app.*` or `deerflow.*` performs blocking IO on
the asyncio event-loop thread.

Run it from `backend/`:

```bash
make test-blocking-io
```

The runtime gate starts from confirmed production bugs and protects those
paths from regressing. It does not prove that the entire backend is free of
blocking IO; it only covers the production paths exercised by
`backend/tests/blocking_io/`.

## Maintenance workflow

Use the static detector to find candidates, then use review to decide which
async production paths are worth protecting in CI.

The normal workflow is:

1. Run the static detector to find backend blocking-IO candidates.
2. Use human review to pick high-risk production async paths.
3. Add or update a focused runtime anchor in `backend/tests/blocking_io/`.
4. Let CI prevent that path from regressing.

Runtime detection has two maintenance paths.

### Add a runtime rule

Add a runtime rule when Blockbuster's default rules do not cover a generic
blocking primitive used by production code.

Rules belong in:

```text
backend/tests/support/detectors/blocking_io_runtime.py
```

Add them to `_PROJECT_BLOCKING_RULES`, not directly inside individual tests.
Keeping rules centralized makes it clear which extra primitives DeerFlow
expects Blockbuster to catch.

Example shape:

```python
import subprocess

from blockbuster import BlockBusterFunction

_PROJECT_BLOCKING_RULES = (
    (
        "subprocess.Popen.__init__",
        BlockBusterFunction(
            subprocess.Popen,
            "__init__",
            scanned_modules=["app", "deerflow"],
        ),
    ),
)
```

Do not add a runtime rule just because a business path is not tested. A rule
only expands what Blockbuster can intercept after code runs.

### Add a runtime anchor

Add a runtime anchor when a high-risk async production path should be protected
by CI but no existing `backend/tests/blocking_io/` test executes it.

Anchors belong in:

```text
backend/tests/blocking_io/
```

A good anchor should:

- Call the real production async entry point.
- Avoid bypassing the blocking surface with test-only `asyncio.to_thread`
  wrappers.
- Use real local filesystem inputs when the bug shape is filesystem IO.
- Mock only the external dependency boundary, such as a network service or
  third-party saver class.
- Fail if a future change moves the blocking operation back onto the event
  loop.

Avoid testing only the low-level helper unless that helper is the production
async entry point. The runtime gate is most useful when it protects the caller
that production actually executes.

## Current runtime coverage

The initial runtime anchors protect confirmed blocking-IO bug shapes:

- SQLite checkpointer setup, including path resolution and parent-directory
  creation.
- Subagent skill metadata loading through `SubagentExecutor._load_skills()`.
- Gate health checks: Blockbuster catches unoffloaded calls, opt-out works, and
  patches are restored after exceptions.

As static detection and review identify more high-risk async paths, add new
runtime anchors incrementally.
