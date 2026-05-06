# Authentication Upgrade Guide

DeerFlow 内置了认证模块。本文档面向从无认证版本升级的用户。

## 核心概念

认证模块采用**始终强制**策略：

- 首次启动时自动创建 admin 账号，随机密码打印到控制台日志
- 认证从一开始就是强制的，无竞争窗口
- 历史对话（升级前创建的 thread）自动迁移到 admin 名下

## 升级步骤

### 1. 更新代码

```bash
git pull origin main
cd backend && make install
```

### 2. 首次启动

```bash
make dev
```

控制台会输出：

```
============================================================
  Admin account created on first boot
  Email:    admin@deerflow.dev
  Password: aB3xK9mN_pQ7rT2w
  Change it after login: Settings → Account
============================================================
```

如果未登录就重启了服务，不用担心——只要 setup 未完成，每次启动都会重置密码并重新打印到控制台。

### 3. 登录

访问 `http://localhost:2026/login`，使用控制台输出的邮箱和密码登录。

### 4. 修改密码

登录后进入 Settings → Account → Change Password。

### 5. 添加用户（可选）

其他用户通过 `/login` 页面注册，自动获得 **user** 角色。每个用户只能看到自己的对话。

## 安全机制

| 机制 | 说明 |
|------|------|
| JWT HttpOnly Cookie | Token 不暴露给 JavaScript，防止 XSS 窃取 |
| CSRF Double Submit Cookie | 所有 POST/PUT/DELETE 请求需携带 `X-CSRF-Token` |
| bcrypt 密码哈希 | 密码不以明文存储 |
| 多租户隔离 | 用户只能访问自己的 thread |
| HTTPS 自适应 | 检测 `x-forwarded-proto`，自动设置 `Secure` cookie 标志 |

## 常见操作

### 忘记密码

```bash
cd backend

# 重置 admin 密码
python -m app.gateway.auth.reset_admin

# 重置指定用户密码
python -m app.gateway.auth.reset_admin --email user@example.com
```

会输出新的随机密码。

### 完全重置

删除用户数据库，重启后自动创建新 admin：

```bash
rm -f backend/.deer-flow/users.db
# 重启服务，控制台输出新密码
```

## 数据存储

| 文件 | 内容 |
|------|------|
| `.deer-flow/users.db` | SQLite 用户数据库（密码哈希、角色） |
| `.env` 中的 `AUTH_JWT_SECRET` | JWT 签名密钥（未设置时自动生成临时密钥，重启后 session 失效） |

### 生产环境建议

```bash
# 生成持久化 JWT 密钥，避免重启后所有用户需重新登录
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 将输出添加到 .env：
# AUTH_JWT_SECRET=<生成的密钥>
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login/local` | POST | 邮箱密码登录（OAuth2 form） |
| `/api/v1/auth/register` | POST | 注册新用户（user 角色） |
| `/api/v1/auth/logout` | POST | 登出（清除 cookie） |
| `/api/v1/auth/me` | GET | 获取当前用户信息 |
| `/api/v1/auth/change-password` | POST | 修改密码 |
| `/api/v1/auth/setup-status` | GET | 检查 admin 是否存在 |

## 兼容性

- **标准模式**（`make dev`）：完全兼容，admin 自动创建
- **Gateway 模式**（`make dev-pro`）：完全兼容
- **Docker 部署**：完全兼容，`.deer-flow/users.db` 需持久化卷挂载
- **IM 渠道**（Feishu/Slack/Telegram）：通过 LangGraph SDK 通信，不经过认证层
- **DeerFlowClient**（嵌入式）：不经过 HTTP，不受认证影响

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| 启动后没看到密码 | admin 已存在（非首次启动） | 用 `reset_admin` 重置，或删 `users.db` |
| 登录后 POST 返回 403 | CSRF token 缺失 | 确认前端已更新 |
| 重启后需要重新登录 | `AUTH_JWT_SECRET` 未持久化 | 在 `.env` 中设置固定密钥 |
