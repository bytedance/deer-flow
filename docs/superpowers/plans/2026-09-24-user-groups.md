# User groups implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the frontend task and independent reviews; preserve all prior uncommitted changes.

**Goal:** Add administrator-managed groups, multiple memberships, inherited exact tool/MCP/sandbox grants, and personal deny exceptions, as approved by the user.

**Architecture:** Extend the existing Gateway-owned private SQLite store with groups, members, group grants and user denies. Effective permissions are `(direct grants UNION all group grants) EXCEPT personal denies`, evaluated fresh on each invocation through the existing provider and MCP boundary. Admin role remains privileged. Credentials and execution identities remain individual.

**Tech stack:** Python/FastAPI/SQLite, React/TanStack Query, existing bilingual Settings UI.

## Scope and API contract

- No nested groups, shared credentials, directory synchronization or group-owned sandboxes.
- Group IDs are server-generated UUIDs. Names are trimmed, 1–80 characters, unique after Unicode normalization/casefold. Rename preserves membership/grants; deletion cascades membership/grants only and records an audit event.
- All group routes are session-only and admin-only under `/api/user-security` with existing CSRF and private validation errors.
- `GET /groups` → `{groups: [{id,name,member_count}]}`.
- `POST /groups {name}` → `{id,name,member_count}`; `PATCH /groups/{id} {name}` → same; `DELETE /groups/{id}` → `{deleted:true}`.
- `GET /groups/{id}` → `{id,name,members:[{id,email:string|null}],grants:[{resource,target}]}`.
- `POST /groups/{id}/members {email}` adds an existing account; `DELETE /groups/{id}/members/{user_id}` removes exactly that account. Responses `{member:true|false}`.
- `PUT /groups/{id}/grants {resource,target,allowed}` sets/removes an exact group grant. Validate catalog on allow; permit revoking stale resources.
- `PUT /overrides {email,resource,target,mode:'inherit'|'allow'|'deny'}` changes personal exception. Inherit clears direct allow and deny, allow sets direct allow/clears deny, deny sets deny/clears direct allow. No exceptions for administrator-role accounts.
- Existing `GET /grants?email=` adds `direct_grants`, `denied`, `groups:[{id,name}]`; existing `grants` now means effective grants. Existing grant mutation remains compatible: true sets direct allow/clears deny; false removes direct allow (does not override inherited access).
- `GET /me` retains shape, with resources.allowed reflecting effective permissions.

## Tasks

- [x] Record baseline and write failing backend tests for migration, group CRUD, multigroup union, direct grants, deny precedence, reset, deletion/revocation, and credential separation.
- [x] Implement group storage and effective grant queries; use atomic transactions, foreign-key cascades, exact target validation and audits. Test existing database rows and credentials survive schema extension.
- [x] Add admin group and override APIs; test nonadmin/PAT rejection, membership identity validation, stale-group handling, exact resource validation and effective readback. Verify provider and existing MCP wrappers respond to membership/deny changes.
- [x] Implement frontend group management in a separate settings component; show membership and effective permissions, replace personal grant switches with inherit/allow/deny choices. Keep selected identities separate from drafts, disable conflicting mutations, scope all query keys by signed-in user and refresh permissions after mutations. Add bilingual labels and DOM tests.
- [x] Review specification compliance then code quality, run focused backend/frontend checks and required full baseline comparison, update README/module guides.
- [x] Back up application/security databases, build production frontend, restart Gateway/frontend through existing helper, verify real authenticated group UI and effective grants with disposable users/groups; clean disposable rows and compare original account/chat counts.

## Validation commands and acceptance

Use `backend/.venv/Scripts/python.exe -X utf8 -m pytest` for scoped host tests, and the existing Linux Gateway environment for baseline comparison. Frontend checks use a disposable image/container with source copied in (avoid slow Windows node_modules binds); host pnpm must use scripts/pnpm.py.

Key scenario: Alice belongs to groups A and B. Both grant bash; removing A still permits bash via B. Personal deny blocks bash despite B, including previously assembled tools. Inherit restores B access. Removing B or deleting B revokes it immediately. Alice's personal credential never authenticates Bob even when they share a group. Admin and public/session boundaries stay intact.

The prior implementation is already deployed and dirty in this working branch. Keep operator config, model credentials, branded UI, existing chats and users; do not reset or commit unrelated changes. User's approval of the preceding proposal authorizes implementation and deployment without another design/permission round.

## Completion evidence

- Backend focused suite: 75 passed on Windows and Linux, including group schema
  compatibility, provider/MCP revocation and existing sandbox authorization tests.
- Frontend: lint/type check and optimized production build passed; 23 relevant
  tests passed (7 security/group DOM, 6 enterprise shell, 10 MCP mutation tests).
- Independent specification and quality reviews approved; reviewers independently
  reran overlapping backend subsets (40 and 35 tests).
- Full Linux checks before/after unchanged: 11 repository-layout collection errors;
  strict blocking-I/O 112 passed / 4 existing memory timeout failures. Full suite
  is not claimed passing. Logs: logs/bootstrap/groups-{baseline,final}-*.log.
- Live authenticated API and browser tests passed: group CRUD, multigroup union,
  member removal, personal deny/inherit/allow, non-admin rejection/hidden controls,
  confirmed group deletion and subsequent effective permission changes. No browser
  page errors. Scripts/evidence: logs/bootstrap/groups-live-smoke.py,
  groups-live-browser.mjs, groups-admin-settings.png, groups-personal-deny.png.
- Deployed via production helper (now forces Gateway recreation for bound source
  changes). Gateway/frontend healthy. Backups: pre-groups-20260924-103322; prior
  frontend image retained as ddfw-agent/frontend:pre-groups-20260924.
- Disposable users/groups/memberships/overrides/session file and validation
  container cleaned. Main/security quick_check both ok; original counts preserved:
  users 1, threads 3, runs 4, checkpoints 336, agents 0. No groups prepopulated.
