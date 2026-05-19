## 背景

当前 `InsBaseAuthProvider` 在两个流程中都硬编码 `tenant_id = "default"`：
- `authenticate()` — 登录时（第 125 行）
- `get_user()` — token 验证时（第 202 行）

`create_auth_middleware` 中间件在 ins_base Bearer token 路径（第 129 行）也硬编码 `tenant_id = "default"`。需要改为根据用户所属组织的"工厂"节点自动确定租户。

## 目标 / 非目标

**目标：**
- ins_base 登录和 token 验证流程中根据用户 orgId 自动解析租户
- orgId 为 "0" 时使用 `"default"` 租户（向后兼容）
- orgId 非 "0" 时通过 `getAllParentOrg` RPC 查找工厂（orgType=13）节点，以其 orgId 作为 tenant_id
- 工厂对应的租户不存在时自动创建，限额全部设为 0
- 中间件使用 provider 返回的 tenant_id，不再硬编码

**非目标：**
- 不修改租户切换逻辑（前端仍可通过 `X-DeerFlow-Tenant` header 覆盖）
- 不修改 local auth provider 的租户逻辑
- 不修改 login 路由 `/api/v1/auth/ins-base/login` 的响应格式

## 设计决策

### 决策 1：租户解析逻辑放在 `InsBaseAuthProvider` 内部

**选择**：在 `InsBaseAuthProvider` 中新增 `_resolve_tenant_id(org_id)` 私有方法，该方法完成 RPC 调用 + 租户 get-or-create。

**备选方案**：将租户解析逻辑放在中间件中 → 不采用，因为中间件不应包含业务逻辑，且登录路由也需要租户解析（登录时设置 cookie 中的 tenant_id）。

**理由**：Provider 是 ins_base 认证的单一入口点，`authenticate()` 和 `get_user()` 都需要租户解析。将逻辑集中在 provider 中避免重复。

### 决策 2：新增 `InsBaseOrgServiceClient` RPC 客户端

**选择**：在 `deerflow/rpc/` 中新增 `ins_base_org_service.py`，调用 `ins-base-rpc`（而非 `ins-bus-rpc`）的 `/org/getAllParentOrg`。

**理由**：需求明确指定调用 `ins-base-rpc` 服务。虽然当前 `OrganizeServiceClient` 调用的是 `ins-bus-rpc`，但这是不同的微服务端点。

### 决策 3：通过构造函数注入 `TenantRepository`

**选择**：`InsBaseAuthProvider.__init__` 新增可选的 `tenant_repo: TenantRepository | None` 参数。`get_ins_base_provider()` 在创建 provider 时注入。

**理由**：`TenantRepository` 是线程安全的（基于 session_factory），可以作为单例共享。这样 provider 可以独立完成租户 get-or-create，无需回调。

### 决策 4：中间件读取 user.tenant_id 而非硬编码

**选择**：中间件中 `tenant_id = getattr(user, "tenant_id", "default")` 替代硬编码的 `tenant_id = "default"`。

**备选方案**：在中间件中再次调用租户解析 → 不采用，get_user() 已返回正确的 tenant_id，重复调用浪费 RPC。

### 决策 5：`getAllParentOrg` 返回列表即为完整的祖先链

**选择**：直接遍历返回的 List<Org>，查找 `orgType == 13` 的节点。若多个工厂节点，取第一个（最近的父节点）。

**备选方案**：通过 ancestors 字段自行解析 → 不采用，RPC 返回的列表已经组织好父子关系，直接遍历即可。

## 风险与取舍

- **[RPC 调用失败]** → 抛出 `RuntimeError("获取组织信息失败，无法完成登录")`，中断登录/认证流程
- **[找不到工厂节点]** → 抛出 `RuntimeError("未找到所属工厂（orgType=13），无法确定租户，请联系管理员")`，中断登录/认证流程
- **[租户自动创建竞争]** → TenantRepository.create() 对已存在的 tenant_id 会抛 ValueError，捕获后 get 即可。由于创建是幂等的（get-or-create），不会产生数据问题
- **[租户名称为空]** → 自动创建时使用工厂 orgId 作为 name（如 `工厂-{org_id}`）
