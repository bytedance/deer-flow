# Multi-User Isolation Architecture Investigation Report

> Investigation Date: 2026/05/15
> Branch: `main` vs `upstream/feat/auth-on-2.0-rc`

---

## Executive Summary

| Dimension | main branch | feat/auth-on-2.0-rc |
|-----------|-------------|---------------------|
| Multi-user data isolation | **Implemented** | **Implemented** |
| Login / Registration UI | Better-auth (3rd party) | Self-built AuthProvider |
| Account settings page | Not available | Available |
| CSRF protection middleware | Not available | Available |
| SQLAlchemy ORM for user persistence | Not available | Available |
| JWT token refresh mechanism | Basic only | Full lifecycle |

**Conclusion:** `main` branch already provides complete multi-user data isolation at the storage and API layer. The `feat/auth-on-2.0-rc` branch replaces the third-party auth library with a self-built auth system.

---

## 1. What `main` Branch Already Implements

### 1.1 User Model

```python
# backend/packages/harness/deerflow/persistence/user/model.py
class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime]
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    needs_setup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_version: Mapped[int] = mapped_column(nullable=False, default=0)
```

### 1.2 Thread Isolation

- `ThreadMetaRow` has a `user_id` column (indexed)
- `ThreadMetaRepository.get()` / `search()` both filter by `WHERE user_id = ?`
- API routes use `@require_permission("threads", "delete|write", owner_check=True, require_existing=True)`

**Database path:** `threads_meta` table, `user_id` column with index.

### 1.3 Filesystem Isolation

`ThreadDataMiddleware` creates per-thread directories under user isolation scope:

```
{base_dir}/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}
{base_dir}/users/{user_id}/threads/{thread_id}/acp-workspace/
```

Path resolution uses `get_effective_user_id()` which reads from a `ContextVar[CurrentUser | None]`.

### 1.4 Memory Isolation

```
{base_dir}/users/{user_id}/memory.json
{base_dir}/users/{user_id}/agents/{agent_name}/memory.json
```

- `MemoryMiddleware` captures `user_id` via `get_effective_user_id()` at enqueue time
- Background timer thread uses the captured `user_id` (survives the `threading.Timer` boundary)
- Fact deduplication and context injection are all scoped per user

### 1.5 Runtime Context Isolation

```python
# deerflow/runtime/user_context.py
def get_effective_user_id() -> str:
    # Reads from runtime.context["user_id"] first, then contextvar, then "default"
```

Every middleware, tool, and subagent inherits the same `user_id` from this context system.

### 1.6 Auth Middleware

- `AuthMiddleware` in `app/gateway/auth_middleware.py` — fail-closed, rejects unauthenticated requests to non-public paths with 401
- JWT tokens contain `sub` (user_id), `exp`, `iat`, `ver` (token_version for revocation)
- `get_current_user_from_request()` fetches `User` from database, verifies `token_version`

---

## 2. Multi-Tenancy vs Multi-User Concept

### 2.1 Multi-User (Implemented)

**Scenario**: A single DeerFlow deployment serves multiple independent users. Each user can only see their own data.

```
Deployment A (DeerFlow single instance)
├── User Alice  →  can only see Alice's threads / memory / files
├── User Bob    →  can only see Bob's threads / memory / files
└── User Carol  →  can only see Carol's threads / memory / files
```

**Isolation mechanisms**:
- All `user_id` filtered API routes (`owner_check=True`)
- Filesystem partitioned by user directory
- Memory stored per user
- JWT token bound to user_id

### 2.2 Multi-Tenancy (Not Implemented)

**Scenario**: A single DeerFlow deployment serves multiple isolated **organizations/tenants**, each tenant has independent configuration, user system, and data.

```
DeerFlow SaaS
├── Tenant Org-A (independent config: model / api key / quota)
│   ├── Users A1, A2, A3
│   └── Data completely isolated from Org-B
├── Tenant Org-B (independent config: model / api key / quota)
│   ├── Users B1, B2
│   └── Data completely isolated from Org-A
└── Tenant Org-C ...
```

**Missing key elements**:

| Element | Multi-User (current) | Multi-Tenant (missing) |
|---------|---------------------|----------------------|
| **Tenant model** | None | Needs `Tenant` table |
| **User-tenant association** | Users are flat structure | `user.tenant_id` association |
| **Tenant-level config** | Global `config.yaml` | Per-tenant independent config |
| **API routing** | No tenant prefix | `/tenants/{tenant_id}/...` prefix |
| **Data isolation** | `user_id` column filtering | May need schema isolation or tenant_id filtering |
| **LangGraph namespace** | None | Needs `tenant_id` isolated checkpointer |
| **Quota / Billing** | None | Needs tenant-level quota/billing |

### 2.3 Summary Table

| | Multi-User | Multi-Tenancy |
|---|---|---|
| **Isolation unit** | User (User) | Organization (Tenant) |
| **Configuration** | Global shared | Tenant independent |
| **Use case** | Team internal multi-user collaboration | SaaS multi-customer isolation |
| **Implementation complexity** | Existing (main branch) | Needs to be designed from scratch |

DeerFlow `main` branch design is: **Single-tenant + Multi-user**.

To implement true multi-tenancy, a `tenant_id` concept needs to be introduced across all tables, APIs, configurations, and LangGraph namespaces.

**Important distinction:**

| Term | Definition | DeerFlow main branch |
|------|-----------|----------------------|
| Multi-tenancy | Isolated **tenant** deployments (e.g. SaaS with separate orgs) | **NOT implemented** |
| Multi-user | Multiple **users** within a single deployment, data isolated by `user_id` | **Implemented** |

---

## 3. What `feat/auth-on-2.0-rc` Adds

### 3.1 Self-Built Authentication System

| Component | Description |
|-----------|-------------|
| `backend/app/gateway/auth/` | JWT handling, password hashing (bcrypt), UserRepository, Provider Factory |
| `AuthMiddleware` + `CSRFMiddleware` | End-to-end auth + CSRF protection |
| `routers/auth` | Login, register, reset password endpoints |
| `frontend/src/core/auth/*` | AuthProvider, gateway-config, proxy-policy |
| `(auth)/login`, `(auth)/setup` | Login and initial setup pages |
| Account settings page | Change email, change password, logout |

### 3.2 SQLAlchemy ORM Migration

- `ceeccabc refactor(auth): migrate user repository to SQLAlchemy ORM`
- Unified persistence layer with async engine lifecycle
- `DatabaseConfig` controls both LangGraph checkpointer and application persistence

### 3.3 Security Hardening

| Commit | Fix |
|--------|-----|
| `745bf432` | Strict JWT validation in middleware (fix junk cookie bypass) |
| `e7a881b5` | Write initial admin password to 0600 file instead of logs |
| `2b33bfd7` | Wire `@require_permission(owner_check=True)` on all isolation routes |

### 3.4 DingTalk Channel Removed

`feat/auth-on-2.0-rc` deleted the DingTalk integration (`dingtalk.py` 740 lines), contributing to the net deletion of 57,681 lines.

---

## 4. Verification Guide

### 4.1 Check User Isolation

```bash
# Register two users and observe filesystem isolation
ls backend/.deer-flow/users/
```

Each user gets an isolated directory tree:

```
backend/.deer-flow/users/
├── {user_id_1}/
│   ├── threads/
│   │   └── {thread_id}/
│   │       └── user-data/{workspace,uploads,outputs}
│   ├── memory.json
│   └── agents/{agent_name}/memory.json
├── {user_id_2}/
│   └── ...
```

### 4.2 Check Database Isolation

```sql
SELECT thread_id, user_id, display_name FROM threads_meta WHERE user_id = ?;
```

Only threads belonging to the authenticated user are returned.

### 4.3 Check Memory Isolation

```bash
cat backend/.deer-flow/users/{user_id}/memory.json
```

Each user has a separate memory store.

---

## 5. Conclusion

### 5.1 Multi-User Login (Different Users Have Different Threads/Context/Memory)

**Yes, `main` branch already implements this.** The isolation mechanisms are:

1. **User ID** — UUID primary key, stored in JWT `sub` claim
2. **Thread isolation** — `user_id` indexed column in `threads_meta`, `owner_check=True` on all mutation APIs
3. **Filesystem isolation** — `{base_dir}/users/{user_id}/threads/{thread_id}/` directory structure
4. **Memory isolation** — `{base_dir}/users/{user_id}/memory.json` per-user store
5. **Context isolation** — `get_effective_user_id()` context system propagated through all middleware and tools

### 5.2 What's Missing in `main`

| Feature | Status |
|---------|--------|
| Self-built login page | Uses better-auth (3rd party) |
| Account settings (email/password) | Not available |
| CSRF middleware | Not available |
| SQLAlchemy ORM for users | Not available |
| Token refresh mechanism | Basic only |

### 5.3 Decision Guide

```
Need multi-user data isolation only?
  → main branch is sufficient

Need self-built auth (no third-party dependency)?
  → Implement based on feat/auth-on-2.0-rc pattern
    or cherry-pick relevant commits from that branch

Need true multi-tenancy (organizations/workspaces)?
  → Not available; requires significant new architecture
```

---

## 6. Reference

- Branch divergence point: `055e4df0490dbd1bca9ffc8f6b2330668933223b`
- `feat/auth-on-2.0-rc` latest commit: `2b33bfd7` (security: wire @require_permission(owner_check=True) on isolation routes)
- `main` latest commit: `45060a9f` (fix(runtime): avoid postgres aggregate row lock)