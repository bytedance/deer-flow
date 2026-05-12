# 移除 tenants.json，改为纯数据库租户检查

## Context

用户 `yh@shenguyuan.com` 登录后报"租户已禁用"，根因是该用户属于 `zm` 租户，但 `zm` 从未在 `tenants.json` 中注册（也未迁移到 DB）。系统已有 DB-backed `TenantRepository`，Gateway 中间件已使用它，但 `lead_agent/agent.py` 仍通过同步 `TenantStorage()` 读取 JSON 文件做租户校验。用户要求彻底去掉 `tenants.json`，所有租户检查走数据库。

## 修改文件

1. `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (lines 432-438)
2. `backend/app/gateway/app.py` (lines 157-191)
3. `backend/.deer-flow/tenants.json` (删除)
4. `backend/packages/harness/deerflow/config/tenant_storage.py` (可选：保留 `TenantConfig` dataclass，删除 `TenantStorage` class)

## 实施步骤

### Step 1: 替换 lead_agent 中的 TenantStorage → TenantRepository

文件: `packages/harness/deerflow/agents/lead_agent/agent.py` lines 432-438

当前代码:
```python
ts = TenantStorage()
tc = ts.get(tenant_id)
if tc is None:
    raise PermissionError(f"Tenant {tenant_id!r} does not exist")
if not tc.is_active:
    raise PermissionError(f"Tenant {tenant_id!r} is disabled")
```

替换为（复用同文件 lines 362-388 已有的 async-from-sync 模式）:
```python
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.tenant.repository import TenantRepository

sf = get_session_factory()
if sf is not None:
    repo = TenantRepository(sf)

    async def _check_tenant():
        return await repo.get(tenant_id)

    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                tc = executor.submit(asyncio.run, _check_tenant()).result()
        else:
            tc = loop.run_until_complete(_check_tenant())
    except RuntimeError:
        tc = asyncio.run(_check_tenant())

    if tc is None:
        raise PermissionError(f"Tenant {tenant_id!r} does not exist")
    if not tc.is_active:
        raise PermissionError(f"Tenant {tenant_id!r} is disabled")
else:
    # backend=memory mode — skip tenant enforcement
    pass
```

### Step 2: 启动时自动补全缺失租户

文件: `app/gateway/app.py`，在现有 tenants.json 迁移代码之后，增加一段：扫描 users 表中所有 distinct `tenant_id`，对不在 tenants 表中的自动创建。

```python
# Auto-create tenants referenced by users but missing from tenants table
user_tenants = await conn.execute(text("SELECT DISTINCT tenant_id FROM users"))
for (tid,) in user_tenants.fetchall():
    if tid:
        existing = await conn.execute(text("SELECT 1 FROM tenants WHERE tenant_id = :tid"), {"tid": tid})
        if existing.scalar() is None:
            await conn.execute(
                text("""
                    INSERT INTO tenants (tenant_id, name, is_active, daily_quota_usd, monthly_quota_usd, created_at, updated_at)
                    VALUES (:tid, :name, 1, 50.0, 1000.0, :now, :now)
                """),
                {"tid": tid, "name": tid, "now": now},
            )
            logger.info("Auto-created missing tenant %r (referenced by users table)", tid)
```

### Step 3: 删除 tenants.json

删除文件: `backend/.deer-flow/tenants.json`

保留 `app.py` 中的 tenants.json 迁移代码（无害 — 文件不存在时跳过），以兼容其他部署环境可能仍有该文件的情况。

### Step 4: 清理 TenantStorage 引用（可选）

- `lead_agent/agent.py` 中移除 `from deerflow.config.tenant_storage import TenantStorage` import
- `deerflow/config/tenant_storage.py` 中保留 `TenantConfig` dataclass（`TenantRepository` 依赖它），可以删除 `TenantStorage` class 或标记 deprecated

## 验证

1. `cd backend && PYTHONPATH=. uv run pytest tests/test_auth_tenant_detection.py -v` — 确认 18 个测试通过
2. `PYTHONPATH=. uv run pytest tests/ -v` — 全量测试
3. 启动服务后用 `yh@shenguyuan.com` 登录，确认不再报"租户已禁用"
4. 确认 `zm` 租户在启动时被自动创建到 DB
