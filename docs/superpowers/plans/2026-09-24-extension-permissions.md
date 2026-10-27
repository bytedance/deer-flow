# Default capabilities and extension authorization

> **For agentic workers:** Use subagent-driven-development for skill enforcement, frontend presentation and independent review. The user explicitly requested the behavior change; continue through production verification without another approval round.

**Goal:** Existing default tools and bundled skills work for authenticated users without grants. Additional tools, MCP and skills remain subject to user/group authorization.

**Architecture:** Freeze an explicit built-in tool-name and public-skill-source baseline in `security/defaults.py`; never derive exemptions from future dynamic catalogs. Add `skill` as an exact grant resource. Existing grant/deny composition applies only to managed extensions; stale overrides on default capabilities no longer block them. Sandbox execution remains isolated but requires no permission toggle. Skills must be gated in discovery/activation/API visibility and filesystem projection, with fail-closed identity and no stale cached authorization.

**Accepted interpretation:** The user referred to the current default permission list and future added tools/skills. Current bundled public skills are also default-open; future files added even to public/ are not automatically exempt. Custom skills shadowing a built-in name are not exempt. Existing skill ownership/visibility scopes are retained; grants do not publish another user's private custom skills.

## Interface and boundaries

- Defaults: the 23 tool names in the verified current catalog plus framework discovery tools needed to use skills/tools; exact public skill targets from the verified current 23-package snapshot. No wildcard exemptions for new extensions.
- Skill targets identify source as `category:path` (custom skills additionally include owner ID). Public baseline `vercel-deploy` is keyed by its actual `vercel-deploy-claimable` path.
- Permission catalog and grant editor show only managed extensions; use optional human-readable label and `resource:'skill'`. Inform users that built-ins work automatically. Preserve groups and personal credential forms.
- Existing permission changes cannot grant new capabilities accidentally: unknown additions default deny for ordinary users; administrators retain account-role access. Skill permission does not implicitly authorize a separate MCP/tool.
- `security/skill_access.py` owns target identity and fresh filtering; runtime and API integrations must not filter administrator catalog scans. Refresh authorization after cached metadata reads and intersect with existing Agent skill allowlists. Ensure denied skills do not enter sandbox mounts, including warm reuse.
- Secrets, model configuration, account roles, independent execution containers and chat data stay unchanged.

## Tasks

- [x] Record backend baseline; add failing tests for default-open, new-tool deny, stale default overrides, unknown identities and new skill resource grants.
- [x] Implement explicit default baseline, provider decisions, storage/API catalog changes; preserve group union and deny semantics for extensions.
- [x] Implement skill permission filtering across API/runtime and sandbox projection, with tests for default public vs custom shadow, group grants/revocation, denied slash/deferred activation and filesystem exposure.
- [x] Update frontend resource type/labels, explanatory copy and relevant DOM tests; remove default permission toggles from catalog-based UI.
- [x] Independent spec/quality review; backend/frontend targeted and full-baseline checks; update guides/README.
- [x] Back up data, build/recreate production services, verify default tool availability for fresh users and extension/skill deny+grant+revoke behavior, clean test data.


## Verification notes

- Policy/store/router/private-credential targeted suite: 45 passed.
- Skill/runtime/projection regression: 590 passed in Linux with isolated example config.
- Bootstrap/assembly regression after preserving the enterprise bootstrap projection: 139 passed.
- Frontend lint/type checks and 30 focused tests passed; optimized production build passed.
- Full offline baseline and after-check both encounter the same 11 existing container repository-layout collection errors. Strict blocking baseline and final both have the same 4 dynamic-memory timeout failures, with 112 passing.
- Live authenticated API and browser checks passed: defaults available; new Skill hidden until grant; group union/member revoke; personal deny/inherit; separate normal-user visibility. Existing user-created groups were preserved.
- Real Docker sandbox verified default Skill files, denied extension files, grant visibility and deny/revocation removal on reuse. Disposable container, source Skill and permissions were cleaned.
- Automated approval review rejected recursive removal of the generated `backend/.deer-flow/users/extensions-smoke-c696d8330ee4` directory (`blocked by policy`). It remains as test evidence; no alternate deletion attempted. Frontend check container stopped.
- Independent final review identified MCP default-name collisions. Fixed with default-name reservation at MCP discovery, catalog and final transport checks (including prefix combinations); related regression 72 passed, final focused suite 41 passed. Discovery policy resolution is offloaded from the async event loop.

- Production frontend and Gateway updated; final service readiness and `http://localhost:2026/api/v1/auth/setup-status` returned 200. Docker Desktop restarted during final verification; the four DDFW services were restored, and the final live API suite passed with disposable data cleaned.
- Backup: `logs/bootstrap/pre-extensions-20260924-104747/`. Frontend rollback image: `ddfw-agent/frontend:pre-extensions-20260924`.
