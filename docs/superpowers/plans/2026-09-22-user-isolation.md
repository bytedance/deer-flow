# DDFW-Agent user isolation implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent sandbox task; integrate and review before deployment.

**Goal:** Implement the user's requested per-user tool grants, private credentials, and independent Docker execution, preserving current production data and branding.

**Architecture:** Reuse the existing two-layer authorization hooks and MCP interceptors. Store exact user grants and encrypted personal MCP credentials in Gateway-owned storage outside user mounts. Reuse the AIO Docker provider's user/thread identity, lifecycle, resource limits, and restricted network support. Expose personal credentials and administrator grants through authenticated settings APIs and the Tools UI.

**Decisions:** The existing user instruction authorizes this implementation and production update. Each user/thread receives an independently isolated execution container, created lazily and retired after idle time; no shared LocalSandbox fallback. Administrators manage the deployment tool catalog and individual grants. Ordinary users start without tool grants. Missing credentials deny access; no shared-token fallback. The existing model-provider credentials remain operator-managed and are never mounted into execution containers. This increment isolates personal MCP credentials; it does not invent a per-user ChatGPT OAuth sign-in flow.

## Tasks

- [x] Baseline backend offline and blocking-I/O checks; record existing failures without changing unrelated code.
- [x] Add a private encrypted credential/grant store and a user-based authorization provider, with tests for exact user matching, deny-by-default, revocation, and ciphertext-only persistence.
- [x] Add authenticated APIs: own credential set/delete/status; admin user grant management. Never return plaintext or accept caller-selected identity for personal operations. Add API tests for non-admin and cross-user denial.
- [x] Add a final MCP interceptor that enforces user grants and injects only the caller's stored credential. Reject unsupported/shared-auth configurations in enterprise mode rather than silently falling back. Test two users, missing credentials, invalid headers, revocation, and configuration changes.
- [x] Add Tools settings UI for personal credentials and administrator grants, following existing locale and request utilities. Verify with type/lint checks and relevant DOM/API tests.
- [x] Configure and live-test isolated Docker sandboxes: separate user/thread containers and files, no platform config/socket mounts, constrained CPU/memory/process count, controlled networking, idle cleanup, no LocalSandbox fallback.
- [x] Review security boundaries and fixes, run targeted regressions and the required full checks, update README/module guides and local deployment runbook.
- [x] Back up live data, build production frontend, deploy with authorization enabled, verify existing login/model setup and two-user isolation, remove disposable test state. Two test workspaces remain as evidence after automatic policy rejected their recursive deletion; test accounts, grants, session files and containers were removed.

## Acceptance checks

1. User A's grants and credentials do not grant or authenticate User B.
2. Removed grants/credentials are rejected on subsequent invocations, including tools assembled earlier.
3. Non-admins cannot change grants or deployment MCP configuration; personal APIs never reveal plaintext.
4. A and B have distinct Docker execution identities; neither can read the other's mounted files or Gateway credentials.
5. Production remains authenticated and retains existing accounts, conversations, and branding.

## Completion evidence

- New security/router/MCP plus sandbox authorization tests: 54 passed; independent
  route review confirmed all 6 route tests after private validation-error handling.
- Frontend lint/type checks and 19 relevant tests passed; optimized production
  frontend built and deployed successfully.
- AIO provider/network/identity tests: 136 passed, 3 opt-in live tests skipped;
  separate real two-user preflight: 39/39 passed.
- Live production: password login for disposable admin + two ordinary users;
  default deny, non-admin grant denial, isolated grant/revocation, model list;
  actual browser Tools settings for all three roles; two live-config execution
  containers with separate files and no platform credentials/socket. All passed.
- Database quick_check: ok; final counts unchanged: users 1, threads 3, runs 4,
  checkpoints 336, agents 0. Both production services healthy.
- Full Linux offline suite remains blocked by the same 11 repository-layout
  collection errors as baseline; strict blocking-I/O remains 112 passed / 4
  pre-existing memory timeout failures. Windows full collection also encounters
  existing os.geteuid/POSIX incompatibilities. Broad Windows MCP regression:
  717 passed / 16 failures; broad Linux MCP collection was interrupted after
  310 seconds blocked on Windows bind-mount filesystem calls, before tests ran.
  Do not describe the full repository suite as passing.
- Local evidence/runbook: logs/bootstrap/PRODUCTION.md,
  sandbox-deployment-evidence.md, sandbox-preflight-report.json,
  isolation-live-sandbox.log and isolation-*-tools.png. Production start helper
  applies the sandbox overlay; operator secrets/config/backups stay gitignored.
