# Backend tests (`backend/tests/`)

The offline suite for the Gateway and the harness. `blocking_io/` is the strict
event-loop gate, `support/` holds shared helpers, and `fixtures/` holds recorded
data. What a single test file covers is stated in that file, not here.

## Verify

```bash
cd backend
make test                 # four offline shards; TEST_JOBS=1 runs serially
make test-blocking-io     # strict gate over tests/blocking_io/
python -m pytest tests/test_<feature>.py::test_<name> -q
```

Live tests run only with `DEER_FLOW_RUN_LIVE_TESTS=1`. PostgreSQL cases run when
`TEST_POSTGRES_URI` is set and skip otherwise. Helm and real-Compose cases skip
with a reason when the binary is missing.

## What a test must exercise

- **Run the production path.** Drive the real graph, worker, repository, script
  or HTTP client, and replace only the outermost boundary: the model response,
  the network transport, the clock. A test that raises the expected error itself
  or writes the stored result directly proves nothing about the code.
- **Put the double below the SDK.** A fake HTTP transport under the real vendor
  client checks the payload that DeerFlow sends. A mocked client method does not.
- **A regression test fails on the unfixed code.** Check that before you commit
  the fix. Do not encode a known bug as expected behaviour, and do not hide it
  behind a permanent `xfail`.
- **Assert on structure.** Check decoded payloads, stored rows and metadata.
  User-facing wording is asserted only where the wording is the contract.
- **Scripts run as copies in a temporary checkout.** Never swap sources in the
  working tree during a test, and never let a test read the developer's own
  `config.yaml`, `.env` or runtime home.

## Concurrency and timing

- **Synchronize with events and barriers.** A sleep or a timing threshold passes
  on a fast machine and fails on a loaded CI runner. Park the code at a named
  point, observe the peer reach it, then release.
- **Use a controlled clock** for leases, expiry and scheduling.
- **Release everything in `finally`.** Blocked workers, paused tasks, patched
  process-wide state and event loops are restored even when the assertion fails.
  A leaked worker fails a later, unrelated test.
- **Treat an unhandled warning from a worker thread as an error.**
- **Injected failures must be shown to fire.** Assert that the injection ran, so
  a refactor cannot turn a failure test into a silent pass.

## Portability

- **Use the helpers in `support/`.** `support.postgres` builds the isolated schema
  URL, `support.symlinks.symlink_or_skip` handles hosts without symlink rights,
  `support.shell` finds a POSIX shell or Git Bash, and `support.compose` detects
  the Compose version.
- **Guard POSIX-only cases with `os.name`** so that Windows collection succeeds.
  Permission tests also skip as root, where mode bits do not restrict access.
- **Write fixtures with an explicit newline mode and encoding.** Platform
  defaults change LF/CRLF hashes and non-ASCII paths.
- **Do not import another test module's private fixtures.** Shared code moves to
  `support/` or `conftest.py`.
- **Circular imports are solved in `conftest.py`** with a `sys.modules` stub; see
  the existing entry for `deerflow.subagents.executor`.

## Bundled extension behavior

A module that validates a bundled example's own behavior carries
`pytest.mark.bundled_extension` at module level, so the core shards skip it and
the bundled extension CI runs it. Host mechanisms stay in the core shards even
when an example package is the payload: loading and registration, the public
extension API, authorization, routing and runtime. Host/extension compatibility
checks live in `test_extension_host_contracts.py`, so a broken compatibility
guarantee still fails core CI, and `test_bundled_extension_ci.py` keeps the
workflow's test-file list in step with the marker. Run the bundled suites with
`make test-bundled-extensions`.

## Blocking-I/O tests

Every test under `blocking_io/` runs with a detector that fails on a blocking
call made on the event loop through DeerFlow code. Add a case there when you add
an async entry point that touches files, subprocesses or a synchronous SDK.
`@pytest.mark.allow_blocking_io` is for a test that needs the unguarded behaviour
and states why.

## Guidance inventory

When you add a scoped `AGENTS.md`, add its path to `EXPECTED_GUIDANCE_PATHS` in
`test_agent_guidance_check.py` in the same change.
