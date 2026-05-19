## 1. RPC 客户端

- [ ] 1.1 新建 `backend/packages/harness/deerflow/rpc/ins_base_org_service.py`，实现 `InsBaseOrgServiceClient` 类，调用 `ins-base-rpc` `/org/getAllParentOrg?orgId={orgId}` GET 接口，解析 AjaxResult 包装的响应
- [ ] 1.2 从 RPC 响应中提取 `data` 字段作为组织列表，Org 使用 TypedDict 定义必要字段（`orgId`、`parentId`、`orgName`、`orgType`）

## 2. Provider 租户解析

- [ ] 2.1 在 `InsBaseAuthProvider.__init__` 新增可选参数 `tenant_repo: TenantRepository | None`
- [ ] 2.2 新增私有方法 `_resolve_tenant_id(org_id: str) -> str`：orgId 为 "0" 直接返回 "default"；否则调用 `InsBaseOrgServiceClient.get_all_parent_org()`，遍历结果找 `orgType == 13` 的节点作为 tenant_id，找不到则返回 "default"
- [ ] 2.3 在 `_resolve_tenant_id` 中实现 get-or-create：查询 `TenantRepository.get(tenant_id)`，存在则直接返回；不存在则创建 `TenantConfig(tenant_id=tenant_id, name=f"工厂-{tenant_id}", daily_quota_usd=0, monthly_quota_usd=0)`，捕获 `ValueError`（并发创建）后重新 get
- [ ] 2.4 在 `authenticate()` 和 `get_user()` 方法中提取 `orgId`（从认证响应中 `user.org.orgId` 或 `user.orgId`），调用 `_resolve_tenant_id(org_id)` 替代硬编码的 `"default"`
- [ ] 2.5 RPC 调用失败或找不到工厂节点时抛出 `RuntimeError`，中断登录流程

## 3. 依赖注入

- [ ] 3.1 修改 `backend/app/gateway/deps.py` 中 `get_ins_base_provider()`，在创建 `InsBaseAuthProvider` 时注入 `TenantRepository`（从 `get_session_factory()` 获取，若 `sf` 为 None 则 `tenant_repo` 为 None，provider 内部降级处理）

## 4. 中间件

- [ ] 4.1 修改 `backend/app/gateway/auth/middleware.py` 中 ins_base 认证路径，将 `tenant_id = "default"` 改为 `tenant_id = getattr(user, "tenant_id", "default")`
- [ ] 4.2 确认 `request.state.user["tenant_id"]` 也使用正确的 tenant_id

## 5. 测试

- [ ] 5.1 新增 `backend/tests/test_ins_base_org_tenant.py`，覆盖：orgId=0 → default、orgId 非 0 且找到工厂节点、orgId 非 0 但无工厂节点抛出异常、RPC 调用失败抛出异常、租户已存在直接使用、租户不存在自动创建、并发创建幂等。使用 mock 替代真实 RPC 和数据库调用
