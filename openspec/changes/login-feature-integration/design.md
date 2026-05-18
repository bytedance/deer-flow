## Context

当前项目已有基础的 JWT + API Key 认证系统（默认关闭），以及一套基于 RPC Client（httpx + Nacos 服务发现）的 Java 微服务调用体系。需要在现有 AuthProvider 模式下扩展一个 `InsBaseAuthProvider`，对接 `ins-base-rpc` 的认证接口，实现企业级用户登录。

- `ins-base-rpc` 是一套 Java 微服务，暴露了 `/auth/login`、`/auth/authentication`、`/auth/refresh` 三个 HTTP GET 接口
- 登录时需要将用户名密码用 RSA 公钥加密后传输（PKCS1v15 padding + Base64）
- 已有的 `RpcClient` 在 `deerflow/rpc/rpc_client.py` 提供了 `call_raw()` 方法，可直接按路径调用已注册的 RPC 服务
- 现有的 `AuthProvider` 抽象类位于 `backend/app/gateway/auth/providers.py`
- 现有的 `AuthConfig` 位于 `deerflow/config/auth_config.py`（`enabled: bool = False`）
- 所有登录用户采用默认租户 "default"

## Goals / Non-Goals

**Goals:**
- 实现 RSA 加密工具函数，用于登录时加密用户名密码
- 实现 `InsBaseAuthProvider`，通过 RPC 调用 `ins-base-rpc` 完成登录
- 实现 `/auth/authentication` 调用，验证 token 并获取用户权限
- 实现 `/auth/refresh` 调用，刷新 token
- 在 `config.yaml` 中注册 `ins-base-rpc` RPC 服务配置
- 所有登录用户携带默认租户 `default`
- 关闭现有的本地注册端点 `POST /api/v1/auth/register`，用户注册统一由 ins-base-rpc 管理

**Non-Goals:**
- 不修改现有的本地 JWT/API Key 认证流程
- 不实现密码重置
- 不实现多租户登录选择（统一使用 default）

## Decisions

### Decision 1: 在 app.gateway.auth 下创建 InsBaseAuthProvider 作为独立模块

**选择**: 在 `backend/app/gateway/auth/ins_base_provider.py` 中创建 `InsBaseAuthProvider`，实现 `AuthProvider` 接口。

**原因**: 保持与已有 `LocalAuthProvider` 一致的设计模式，便于在 app.py 中按条件注入。

**替代方案**: 直接放在 backend/app/gateway/auth/providers.py 中 → 文件会臃肿，不利于扩展和测试。

### Decision 2: 使用现有的 RpcClient.call_raw() 调用 ins-base-rpc

**选择**: 复用 `deerflow.rpc.rpc_client.get_rpc_client()` 获取单例 `RpcClient`，使用 `call_raw()` 调用 `/auth/login`、`/auth/authentication`、`/auth/refresh`。

**原因**: 项目已有完整的 RPC 调用基础设施（Nacos 服务发现、重试、超时控制），无需重复实现。

**配置**: 在 `config.yaml` 的 `rpc.services` 中添加 `ins-base-rpc` 条目，配置 `base_url` 或 `discovery`。

### Decision 3: RSA 加密工具作为独立工具函数

**选择**: 在 `backend/app/gateway/auth/rsa_utils.py` 中实现 `rsa_encrypt()` 函数，使用 `cryptography` 库的 RSA PKCS1v15 加密。

**原因**: 项目中已有 `cryptography` 作为依赖（通过 jose/passlib 引入），无需新增依赖。

**注意**: Python 的 `cryptography` 库已经包含在项目依赖中。

### Decision 4: 登录成功后直接使用 ins-base-rpc 返回的 token，不创建本地二次 JWT

**选择**: 登录成功后将 `ins-base-rpc` 返回的 token 作为当前用户的认证凭据返回给前端。后续认证（/auth/authentication）以前端携带的 token 为准。

**原因**: 减少 token 链的复杂度，ins-base-rpc 返回的 token 本身是 JWT，包含了用户信息。如果创建本地二次 JWT，需要额外维护 token 映射关系。

**替代方案**: 创建本地 JWT 包装 ins-base token → 增加了一层间接性，每次请求需要解包两次，增加了复杂度且没有带来额外安全收益。

### Decision 5: 认证中间件集成

**选择**: 在现有 `create_auth_middleware()` 中增加一个新的 Provider 类型检测：当 `auth_config.provider == "ins_base"` 时，对受保护路由调用 `InsBaseAuthProvider.get_user()` 进行 token 验证。

**原因**: 现有的 auth middleware 在 auth enabled 时已经会检查 JWT/API Key。InsBase 的认证流程与现有的 JWTHandler 不同（需要调用远程服务），所以需要在 middleware 中增加特定的 InsBase token 验证逻辑。

### Decision 6: 配置方式

**选择**: 在 `AuthConfig` 中新增 `provider: str = "local"` 字段，设置为 `"ins_base"` 时启用 InsBase 认证。

**RSA 公钥配置**: 在 `AuthConfig` 中新增 `rsa_public_key: str = ""` 字段。

**原因**: 与现有配置系统一致，通过 config.yaml 统一管理认证配置，测试中可通过 reset_auth_config() 重置。

### Decision 7: 关闭本地注册端点

**选择**: 移除 `POST /api/v1/auth/register` 端点的路由注册，同时从 `AuthMiddleware._PUBLIC_EXACT_PATHS` 和 `CSRFMiddleware`、`create_auth_middleware` 的公共路径白名单中移除 `/api/v1/auth/register`。

**原因**: 对接 ins-base-rpc 后，用户统一由 Java 端管理注册。本地注册功能不再需要，关闭后避免用户绕过 ins-base-rpc 直接在本地创建账号。

**涉及改动位置**:
- `backend/app/gateway/routers/auth.py` — 删除 `register` endpoint 或使其返回 400
- `backend/app/gateway/auth_middleware.py` — `_PUBLIC_EXACT_PATHS` 中移除 `/api/v1/auth/register`
- `backend/app/gateway/auth/middleware.py` — public paths 中移除 `/api/v1/auth/register`
- `backend/app/gateway/csrf_middleware.py` — public paths 中移除 `/api/v1/auth/register`
- 相关测试文件更新

| 风险 | 缓解措施 |
|------|----------|
| ins-base-rpc 服务不可用时，全部用户无法登录 | 增加超时配置（默认 5s）；在 AuthConfig 中可配置 fallback 行为 |
| 每次请求都调用远程 /auth/authentication 增加延迟 | 使用简单的本地 token 缓存（TTL 5分钟），避免频繁 RPC 调用 |
| RSA 密钥对变更需要同步更新 DeerFlow 配置 | rsa_public_key 通过 config.yaml 配置，变更后重启即生效 |
| ins-base-rpc 接口响应格式变化 | 在 InsBaseAuthProvider 中做健壮的响应解析，对异常响应记录详细日志 |
| Nacos 或网络问题导致服务发现失败 | 支持通过 base_url 直接配置 ins-base-rpc 地址，绕过 Nacos |
