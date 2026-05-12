# Plan: Migrate TenantStorage from JSON to Database

## Context

The user expects tenant management data to be consistent with the login/user system (database-backed), not a separate JSON file (tenants.json). Currently users are in SQLite but tenants are in a JSON file, causing data inconsistency.

## Approach

Create a tenants table in the database and replace JSON-based TenantStorage with SQL-backed TenantRepository, following existing patterns (ThreadMetaRepository, SQLiteUserRepository).

## Steps

### 1. Create TenantRow ORM model
NEW: backend/packages/harness/deerflow/persistence/tenant/model.py
- tenant_id (PK), name, is_active, daily_quota_usd, monthly_quota_usd, created_at, updated_at

### 2. Create TenantRepository (async)
NEW: backend/packages/harness/deerflow/persistence/tenant/repository.py
- Same interface as current TenantStorage: list_all, get, create, update, delete, ensure_default

### 3. Add startup migration in app.py
File: backend/app/gateway/app.py (_ensure_admin_user)
- CREATE TABLE IF NOT EXISTS tenants
- One-time import from tenants.json if table is empty

### 4. Initialize on app.state
File: backend/app/gateway/app.py
- app.state.tenant_store = TenantRepository(session_factory)

### 5. Add get_tenant_store(request) dependency
File: backend/app/gateway/deps.py

### 6. Update admin.py
File: backend/app/gateway/routers/admin.py
- Replace _get_tenant_storage() with get_tenant_store(request)

### 7. Update auth middleware
File: backend/app/gateway/auth/middleware.py
- _check_tenant_active() uses cached DB singleton instead of JSON

### 8. Update tenant_status.py
File: backend/app/gateway/routers/tenant_status.py

### 9. Update tests
File: backend/tests/test_admin_router.py

## Verification

1. make dev from project root
2. Login as superadmin, check admin tenant page shows correct data
3. CRUD tenants, confirm DB persistence
4. make test from backend directory
