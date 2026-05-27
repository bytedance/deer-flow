# Authentication Upgrade Guide

DeerFlow 内置了认证模块。本文档面向从无认证版本升级的用户。

完整设计见 [AUTH_DESIGN.md](AUTH_DESIGN.md)。

## 核心概念

认证模块采用**始终强制**策略：

- 首次启动时不会自动创建账号；首次访问 `/setup` 时由操作者创建第一个 admin 账号
- 认证从一开始就是强制的，无竞争窗口
- 已有 admin 后，服务启动时会把历史对话（升级前创建且缺少 `user_id` 的 thread）迁移到 admin 名下
- 新数据按用户隔离：thread、workspace/uploads/outputs、memory、自定义 agent 都归属当前用户

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

如果没有 admin 账号，控制台只会提示：

```
============================================================
  First boot detected — no admin account exists.
  Visit /setup to complete admin account creation.
============================================================
```

首次启动不会在日志里打印随机密码，也不会写入默认 admin。这样避免启动日志泄露凭据，也避免在操作者创建账号前出现可被猜测的默认身份。

### 3. 创建 admin

访问 `http://localhost:2026/setup`，填写邮箱和密码创建第一个 admin 账号。创建成功后会自动登录并进入 workspace。

如果这是从无认证版本升级，创建 admin 后重启一次服务，让启动迁移把缺少 `user_id` 的历史 thread 归属到 admin。

### 4. 登录

后续访问 `http://localhost:2026/login`，使用已创建的邮箱和密码登录。

### 5. 添加用户（可选）

其他用户通过 `/login` 页面注册，自动获得 **user** 角色。每个用户只能看到自己的对话、上传文件、输出文件、memory 和自定义 agent。

## 安全机制

| 机制 | 说明 |
|------|------|
| JWT HttpOnly Cookie | Token 不暴露给 JavaScript，防止 XSS 窃取 |
| CSRF Double Submit Cookie | 受保护的 POST/PUT/PATCH/DELETE 请求需携带 `X-CSRF-Token`；登录/注册/初始化/登出走 auth 端点 Origin 校验 |
| bcrypt 密码哈希 | 密码不以明文存储 |
| Thread owner filter | `threads_meta.user_id` 由服务端认证上下文写入，搜索、读取、更新、删除默认按当前用户过滤 |
| 文件系统隔离 | 线程数据写入 `{base_dir}/users/{user_id}/threads/{thread_id}/user-data/`，sandbox 内统一映射为 `/mnt/user-data/` |
| Memory / agent 隔离 | 用户 memory 和自定义 agent 写入 `{base_dir}/users/{user_id}/...`；旧共享 agent 只作为只读兼容回退 |
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

会把新的随机密码写入 `.deer-flow/admin_initial_credentials.txt`，文件权限为 `0600`。命令行只输出文件路径，不输出明文密码。

### 完全重置

删除统一 SQLite 数据库，重启后重新访问 `/setup` 创建新 admin：

```bash
rm -f backend/.deer-flow/data/deerflow.db
# 重启服务后访问 http://localhost:2026/setup
```

## 数据存储

| 文件 | 内容 |
|------|------|
| `.deer-flow/data/deerflow.db` | 统一 SQLite 数据库（users、threads_meta、runs、feedback 等应用数据） |
| `.deer-flow/users/{user_id}/threads/{thread_id}/user-data/` | 用户线程的 workspace、uploads、outputs |
| `.deer-flow/users/{user_id}/memory.json` | 用户级 memory |
| `.deer-flow/users/{user_id}/agents/{agent_name}/` | 用户自定义 agent 配置、SOUL 和 agent memory |
| `.deer-flow/admin_initial_credentials.txt` | `reset_admin` 生成的新凭据文件（0600，读完应删除） |
| `.env` 中的 `AUTH_JWT_SECRET` | JWT 签名密钥（未设置时自动生成并持久化到 `.deer-flow/.jwt_secret`，重启后 session 保持） |

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
| `/api/v1/auth/initialize` | POST | 首次初始化第一个 admin（仅无 admin 时可调用） |

## 兼容性

- **标准模式**（`make dev`）：完全兼容；无 admin 时访问 `/setup` 初始化
- **Gateway 模式**（`make dev-pro`）：完全兼容
- **Docker 部署**：完全兼容，`.deer-flow/data/deerflow.db` 需持久化卷挂载
- **IM 渠道**（Feishu/Slack/Telegram）：通过 Gateway 内部认证通信，使用 `default` 用户桶
- **DeerFlowClient**（嵌入式）：不经过 HTTP，不受认证影响

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| 启动后没看到密码 | 当前实现不在启动日志输出密码 | 首次安装访问 `/setup`；忘记密码用 `reset_admin` |
| `/login` 自动跳到 `/setup` | 系统还没有 admin | 在 `/setup` 创建第一个 admin |
| 登录后 POST 返回 403 | CSRF token 缺失 | 确认前端已更新 |
| 重启后需要重新登录 | `.jwt_secret` 文件被删除且 `.env` 未设置 `AUTH_JWT_SECRET` | 在 `.env` 中设置固定密钥 |
