# 用户认证

## 目的

通过集成 ins-base-rpc 实现用户认证功能，支持 RSA 加密凭据登录、token 认证和刷新，统一由 Java 端管理用户注册。

## 新增需求

### Requirement: 用户通过 RSA 加密凭据登录

系统 SHALL 允许用户使用用户名和密码进行登录，登录前使用 RSA 公钥对凭据进行加密。

#### Scenario: 成功登录
- **WHEN** 用户提供正确的用户名和密码
- **AND** 系统使用 RSA 公钥对用户名和密码进行 PKCS1v15 加密并 Base64 编码
- **AND** 系统调用 `ins-base-rpc` `/auth/login` 接口并传入加密后的凭据
- **AND** 接口返回成功响应（code=200）
- **THEN** 系统返回包含 token 和 refresh token 的登录成功响应

#### Scenario: 登录失败 - 密码错误
- **WHEN** 用户提供错误的密码
- **AND** 系统调用 `ins-base-rpc` `/auth/login` 接口
- **AND** 接口返回错误响应
- **THEN** 系统返回登录失败错误信息

#### Scenario: 登录失败 - 用户已停用
- **WHEN** 用户提供正确的凭据
- **AND** `ins-base-rpc` 返回的用户状态非 NORMAL 或 HIDE
- **THEN** 系统返回 "用户已停用" 错误信息

#### Scenario: 登录失败 - ins-base-rpc 不可用
- **WHEN** 用户提供凭据
- **AND** `ins-base-rpc` 服务不可用或超时
- **THEN** 系统返回认证服务不可用的错误信息

### Requirement: 用户通过 token 认证

系统 SHALL 允许用户通过携带 token 进行认证，以验证身份并获取权限信息。

#### Scenario: 成功认证
- **WHEN** 用户提供有效的 token
- **AND** 系统调用 `ins-base-rpc` `/auth/authentication` 接口验证 token
- **AND** 接口返回成功响应
- **THEN** 系统返回用户信息和权限列表

#### Scenario: 认证失败 - 无效 token
- **WHEN** 用户提供无效的 token
- **AND** 系统调用 `ins-base-rpc` `/auth/authentication` 接口
- **AND** 接口返回错误
- **THEN** 系统返回 "无效token" 错误信息

#### Scenario: 认证失败 - 用户已停用
- **WHEN** 用户提供有效的 token
- **AND** `ins-base-rpc` 返回的用户状态非 NORMAL 或 HIDE
- **THEN** 系统返回 "用户已停用" 错误信息

### Requirement: 用户刷新 token

系统 SHALL 允许用户使用 refresh token 刷新过期的 token。

#### Scenario: 成功刷新
- **WHEN** 用户提供有效的 refresh token
- **AND** 系统调用 `ins-base-rpc` `/auth/refresh` 接口
- **AND** 接口返回成功响应
- **THEN** 系统返回新的 token

#### Scenario: 刷新失败 - 无效 refresh token
- **WHEN** 用户提供无效的 refresh token
- **AND** 系统调用 `ins-base-rpc` `/auth/refresh` 接口
- **AND** 接口返回错误
- **THEN** 系统返回 "无效refresh" 错误信息

### Requirement: 登录用户使用默认租户

所有通过 ins-base-rpc 登录的用户 SHALL 使用默认租户 "default"。

#### Scenario: 登录后租户为 default
- **WHEN** 用户通过 ins-base-rpc 登录成功
- **AND** 系统创建本地用户记录
- **THEN** 用户的 tenant_id 被设置为 "default"

### Requirement: RSA 公钥可配置

系统 SHALL 支持通过配置文件配置 RSA 公钥，用于加密登录凭据。

#### Scenario: 配置 RSA 公钥
- **WHEN** 系统启动时加载配置
- **AND** `auth.rsa_public_key` 字段配置了有效的 RSA 公钥 PEM 字符串
- **THEN** 登录时使用该公钥加密用户名和密码

#### Scenario: RSA 公钥未配置
- **WHEN** 系统启动时加载配置
- **AND** `auth.rsa_public_key` 为空
- **THEN** 登录接口返回配置错误信息

## 已移除的需求

### Requirement: 用户注册（本地）

**Reason**: 对接 ins-base-rpc 后，用户统一由 Java 端管理注册，本地注册不再需要。`/api/v1/auth/register` 端点已移除，返回 410 Gone。
