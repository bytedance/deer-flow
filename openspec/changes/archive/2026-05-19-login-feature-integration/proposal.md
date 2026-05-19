## Why

当前项目缺少登录认证功能，用户无法通过账号密码登录系统。需要对接 `ins-base-rpc` 服务的认证接口，实现用户登录、token 认证和 token 刷新能力，并采用默认租户 "default" 为所有登录用户分配租户。

## What Changes

- 新增登录接口，使用 RSA 加密用户名密码后调用 `ins-base-rpc` `/auth/login` 获取 token 和 refresh token
- 新增 token 认证中间件/拦截器，调用 `ins-base-rpc` `/auth/authentication` 验证 token 有效性并获取用户信息和权限
- 新增 token 刷新接口，调用 `ins-base-rpc` `/auth/refresh` 刷新 token
- 所有登录用户统一使用默认租户 "default"
- 关闭现有的本地注册功能（`/api/v1/auth/register` 端点），用户注册由 ins-base-rpc 统一管理

## Capabilities

### New Capabilities
- `user-auth`: 用户认证能力，包含登录、token 认证、token 刷新三个子功能，对接 ins-base-rpc 认证服务

### Modified Capabilities
<!-- No existing capabilities are modified -->

## Impact

- 新增 RPC 客户端模块，对接 ins-base-rpc 服务
- 新增 RSA 加密工具类（用于登录时加密用户名密码）
- 新增认证中间件/过滤器，拦截请求并验证 token
- 新增登录、认证、刷新三个 API 端点
- 依赖：ins-base-rpc 服务、JWT 解析能力、RSA 公钥配置
