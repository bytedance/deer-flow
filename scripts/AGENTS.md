## Support Bundle Runtime Home

Thread manifests use a nonempty `DEER_FLOW_HOME` exclusively, resolving relative
values from the caller's current directory like `Paths.base_dir`. Scan both
legacy threads and user-scoped threads in that root. With no override, retain
the two checkout layouts. Display an external home as `{DEER_FLOW_HOME}` rather
than its absolute host path, and never include file contents in the manifest.
Coverage lives in `backend/tests/test_support_bundle.py`.

## Manual Claude OAuth Export

`export_claude_code_oauth.py` validates Keychain JSON as an object containing an
object `claudeAiOauth` and a nonblank string `accessToken` before any export action.
Malformed containers use the existing token-missing error without exposing their
contents. The loader returns the full container together with the validated token;
export actions use that token without repeating credential-shape assumptions or
trimming its contents. Offline CLI coverage:
`backend/tests/test_claude_keychain_export.py`.

## Service Startup Contracts

Optional browser dependency detection reads the top-level `tools:` sequence
without requiring `name` to be its first mapping key. Both indented and
indentless lists are supported; nested option names and block-scalar text
must not enable the browser extra. Keep the detector standard-library-only
because it runs before dependency synchronization. Read UTF-8 config files
with or without a leading BOM so the first section remains detectable.
`setup-sandbox.sh` also strips the leading BOM and normalizes CRLF before selecting the image;
keep its shell filter compatible with GNU and BSD sed.
An Apple Container pull that succeeds on macOS must not fail the setup step
just because Docker is absent. Keep the Docker pull when Docker is available,
including after an Apple Container failure, and retain the final image-config
note rather than exiting early on Apple Container success.

The root `PORT` value configures Docker's published nginx ingress only; local
orchestration pins Next.js to `3000`. Runtime commands launch from the already
synchronized environment with `uv run --no-sync`. Production Compose probes
Gateway `/health`, and `deploy.sh` waits for all services before reporting
success; failures print Compose status and recent Gateway logs.

Both compose files mark `../.env` and `../frontend/.env` optional
(`path`/`required: false`, Compose 2.24+), so `make up`, `make down` and
`make prod-logs` on a fresh checkout neither abort nor create them; an
unreadable `.env` still fails. Do not seed them from the examples in
`deploy.sh` as `docker.sh start` does: `.env.example` holds placeholder API
keys the production Gateway would receive, and `make config` skips files that
exist. Pinned by `backend/tests/test_compose_default_bind_host.py` and
`backend/tests/test_gateway_startup.py`.

`deploy.sh` never sources the repo-root `.env`; Compose reads it via
`--env-file`, and shell exports outrank that file during interpolation (an
exported-but-empty variable still wins). So `BETTER_AUTH_SECRET` and
`DEER_FLOW_INTERNAL_AUTH_TOKEN` resolve shell → `.env` → persisted file under
`DEER_FLOW_HOME` → freshly generated, and a `.env`-provided value is left
unexported so Compose parses it itself. Whether `.env` provides one is
Compose's answer, not a `KEY=VALUE` grep: Compose also accepts `KEY: VALUE`
lines and interpolates `${VAR}` inside values, so the script renders a stub
project whose only environment entry is `${KEY}` through
`docker compose config` (same `--env-file`, stub on stdin, project directory
`docker/`) and reads the value back; `""` means empty or unset and falls
through to the persisted/generated secret. This works on every Compose v2
(the README floor is 2.24; `config --environment` would need 2.28), and a
failing probe stops the script rather than guessing. `read_dotenv_value`
stays for the end-of-run summary only. Do not export a value the script read
from `.env`: that shadows Compose's own dotenv parsing and re-creates the bug
where `make up` replaced the operator's secret with a generated one.
`backend/tests/test_deploy_dotenv_secrets.py` pins the order and the probe;
its real-Compose cases run against the installed `docker` CLI and against any
standalone binaries listed in `DEER_FLOW_TEST_COMPOSE_BINARIES`.

`doctor.py` checks the config file the Gateway would load, not a fixed
`<checkout>/config.yaml`. It mirrors how `serve.sh` hands the two
config-location variables to the Gateway: `.env` values for
`DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_PROJECT_ROOT` override the shell (other
keys stay shell-first), an unquoted leading `~` in them expands as `source`
does (a quoted one stays literal), and an unset or empty
`DEER_FLOW_PROJECT_ROOT` becomes the checkout. It then asks the harness
(`AppConfig.resolve_config_path`) instead of re-implementing its order. An
override the Gateway would reject (`DEER_FLOW_CONFIG_PATH` missing,
`DEER_FLOW_PROJECT_ROOT` not a directory) fails `config.yaml found` with the
Gateway's error, and the config-dependent checks skip. Any failure to import
the harness is reported, never raised: doctor diagnoses broken environments.
Pinned by `backend/tests/test_doctor.py::TestMainConfigResolution`.

CLI credential JSON checks accept UTF-8 with or without a leading BOM, matching
the runtime credential loader. Keep `_load_json_object` on `utf-8-sig`; malformed
JSON and invalid encoding remain missing/invalid sources without exposing tokens.
Public doctor/runtime agreement is pinned by
`backend/tests/test_credential_file_encoding.py`.

Root `make install` runs pre-commit through uv, so uv's tool bin directory
need not be on `PATH`.

`config-upgrade.sh` upgrades the file the Gateway loads by asking the harness
(`AppConfig.resolve_config_path`) rather than copying its lookup order. It
defaults `DEER_FLOW_PROJECT_ROOT` to the checkout, as `serve.sh` does, so
`<checkout>/config.yaml` wins over a legacy `backend/config.yaml`. A missing
`DEER_FLOW_CONFIG_PATH` or invalid project root is an error, never a fallback.
Only "no config anywhere" creates `<checkout>/config.yaml` from the example.
`backend/tests/test_config_version.py::test_config_upgrade_*` pins this.

## Shell Script Invocation Contract

Root Makefile recipes must invoke repository `.sh` files through
`RUN_SHELL_SCRIPT`. On POSIX this expands to `$(BASH)`; on Windows it uses the
Git Bash wrapper. Shell scripts that invoke sibling repository scripts must
likewise prefix the target with `bash`. This keeps documented `make` commands
working when a source archive, `core.fileMode=false`, or a non-POSIX filesystem
does not preserve executable bits.

`make clean` deletes `backend/.deer-flow` (database, users, threads, uploads,
secrets), which both compose stacks mount into `deer-flow-gateway`. Its recipe
runs `check-data-not-in-use.sh` before `make stop` (which would stop a live
stack's sandboxes) and refuses while that container runs; an absent or
unreachable Docker passes. `make stop` must still run before the delete: it
stops `deer-flow-sandbox*` containers, whose thread mounts live in that tree.
`RUNTIME_DATA_CONTENTS` feeds both the help line and the deletion notice.

Host-side pnpm calls must go through `scripts/pnpm.py`. With native Windows
Python (`os.name == "nt"`), it checks `pnpm.cmd` before the generic `pnpm`
lookup, which uses `PATH`/`PATHEXT` and may select an `.exe` or `.bat` in the
same or an earlier PATH directory. If neither is found, it falls back to
Corepack, checking `corepack.cmd` before `corepack`. POSIX Python (including
MSYS/Cygwin Python) keeps the generic name first for each tool; the gate is
based on Python's `os.name`, not the invoking shell.

## Public Skill Review Waivers

`review_changed_public_skills.py` keeps the analyzer strict and applies narrow
CI-only exceptions from `.github/skill-review-waivers.v1.json`. The manifest is
versioned by `contracts/skill_review/waiver_manifest.v1.schema.json`; each entry
must identify one current error by package, source, rule, path, line, and
evidence, and pin the complete source file with SHA-256 plus an expiry date.
An optional, bounded `preapproved_file_sha256s` list authorizes reviewed future
full-file digests without relaxing the exact finding match. Blockers are never
waivable, and waived errors are still printed with their original severity and
justification.

For pull requests, only the base revision's manifest is effective. The head
manifest is parsed and checked against the current analyzer output, but cannot
self-authorize a finding in the same pull request. Push comparisons use the
same before/after trust boundary. A waiver-only change can therefore land
without weakening its own check, then become effective for later changes after
it is part of the trusted base. Preapproved digests must be code-reviewed in
that first change; after the corresponding file revision lands, promote the
consumed digest to `file_sha256` and remove it from the preapproval list.

## Backend Static Analysis Commands

The root `detect-thread-boundaries` target statically inventories execution
boundaries under `backend/app/` and `backend/packages/harness/deerflow/`. It
prints a concise count by execution domain and writes the complete, versioned
JSON payload to `.deer-flow/thread-boundary-inventory.json`. Every finding has
a stable `boundary_kind`: `asyncio_default_executor`, `dedicated_executor`,
`anyio_worker_thread`, `direct_event_loop_blocking`, `separate_event_loop`, or
`unresolved_dynamic_boundary`.

The AST inventory covers `asyncio.to_thread`, default and explicit
`run_in_executor` submissions, imported aliases, simple same-module helper
wrappers (after pre-registering dedicated executor targets), `set_default_executor`,
`ThreadPoolExecutor` construction/submission,
additional event loops, synchronous LangChain tools, and direct
`BaseChatModel` fallback inheritance. It remains read-only and does not alter
executor routing or sizing.

To supplement the static scan with configured runtime types, run:

```bash
python scripts/detect_thread_boundaries.py \
  --runtime-config config.yaml \
  --json-output .deer-flow/thread-boundary-inventory.json
```

Runtime inspection imports configured tool objects and model classes so it can
record concrete tool names/types/modules, sync functions, async coroutines,
and `_agenerate`/`_astream` ownership. It does not invoke tools, instantiate
models, or call external services; import failures remain in the JSON as
`unresolved_dynamic_boundary` records. The detector implementation and focused
coverage live in `tests/support/detectors/thread_boundaries.py` and
`tests/test_detect_thread_boundaries.py`.

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

Boundary check (harness → app import firewall):
- `tests/test_harness_boundary.py` — ensures `packages/harness/deerflow/` never imports from `app.*`

Memory backend async boundary:
- `MemoryMiddleware.aafter_agent` calls `MemoryManager.aadd`; network-backed
  managers must override their `a*` methods to offload or use native async I/O.
- The mem0 backend requires an HTTPS `base_url` by default because requests
  carry an API token. Plain HTTP requires the explicit
  `backend_config.allow_insecure_http: true` local-development opt-in.
- Gateway memory routes offload the synchronous management contract with
  `asyncio.to_thread`, so backend file or HTTP I/O does not run on the ASGI
  event loop. Gateway startup and shutdown also resolve the manager off-loop,
  because a backend's `from_config` may perform a fail-fast connectivity check.
- A backend may set `requires_passive_writes_in_tool_mode = True` when tool-mode
  search is supported but durable writes still depend on conversation-level
  extraction. Such backends receive memory tools and retain `MemoryMiddleware`.
- Prompt recall rethrows `MemoryManagerError` only when backend config declares
  `failure_policy.read: fail_closed`; other recall errors preserve the existing
  log-and-empty-context behavior.

CI runs these regression tests for every pull request via [.github/workflows/backend-unit-tests.yml](../.github/workflows/backend-unit-tests.yml).

Agentic browser sessions are process-local. Browser use is refused when the Gateway runs
more than one worker process, because ordinary uvicorn worker dispatch does not provide
thread affinity for browser tools, REST navigation, and the Live WebSocket. Keep
`GATEWAY_WORKERS=1`, and on the launchers that pass uvicorn no `--workers`
(`scripts/serve.sh`, `backend/Dockerfile`) keep `WEB_CONCURRENCY` unset or `1` too — that
is where uvicorn takes the process count from.

Browser Live screenshots remain JPEG bytes inside the harness and the Gateway's
bounded, drop-oldest frame queue. WebSocket clients that request
`frame_format=binary` receive binary messages; control metadata remains JSON.
The legacy no-parameter protocol still base64-encodes frames into JSON at the
Gateway boundary for backward compatibility. Unknown `frame_format` values
receive a JSON error and close code 1008.

The support bundle's `extensions_config.json` reader accepts UTF-8 with or
without a leading BOM, matching the runtime loader. Preserve redaction and
avoid flagging a valid BOM-prefixed file as a syntax error in triage output.

Support-bundle and doctor tool captures explicitly decode UTF-8 with replacement
for invalid bytes. Set `PYTHONIOENCODING=utf-8:backslashreplace` only in the copied
support-bundle child environment so Python helpers can print Unicode and escape
surrogates without aborting diagnostics or changing the parent.
Keep exit codes, timeouts and redaction intact; do not rely on the host locale.
Regressions use real local children, including ASCII/GBK capture defaults,
nonzero exits, surrogate characters and malformed output, without invoking
provider diagnostics. Doctor covers both `_run` streams and pnpm runner capture.
