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

Contributors changing backend async code can run the `blocking-io-guard` skill
(`.agent/skills/blocking-io-guard/`) to execute steps 1–3 for their own diff: it
scans the change for blocking-IO candidates, drafts or extends a runtime anchor,
and verifies the anchor fails when the blocking IO regresses.

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

The runtime anchors protect confirmed blocking-IO bug shapes:

- SQLite checkpointer setup, including path resolution and parent-directory
  creation.
- Subagent skill metadata loading through `SubagentExecutor._load_skills()`.
- `JsonlRunEventStore` async API (`put` / `list_*` / `delete_*`): the JSONL
  run-event backend offloads its synchronous file IO via `asyncio.to_thread`
  (fix #3084); this anchor drives the real async API under the gate so any
  blocking IO reintroduced on the loop fails, not only removal of one
  `to_thread` call.
- `UploadsMiddleware.before_agent` uploads-directory scan: a sync-only middleware
  hook runs on the event loop under async graph execution, so the scan is
  offloaded via `abefore_agent` + `run_in_executor`.
- Gate health checks: Blockbuster catches unoffloaded calls, opt-out works, and
  patches are restored after exceptions.

As static detection and review identify more high-risk async paths, add new
runtime anchors incrementally.

## detect-blocking-io tooling

The `detect-blocking-io` target parses `app/`, `packages/harness/deerflow/`,
and `scripts/` with AST. By default it reports only blocking IO candidates that
are inside async code, reachable from async code in the same file, or reachable
from sync-only `AgentMiddleware` before/after hooks that LangGraph can execute
on the async graph path. It prints a concise summary and writes complete JSON
findings to `.deer-flow/blocking-io-findings.json` at the repository root
(both `make detect-blocking-io` from the repo root and `cd backend && make
detect-blocking-io` resolve to the same repo-root path). JSON findings include
`priority`, `location`, `blocking_call`, `event_loop_exposure`, `reason`, and
`code` for model-assisted or manual review. `priority` is a deterministic
review ordering from operation type, not proof of a bug. Bare-name same-file
calls are resolved by function name, so duplicate helper names in one file can
conservatively over-report async reachability. The call graph also resolves
multi-hop `self.`/`cls.` attribute chains (`self.store.flush()`) and local
variables or parameters traced back — within the same function only — to a
`self.`/`cls.` attribute (`store = self.store; store.flush()`); both fall back
to the same bare-method-name resolution as an unresolvable receiver, so they
share its over-report risk rather than adding a new kind. Deeper cross-function
or cross-module aliasing is out of scope and stays an unreported false
negative.

That same-function alias tracing is deliberately narrower than the symbolic
names `dotted_name()` builds for blocking-call pattern matching elsewhere in
this module: receiver/alias extraction uses a restricted extractor that only
recognizes `Name`/`Attribute` chains, so a `Call` or `Subscript` result (e.g.
`factory().flush()`, or `client = factory(); client.flush()` /
`client = clients[0]; client.flush()`) is never treated as inheriting its
base's alias-worthiness — including when the unsupported node is buried
deeper in the chain (`factory().client.flush()`, `clients[0].client.flush()`):
an unrecognized shape anywhere in the chain makes the whole receiver
unresolved, it never falls back to just the chain's trailing attribute name,
or that name alone could still collide with an unrelated traced parameter or
local alias. Reassigning a traced name to a non-traceable value (anything
other than a `self.`/`cls.` attribute or an already-traced name) kills its
alias instead of leaving it traceable, so a stale alias from an earlier
assignment cannot keep exposing an unrelated same-named method after the
variable is reassigned to something else; the assignment's right-hand side is
always analyzed against the alias state as it stood *before* this kill-or-add
update, matching Python's own evaluate-then-bind order, so
`client = client.flush()` still resolves that call against `client`'s prior
(pre-reassignment) alias instead of the state after it's gone. `if`/`else`
branches get isolated alias state — an alias added in one branch cannot leak
into the other — and the state after the whole `if` is the union of what each
branch produced (a conservative may-alias join), so the result no longer
depends on which branch is textually `body` vs. `orelse`. This branch
isolation is deliberately scoped to `ast.If` only; `ast.Try`/`ast.Match` have
different, more complex control-flow semantics and keep the older unisolated
traversal. Finally, a function's decorators and parameter defaults are
analyzed in the *enclosing* scope rather than the new function's own, and
parameter/return annotations get the same enclosing-scope treatment unless
the module postpones annotation evaluation (`from __future__ import
annotations`), in which case they are skipped entirely, in either scope —
those expressions run at definition time, before the function has ever been
called (or, when postponed, never run at all), so a call there is never
attributed to the function being defined (it moves to whatever scope actually
contains the `def`, e.g. the enclosing function, or disappears if that scope
is module/class level and therefore never async-reachable). PEP 695
type-parameter bounds are not visited in either scope: CPython evaluates each
one lazily, in its own hidden function, only if something like `T.__bound__`
is actually accessed, never as part of running the `def` statement itself.
A `lambda`'s body and a bare generator expression's element/filters/later
`for` clauses are excluded from traversal ONLY while walking another
function's own definition-time expressions (decorators, parameter defaults/
annotations, return annotation): there, we know structurally that the
enclosing `def` statement is executing right now, and neither a lambda body
nor a generator's element runs just because the lambda/generator object is
created — only a lambda's own parameter defaults and a generator's
outermost iterable are genuinely eager at that moment. This exclusion is
absolute and has no exceptions: even a lambda that is immediately invoked at
its own definition site (`(lambda: ...)()`), or a generator passed directly
to an eager-consuming builtin, is still excluded when it appears inside
another function's decorator/default/annotation — a narrow, intentional
limitation given how rarely a definition-time expression contains an
executed call at all, preferred over special-casing specific shapes there.

Everywhere else — module level, class bodies, and ordinary function-body
statements — a lambda body or generator expression's element is scanned
unconditionally, the same conservative, over-report-rather-than-infer stance
this file already takes for reachability elsewhere (the `ast.If` may-alias
union, the bare-name call-graph resolution). This file does not attempt to
distinguish a lambda that is invoked immediately, invoked later through a
stored variable, passed as a callback, or never called at all, nor a
generator that is consumed by an eager builtin (`list`, `sum`, `any`, etc.),
wrapped in another lazy iterator (`map`, `filter`), or never consumed —
telling these apart in the general case would mean inferring evaluation
order and consumption across arbitrary code rather than reading a fixed,
structural fact, so none of them are special-cased; all are scanned the
same way. This is intentionally informational and is not run from CI in
this round.

For a diff-scoped view of the same findings, `scripts/scan_changed_blocking_io.py`
(repo root) reports findings on the added lines of `git diff <base>...HEAD`
plus findings new versus the merge base (so a new async caller exposing an
untouched sync helper in the same file is still reported) — used by the
`blocking-io-guard` skill (`.agent/skills/blocking-io-guard/`) as the
deterministic scope step before routing each candidate to a fix and/or a
`tests/blocking_io/` runtime anchor.

Regression tests related to Docker/provisioner behavior:
- `tests/test_docker_sandbox_mode_detection.py` (mode detection from `config.yaml`)
- `tests/test_provisioner_kubeconfig.py` (kubeconfig file/directory handling)
- `tests/test_provisioner_request_threading.py` (keeps provisioner sandbox CRUD
  endpoints as sync FastAPI handlers so synchronous K8s client calls run in the
  Starlette worker pool instead of on the ASGI event loop)

Blocking-IO runtime gate (`tests/blocking_io/`):
- Wraps every item under `tests/blocking_io/` with a strict Blockbuster
  context scoped to `app.*` and `deerflow.*` (see
  `tests/support/detectors/blocking_io_runtime.py`). Any sync blocking IO
  call whose stack passes through DeerFlow business code while running on
  the asyncio event loop raises `BlockingError` and fails the test.
- Regression anchors live there: `test_skills_load.py` (locks the
  `asyncio.to_thread` offload around `LocalSkillStorage.load_skills`, fix
  for #1917); `test_sqlite_lifespan.py` (locks the offload around
  SQLite path resolution plus `ensure_sqlite_parent_dir`, fix for #1912);
  `test_jsonl_run_event_store.py` (locks `JsonlRunEventStore`'s async
  API — including idempotent singleton-event writes — offloading its file IO
  via `asyncio.to_thread`); `test_run_journal_callbacks.py` (locks
  `RunJournal.run_inline` tool callbacks to in-memory/event-loop-safe work);
  `test_integrations_router.py` (locks Lark integration install and auth
  completion route handlers offloading archive filesystem work and `lark-cli`
  subprocesses);
  `test_uploads_middleware.py` (locks `UploadsMiddleware.abefore_agent`
  offloading the uploads-directory scan off the event loop);
  `test_uploads_router.py` (locks Gateway upload/list/delete endpoints
  offloading upload directory creation, staged writes, chmod/cleanup,
  directory scans/deletes, and remote sandbox sync off the event loop);
  `test_feishu_receive_file.py` (locks Feishu attachment path preparation and
  persistence plus remote sandbox acquisition/sync off the event loop, and
  skips redundant sandbox sync when thread data is already mounted);
  `test_channel_outbound_files.py` (locks Feishu, Telegram, and WeCom outbound
  attachment open/read/hash work off the event loop);
  `test_openviking_memory_backend.py` (locks the official OpenViking backend's
  async add/context/search entrypoints offloading synchronous SDK and cursor
  filesystem IO); and
  `test_workspace_changes_recorder.py` (locks the offload around the snapshot
  text cache lifecycle — roots resolution, `mkdtemp`, and the `shutil.rmtree`
  on both the capture-failure branch and `record_workspace_changes`' `finally`).
- `test_gate_smoke.py` is a meta-test asserting the gate actually catches
  unoffloaded blocking IO and that the `@pytest.mark.allow_blocking_io`
  opt-out works.
- Coverage boundary: the gate only sees code that test execution actually
  touches. Static AST coverage is a separate concern (out of scope for
  this PR).
- CI: runs on every PR via `.github/workflows/backend-blocking-io-tests.yml`,
  hard-fail.
