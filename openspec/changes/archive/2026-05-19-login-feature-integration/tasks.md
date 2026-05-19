## 1. Configuration

- [x] 1.1 在 `AuthConfig` 中增加 `provider: str = "local"` 和 `rsa_public_key: str = ""` 字段
- [x] 1.2 在 `config.yaml` 的 `rpc.services` 中注册 `ins-base-rpc` 服务（base_url 或 Nacos discovery 配置）
- [x] 1.3 在 `config.example.yaml` 中添加 `auth.provider` 和 `auth.rsa_public_key` 示例配置

## 2. RSA Encryption Utility

- [x] 2.1 创建 `backend/app/gateway/auth/rsa_utils.py`，实现 `rsa_encrypt(plaintext: str, public_key_pem: str) -> str` 函数
- [x] 2.2 实现 PEM 格式归一化函数 `normalize_pem()`，处理多行/单行/带空格等不同格式的 RSA 公钥
- [x] 2.3 添加 RSA 加密切片测试覆盖正常加密、不同 PEM 格式、空密钥等场景

## 3. InsBaseAuthProvider

- [x] 3.1 创建 `backend/app/gateway/auth/ins_base_provider.py`，实现 `InsBaseAuthProvider` 类（继承 `AuthProvider`）
- [x] 3.2 实现 `authenticate()` 方法：RSA 加密凭据 → 调用 `ins-base-rpc` `/auth/login` → 解析响应 → 返回 `User` 对象
- [x] 3.3 实现 `get_user()` 方法：通过 token 调用 `ins-base-rpc` `/auth/authentication` → 返回用户信息和权限
- [x] 3.4 实现 `refresh_token()` 方法：调用 `ins-base-rpc` `/auth/refresh` → 返回新 token
- [x] 3.5 添加单元测试覆盖登录成功/失败、token 认证、token 刷新、服务不可用等场景

## 4. Auth Middleware Integration

- [x] 4.1 在 `backend/app/gateway/auth/middleware.py` 中增加 `InsBaseAuthProvider` 的创建和注入（当 `auth_config.provider == "ins_base"` 时）
- [x] 4.2 集成 InsBase token 验证到现有 auth middleware 的 token 检查流程中
- [x] 4.3 实现 token 缓存逻辑（可选，减少重复 RPC 调用）

## 5. API Endpoints

- [x] 5.1 在现有 auth router（或新建 router）中增加 InsBase 登录端点，使用 `InsBaseAuthProvider`
- [x] 5.2 登录成功后为用户分配默认租户 "default"
- [x] 5.3 注册新的 auth router 到 Gateway app

## 6. 关闭本地注册功能

- [x] 6.1 在 `auth.py` 中移除 `POST /api/v1/auth/register` 端点（改为返回 410 Gone）
- [x] 6.2 从 `backend/app/gateway/auth_middleware.py` 的 `_PUBLIC_EXACT_PATHS` 中移除 `/api/v1/auth/register`
- [x] 6.3 从 `backend/app/gateway/auth/middleware.py` 的 public paths 中移除 `/api/v1/auth/register`
- [x] 6.4 从 `backend/app/gateway/csrf_middleware.py` 的 public paths 中移除 `/api/v1/auth/register`
- [x] 6.5 更新相关测试，移除注册功能的测试用例

## 7. Integration Tests

- [x] 7.1 编写集成测试：mock ins-base-rpc 响应，测试完整登录/认证/刷新流程
- [x] 7.2 测试默认租户 "default" 的赋值逻辑
- [x] 7.3 测试 RSA 公钥未配置时的错误处理
- [x] 7.4 测试注册端点已关闭，返回 410
