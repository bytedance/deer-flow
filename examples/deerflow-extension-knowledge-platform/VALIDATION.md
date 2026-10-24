# Stage 3 validation record

Date: 2026-10-24. Base: upstream `9a11f9ae`. Environment: native Windows,
CPython 3.12.15, Node 24.16.0, pnpm 10.26.2. This records the platform/space
backend in the new five-stage follow-up to #6269, after #7171 and #7293.

## Verified behavior

The new backend tests use real SQLite and FastAPI routing. The management bridge
also exercises the existing WeKnora adapter through `httpx.MockTransport` with
synthetic resources and responses. It does not contact a real WeKnora service.

- Four-level spaces, inherited defaults, explicit sharing, exact member roles,
  administrator-only policy changes and restart persistence.
- Rejection of cycles, missing parents, child resource/operation/member expansion,
  stale revisions and unauthorized resources before Provider submission.
- Transactional revision fencing across threads and independently spawned
  processes; one writer wins and the stale writer receives a conflict.
- Ancestor revocation, connection disablement, removed operator resources,
  administrator recovery and continued access to unaffected spaces.
- Tool ceilings, inherited default tools, explicit `null` clearing across policy
  round trips, and rejection when operator tool revocation invalidates a default.
- The same authenticated administrator reaches the original management Provider;
  both plugin namespace grants, space policy and upstream grants remain required.
- Capability/default composition, upload, ingestion, status, reprocess and cancel;
  unsupported options fail before mutation and uncertain writes are not retried.
- Response identity checks preserve dataset/document identity. Unknown processing
  states remain unknown. Revocation during capability discovery prevents a write.
- Bounded request parsing, rejection of forged identity/configuration fields,
  secret-free policy responses and SQLite offloading under the blocking-I/O gate.

## Passing checks

From `backend/`, the final combined regression command passed **272 tests**:

```sh
uv run pytest tests/test_extension_route_principal.py tests/test_extension_gateway_wiring.py tests/test_extension_registry.py tests/test_plugin_targets.py tests/test_knowledge_platform_extension.py tests/test_knowledge_management_extension.py tests/blocking_io/test_knowledge_platform_extension.py tests/blocking_io/test_knowledge_management_extension.py tests/test_agent_guidance_check.py -q --tb=short
```

This includes **32 new platform tests and one strict blocking-I/O test**. Backend
`ruff check .` and `ruff format --check .` passed, as did Ruff on both example
packages. `python scripts/check_agent_guidance.py` reported 0 errors and 15 existing
soft budget warnings. Both extension wheels passed `scripts/check_extension.py`.

The real `ExtensionManager.install(..., yes=True)` source-snapshot workflow also
installed management and platform, in that order, into a separate temporary
project and virtual environment with extension-api 0.2.9. Installed entry points
loaded successfully: both were inert by default; enabling the management
namespace without direct routes and then platform registered both namespaces,
nine platform routes and a policy that survived reopening its SQLite store.
The probe used the real WeKnora factory but made no upstream requests.

Frontend `pnpm check`, formatting checks for changed files and the extension
catalog unit suite passed (**10 tests**). A production build passed using
`BETTER_AUTH_SECRET=local-dev-secret pnpm exec next build --webpack`.
The default Turbopack build could not use the native SWC binary because Windows
Application Control blocked it; its WASM fallback does not support Turbopack.

Against that production build, Chromium ran the existing extension-directory
cases for English, Chinese and failed runtime discovery: **3 passed**. An initial
English attempt saw duplicate search inputs during loading; its isolated rerun
and the subsequent complete three-case run passed without changing the tests.
These cases validate discovery metadata, not a knowledge management page.

## Full-suite results and baseline comparison

The full suites were run, but are **not reported as green** on this Windows host.

- Four backend offline shards initially reported 35,872 passed, 105 failed,
  21 errors and 1,847 skipped. That run overlapped implementation and included
  one platform test whose fake response was subsequently corrected to the
  validated management result contract. The final platform/management regression
  selection above passes.
- Replaying the other failing/error nodes on an untouched `9a11f9ae` worktree
  reproduced 96 failures and 21 errors; eight nodes passed on that replay.
  Failures include Windows filesystem/process behavior and existing test fixture
  errors. A narrower replay on this branch passed eight transient cases; the
  goal-worker fixture error also reproduced separately on the untouched base.
  This is evidence of baseline and transient failures, not a claim that every
  full-suite failure has been conclusively classified.
- The full strict blocking-I/O suite reported 274 passed, 8 skipped and one
  existing dynamic-context memory timeout failure. That timeout test passed
  separately on both this branch and the untouched base. The new platform
  blocking-I/O test passes in the combined regression selection.
- The full frontend suite reported 3,477 passed and one task-form pending-capability
  timeout. That test file passed separately on this branch and the untouched
  base: 37 passed in each run.

CI on the PR is a separate result; these local checks do not substitute for it.

## Acceptance boundary

This is an opt-in backend policy layer, with discovery text in the existing
extension directory. It does not deliver the fourth-stage management page or
fifth-stage Trace, and it does not enforce a global chat retrieval ACL. Tool
policy is an effective-policy projection for future consumers. Existing chat
tools and persisted citations retain their current contracts.

No real upstream ingestion, model answer, production SSO, per-user upstream
delegation, multi-host policy replication or cancellation of already admitted
Provider calls was verified here. The second-stage real-service acceptance
record is independent evidence and is not reclassified as third-stage live
acceptance. Use [CONTRACT.md](CONTRACT.md) for the next-stage integration boundary.
