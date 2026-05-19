## 背景

ins_base 认证提供商目前为所有用户硬编码 `tenant_id = "default"`，导致来自不同组织（工厂）的用户无法自动分配到对应的租户。用户所属组织链中类型为"工厂"的节点应映射为用户的默认租户，实现多租户自动隔离。

## 变更内容

- 新增 `InsBaseOrgServiceClient` RPC 客户端，调用 `ins-base-rpc` 的 `/org/getAllParentOrg` 接口获取用户的父组织链
- 修改 `InsBaseAuthProvider.get_user()`：从认证响应中提取 `orgId`，orgId 为 "0" 时使用 `"default"` 租户，否则通过父组织链查找工厂类型（orgType=13）节点作为租户 ID
- 修改 `InsBaseAuthProvider.authenticate()`（登录流程）：同样根据 orgId 确定租户，替代硬编码的 `"default"`
- 修改 `create_auth_middleware`（中间件）：ins_base Bearer token 认证路径不再硬编码 `"default"`，改为从 provider 获取的租户 ID
- 自动创建租户：若工厂对应的租户在数据库中不存在，则自动创建，所有限额（daily_quota_usd、monthly_quota_usd）设为 0

## 能力划分

### 新增能力
- `ins-base-org-tenant-resolution`: 基于 ins_base 用户组织链自动解析租户，包括父组织 RPC 调用、工厂节点筛选、租户自动创建

### 变更能力
<!-- 无现有 spec 需要修改 -->

## 影响范围

- 受影响代码：`backend/app/gateway/auth/ins_base_provider.py`、`backend/app/gateway/auth/middleware.py`、`backend/packages/harness/deerflow/rpc/`（新增 org service client）
- 受影响系统：`ins-base-rpc` Java 微服务（新增 `/org/getAllParentOrg` 调用）
- 数据库影响：可能自动创建新租户行（限额为 0）
- 前端：无需修改（租户 ID 通过现有 cookie/header 机制传递）
