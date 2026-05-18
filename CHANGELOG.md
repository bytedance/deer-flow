# Changelog

All notable changes to this project will be documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Enterprise Extension (M0—M3)

**Added**

- Opt-in enterprise layer disabled by default; controlled via `enterprise.enabled`
- RBAC: roles, permissions, role assignments; `RbacPermissionProvider` for `app.gateway.authz`
- Audit: HMAC-signed append-only log of agent runs and tool calls; SQLite WAL tuning
- Approval: rule engine, human-in-the-loop pause via `ApprovalMiddleware`, resume by
  re-running with `_approval_ids` metadata; Feishu / WeCom / Web SSE notifiers; timeout sweep
- HTTP routes:
  - `/api/enterprise/audit/*` — list, get, stats, verify, event-types
  - `/api/enterprise/rbac/*` — role/permission/assignment CRUD
  - `/api/enterprise/approvals/*` — list, get, approve, deny, resubmit, cancel
  - `/api/enterprise/approvals/webhook/{feishu,wecom}` — signed inbound callbacks
- Config fields under `enterprise:` — see `config.example.yaml`
- Alembic migrations: `m1_initial_rbac`, `20260518_m2_audit`, `20260518_m3_approval`
  (note: `m1` and `m2` are currently two independent heads; M5 does not merge them)
- One-shot migration script: `python -m scripts.migrate_enterprise`
- Alembic round-trip integration tests for all three enterprise revisions
- Startup config-matrix smoke tests covering 8 legal / fail-fast / warning combinations

**Changed**

- `User.system_role` typed `Literal["admin","member"]` → `str` (type widening; not a breaking change)
- `app.gateway.auth.repositories.UserRepository` gained `list_all_users()` for migration tooling

**Known limitations (M5 backlog)**

- Frontend pages (RBAC admin / Audit viewer / Approval list & detail) are designed but
  not shipped — backend APIs work; UI lands in a separate plan (M5-1 / M5-2).
- Full docker-compose end-to-end acceptance with OIDC mock + Postgres is deferred; see
  enterprise plan §8.3.
- Prometheus metrics namespace `enterprise_*` is reserved but not yet implemented.
- The two Alembic head branches (`m1` vs `m2→m3`) have not been merged; planned for a
  follow-up ops PR.
