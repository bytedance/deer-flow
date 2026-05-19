# 组织-租户解析能力

## 目的

根据 ins_base 认证用户的组织信息（orgId）解析对应的租户，通过 RPC 调用获取父组织链并按工厂节点（orgType=13）确定 tenant_id，支持自动创建不存在的租户。

## 新增需求

### Requirement: orgId 为零映射到默认租户

当认证用户的 `org.orgId` 为 `"0"` 时，系统必须使用 `"default"` 租户。

#### Scenario: superAdmin 的 orgId 为 0 获得默认租户

- **WHEN** 用户通过 ins_base 认证且认证响应包含 `user.org.orgId = "0"`
- **THEN** 系统直接分配 `tenant_id = "default"`，不调用 `getAllParentOrg` RPC

### Requirement: orgId 非零触发父组织 RPC 调用

当认证用户的 `org.orgId` 不为 `"0"` 时，系统必须调用 `ins-base-rpc` 的 `GET /org/getAllParentOrg?orgId={orgId}` 接口。

#### Scenario: 用户 orgId 非零调用父组织接口

- **WHEN** 用户通过 ins_base 认证且 `user.org.orgId` 为 `"5"`
- **THEN** 系统调用 `ins-base-rpc` 的 `GET /org/getAllParentOrg?orgId=5`

### Requirement: 筛选工厂节点作为租户

系统必须从父组织列表中选取 `orgType == 13`（工厂）的组织 ID 作为 tenant_id。若存在多个工厂节点，必须使用第一个。

#### Scenario: 父组织链包含工厂节点

- **WHEN** `getAllParentOrg` 返回 `[{orgId: 3, orgType: 10}, {orgId: 5, orgType: 13}, {orgId: 7, orgType: 13}]`
- **THEN** 系统使用 `"5"` 作为 `tenant_id`（第一个工厂节点）

#### Scenario: 父组织链无工厂节点

- **WHEN** `getAllParentOrg` 返回的列表中没有任何 `orgType == 13` 的节点
- **THEN** 系统抛出 `RuntimeError`，消息为"未找到所属工厂（orgType=13），无法确定租户，请联系管理员"，登录/认证流程中断

### Requirement: 租户获取或创建

当找到工厂组织后，系统必须检查数据库中是否存在对应租户。若存在则直接使用；若不存在则必须创建新租户，设置 `daily_quota_usd = 0`、`monthly_quota_usd = 0`、`is_active = True`。

#### Scenario: 租户已存在

- **WHEN** 工厂 orgId 为 `"5"` 且数据库中已存在 `tenant_id = "5"` 的租户
- **THEN** 系统直接使用已有租户，不新建

#### Scenario: 租户不存在

- **WHEN** 工厂 orgId 为 `"5"` 且数据库中不存在 `tenant_id = "5"` 的租户
- **THEN** 系统创建新租户，参数为 `tenant_id = "5"`、`name = "工厂-5"`、`is_active = True`、`daily_quota_usd = 0`、`monthly_quota_usd = 0`

#### Scenario: 并发创建租户

- **WHEN** 两个并发请求同时尝试创建租户 `"5"` 且第一个成功
- **THEN** 第二个请求捕获重复错误，查询已有租户后使用

### Requirement: RPC 失败必须中断登录

当 `getAllParentOrg` RPC 调用失败（网络错误、超时或返回非 200），系统必须抛出 `RuntimeError` 中断登录/认证流程，不得降级。

#### Scenario: RPC 调用超时

- **WHEN** `getAllParentOrg` RPC 调用超时
- **THEN** 系统抛出 `RuntimeError`，消息为"获取组织信息失败，无法完成登录"

#### Scenario: RPC 返回非 200

- **WHEN** `getAllParentOrg` RPC 调用返回 `code != 200`
- **THEN** 系统抛出 `RuntimeError`，消息为"获取组织信息失败，无法完成登录"

### Requirement: 登录和 token 验证均须解析租户

租户解析逻辑必须同时应用于 `authenticate()`（登录流程）和 `get_user()`（token 验证流程）。

#### Scenario: 登录时根据 orgId 解析租户

- **WHEN** 用户通过 `POST /api/v1/auth/ins-base/login` 提交凭证登录
- **THEN** 登录响应 cookie 中的 `tenant_id` 反映用户组织对应的解析结果

#### Scenario: token 验证时根据 orgId 解析租户

- **WHEN** 认证中间件通过 `get_user()` 验证 Bearer token
- **THEN** 返回的 user 对象中的 `tenant_id` 反映用户组织对应的解析结果

### Requirement: 中间件使用 provider 解析的租户

认证中间件必须使用 `InsBaseAuthProvider.get_user()` 返回的 user 对象中的 `tenant_id`，不得硬编码 `"default"`。

#### Scenario: 中间件从 user 对象读取租户

- **WHEN** ins_base 中间件认证请求且 `get_user()` 返回 `tenant_id = "7"` 的 user 对象
- **THEN** 中间件设置 `request.state.user.tenant_id = "7"` 并 `set_current_tenant_id("7")`
