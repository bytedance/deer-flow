# Auth 模块测试计划

## 测试矩阵

| 模式 | 启动命令 | Auth 层 | 端口 |
|------|---------|---------|------|
| 标准模式 | `make dev` | Gateway AuthMiddleware + LangGraph auth | 2026 (nginx) |
| Gateway 模式 | `make dev-pro` | Gateway AuthMiddleware（全量） | 2026 (nginx) |
| 直连 Gateway | `cd backend && make gateway` | Gateway AuthMiddleware | 8001 |
| 直连 LangGraph | `cd backend && make dev` | LangGraph auth | 2024 |

每种模式下都需执行以下测试。

---

## 一、环境准备

### 1.1 首次启动（干净数据库）

```bash
# 清除已有数据
rm -f backend/.deer-flow/users.db

# 选择模式启动
make dev          # 标准模式
# 或
make dev-pro      # Gateway 模式
```

**验证点：**
- [ ] 控制台输出 admin 邮箱和随机密码
- [ ] 密码格式为 `secrets.token_urlsafe(16)` 的 22 字符字符串
- [ ] 邮箱为 `admin@deerflow.dev`
- [ ] 提示 `Change it after login: Settings -> Account`

### 1.2 非首次启动

```bash
# 不清除数据库，直接启动
make dev
```

**验证点：**
- [ ] 控制台不输出密码
- [ ] 如果 admin 仍 `needs_setup=True`，控制台有 warning 提示

### 1.3 环境变量配置

| 变量 | 验证 |
|------|------|
| `AUTH_JWT_SECRET` 未设 | 启动时 warning，自动生成临时密钥 |
| `AUTH_JWT_SECRET` 已设 | 无 warning，重启后 session 保持 |

---

## 二、接口流程测试

> 以下用 `BASE=http://localhost:2026` 为例。标准模式和 Gateway 模式都用此地址。
> 直连测试替换为对应端口。
>
> **CSRF token 提取**：多处用到从 cookie jar 提取 CSRF token，统一使用：
> ```bash
> CSRF=$(python3 -c "
> import http.cookiejar
> cj = http.cookiejar.MozillaCookieJar('cookies.txt'); cj.load()
> print(next(c.value for c in cj if c.name == 'csrf_token'))
> ")
> ```
> 或简写（多数场景够用）：`CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')`

### 2.1 注册 + 登录 + 会话

#### TC-API-01: Setup 状态查询

```bash
curl -s $BASE/api/v1/auth/setup-status | jq .
```

**预期：** 返回 `{"needs_setup": false}`（admin 在启动时已自动创建，`count_users() > 0`）。仅在启动完成前的极短窗口内可能返回 `true`。

#### TC-API-02: Admin 首次登录

```bash
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@deerflow.dev&password=<控制台密码>" \
  -c cookies.txt | jq .
```

**预期：**
- 状态码 200
- Body: `{"expires_in": 604800, "needs_setup": true}`
- `cookies.txt` 包含 `access_token`（HttpOnly）和 `csrf_token`（非 HttpOnly）

#### TC-API-03: 获取当前用户

```bash
curl -s $BASE/api/v1/auth/me -b cookies.txt | jq .
```

**预期：** `{"id": "...", "email": "admin@deerflow.dev", "system_role": "admin", "needs_setup": true}`

#### TC-API-04: Setup 流程（改邮箱 + 改密码）

```bash
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"current_password":"<控制台密码>","new_password":"NewPass123!","new_email":"admin@example.com"}' | jq .
```

**预期：**
- 状态码 200
- `{"message": "Password changed successfully"}`
- 再调 `/auth/me` 邮箱变为 `admin@example.com`，`needs_setup` 变为 `false`

#### TC-API-05: 普通用户注册

```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user1@example.com","password":"UserPass1!"}' \
  -c user_cookies.txt | jq .
```

**预期：** 状态码 201，`system_role` 为 `"user"`，自动登录（cookie 已设）

#### TC-API-06: 登出

```bash
curl -s -X POST $BASE/api/v1/auth/logout -b cookies.txt | jq .
```

**预期：** `{"message": "Successfully logged out"}`，后续用 cookies.txt 访问 `/auth/me` 返回 401

### 2.2 多租户隔离

#### TC-API-07: 用户 A 创建 Thread

```bash
# 以 user1 登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=user1@example.com&password=UserPass1!" \
  -c user1.txt

CSRF1=$(grep csrf_token user1.txt | awk '{print $NF}')

# 创建 thread
curl -s -X POST $BASE/api/threads \
  -b user1.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF1" \
  -d '{"metadata":{}}' | jq .thread_id
# 记录 THREAD_ID
```

#### TC-API-08: 用户 B 无法访问用户 A 的 Thread

```bash
# 注册并登录 user2
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user2@example.com","password":"UserPass2!"}' \
  -c user2.txt

# 尝试访问 user1 的 thread
curl -s $BASE/api/threads/$THREAD_ID -b user2.txt
```

**预期：** 状态码 404（不是 403，避免泄露 thread 存在性）

#### TC-API-09: 用户 B 搜索 Thread 看不到用户 A 的

```bash
CSRF2=$(grep csrf_token user2.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/threads/search \
  -b user2.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF2" \
  -d '{}' | jq length
```

**预期：** 返回 0 或仅包含 user2 自己的 thread

### 2.3 标准模式 LangGraph Server 隔离

> 仅在标准模式下测试。Gateway 模式不跑 LangGraph Server。

#### TC-API-10: LangGraph 端点需要 cookie

```bash
# 不带 cookie 访问 LangGraph 接口
curl -s -w "%{http_code}" $BASE/api/langgraph/threads
```

**预期：** 401

#### TC-API-11: LangGraph 带 cookie 可访问

```bash
curl -s $BASE/api/langgraph/threads -b user1.txt | jq length
```

**预期：** 200，返回 user1 的 thread 列表

#### TC-API-12: LangGraph 隔离 — 用户只看到自己的

```bash
# user2 查 LangGraph threads
curl -s $BASE/api/langgraph/threads -b user2.txt | jq length
```

**预期：** 不包含 user1 的 thread

### 2.4 Token 失效

#### TC-API-13: 改密码后旧 token 立即失效

```bash
# 保存当前 cookie
cp user1.txt user1_old.txt

# 改密码
CSRF1=$(grep csrf_token user1.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b user1.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF1" \
  -d '{"current_password":"UserPass1!","new_password":"NewUserPass1!"}' \
  -c user1.txt

# 用旧 cookie 访问
curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b user1_old.txt
```

**预期：** 401（token_version 不匹配）

#### TC-API-14: 改密码后新 cookie 可用

```bash
curl -s $BASE/api/v1/auth/me -b user1.txt | jq .email
```

**预期：** 200，返回用户信息

### 2.5 错误响应格式

#### TC-API-15: 结构化错误响应

```bash
# 错误密码登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=wrong" | jq .detail
```

**预期：**
```json
{"code": "invalid_credentials", "message": "Incorrect email or password"}
```

#### TC-API-16: 重复邮箱注册

```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user1@example.com","password":"AnyPass123"}' -w "\n%{http_code}"
```

**预期：** 400，`{"code": "email_already_exists", ...}`

---

## 三、攻击测试

### 3.1 暴力破解防护

#### TC-ATK-01: IP 限速

```bash
# 连续 6 次错误密码
for i in $(seq 1 6); do
  echo "Attempt $i:"
  curl -s -X POST $BASE/api/v1/auth/login/local \
    -d "username=admin@example.com&password=wrong$i" -w " HTTP %{http_code}\n"
done
```

**预期：** 前 5 次返回 401，第 6 次返回 429 `"Too many login attempts. Try again later."`

#### TC-ATK-02: 限速后正确密码也被拒

```bash
# 紧接上一步
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -w " HTTP %{http_code}\n"
```

**预期：** 429（锁定 5 分钟）

#### TC-ATK-03: 成功登录清除限速

```bash
# 等待锁定过期后（或重启服务），用正确密码登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -w " HTTP %{http_code}\n"
```

**预期：** 200，计数器重置

### 3.2 CSRF 防护

#### TC-ATK-04: 无 CSRF token 的 POST 请求

```bash
curl -s -X POST $BASE/api/threads \
  -b user1.txt \
  -H "Content-Type: application/json" \
  -d '{"metadata":{}}' -w "\nHTTP %{http_code}"
```

**预期：** 403 `"CSRF token missing"`

#### TC-ATK-05: 错误 CSRF token

```bash
curl -s -X POST $BASE/api/threads \
  -b user1.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: fake-token" \
  -d '{"metadata":{}}' -w "\nHTTP %{http_code}"
```

**预期：** 403 `"CSRF token mismatch"`

### 3.3 Cookie 安全

> HTTP 与 HTTPS 行为差异通过 `X-Forwarded-Proto: https` 模拟。
> **注意：** 经 nginx 代理时，nginx 的 `proxy_set_header X-Forwarded-Proto $scheme` 会覆盖
> 客户端发的值（`$scheme` = nginx 监听端口的 scheme），因此 HTTPS 模拟必须**直连 Gateway（端口 8001）**。
> 每个 case 需在 **login** 和 **register** 两个端点各验证一次。

#### TC-ATK-06: HTTP 模式 Cookie 属性

```bash
# 登录
curl -s -D - -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" 2>/dev/null | grep -i set-cookie
```

**预期：**
- `access_token`: `HttpOnly; Path=/; SameSite=lax`，无 `Secure`，无 `Max-Age`
- `csrf_token`: `Path=/; SameSite=strict`，无 `HttpOnly`（JS 需要读取），无 `Secure`

```bash
# 注册
curl -s -D - -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"cookie-http@example.com","password":"CookieTest1!"}' 2>/dev/null | grep -i set-cookie
```

**预期：** 同上

#### TC-ATK-07: HTTPS 模式 Cookie 属性

> **必须直连 Gateway**（`GW=http://localhost:8001`），经 nginx 会被 `$scheme` 覆盖。

```bash
GW=http://localhost:8001

# 登录（模拟 HTTPS）
curl -s -D - -X POST $GW/api/v1/auth/login/local \
  -H "X-Forwarded-Proto: https" \
  -d "username=admin@example.com&password=正确密码" 2>/dev/null | grep -i set-cookie
```

**预期：**
- `access_token`: `HttpOnly; Secure; Path=/; SameSite=lax; Max-Age=604800`
- `csrf_token`: `Secure; Path=/; SameSite=strict`，无 `HttpOnly`

```bash
# 注册（模拟 HTTPS）
curl -s -D - -X POST $GW/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-Proto: https" \
  -d '{"email":"cookie-https@example.com","password":"CookieTest1!"}' 2>/dev/null | grep -i set-cookie
```

**预期：** 同上

#### TC-ATK-07a: HTTP/HTTPS 差异对比

> 直连 Gateway 执行，避免 nginx 覆盖 `X-Forwarded-Proto`。

```bash
GW=http://localhost:8001

for proto in "" "https"; do
  HEADER=""
  LABEL="HTTP"
  if [ -n "$proto" ]; then
    HEADER="-H X-Forwarded-Proto:$proto"
    LABEL="HTTPS"
  fi
  echo "=== $LABEL ==="
  EMAIL="compare-${LABEL,,}-$(date +%s)@example.com"
  curl -s -D - -X POST $GW/api/v1/auth/register \
    -H "Content-Type: application/json" $HEADER \
    -d "{\"email\":\"$EMAIL\",\"password\":\"Compare1!\"}" 2>/dev/null | grep -i set-cookie | while read line; do
    if echo "$line" | grep -q "access_token="; then
      echo "  access_token:"
      echo "    HttpOnly: $(echo "$line" | grep -qi httponly && echo YES || echo NO)"
      echo "    Secure:   $(echo "$line" | grep -qi "secure" && echo "$line" | grep -v samesite | grep -qi secure && echo YES || echo NO)"
      echo "    Max-Age:  $(echo "$line" | grep -oi "max-age=[0-9]*" || echo NONE)"
      echo "    SameSite: $(echo "$line" | grep -oi "samesite=[a-z]*")"
    fi
    if echo "$line" | grep -q "csrf_token="; then
      echo "  csrf_token:"
      echo "    HttpOnly: $(echo "$line" | grep -qi httponly && echo YES || echo NO)"
      echo "    Secure:   $(echo "$line" | grep -qi "secure" && echo "$line" | grep -v samesite | grep -qi secure && echo YES || echo NO)"
      echo "    SameSite: $(echo "$line" | grep -oi "samesite=[a-z]*")"
    fi
  done
done
```

**预期对比表：**

| 属性 | HTTP access_token | HTTPS access_token | HTTP csrf_token | HTTPS csrf_token |
|------|------|------|------|------|
| HttpOnly | Yes | Yes | No | No |
| Secure | No | **Yes** | No | **Yes** |
| SameSite | Lax | Lax | Strict | Strict |
| Max-Age | 无（session cookie） | **604800**（7天） | 无 | 无 |

### 3.4 越权访问

#### TC-ATK-08: 无 cookie 访问受保护接口

```bash
for path in /api/models /api/mcp/config /api/memory /api/skills \
            /api/agents /api/channels; do
  echo "$path: $(curl -s -w '%{http_code}' -o /dev/null $BASE$path)"
done
```

**预期：** 全部 401

#### TC-ATK-09: 伪造 JWT

```bash
# 用不同 secret 签名的 token
FAKE_TOKEN=$(python3 -c "
import jwt
print(jwt.encode({'sub':'admin-id','ver':0,'exp':9999999999}, 'wrong-secret', algorithm='HS256'))
")

curl -s -w "%{http_code}" $BASE/api/v1/auth/me \
  --cookie "access_token=$FAKE_TOKEN"
```

**预期：** 401（签名验证失败）

#### TC-ATK-10: 过期 JWT

```bash
# 不依赖环境变量，直接用一个已过期的、随机 secret 签名的 token
# 无论 secret 是否匹配，过期 token 都会被拒绝
EXPIRED_TOKEN=$(python3 -c "
import jwt, time
print(jwt.encode({'sub':'x','ver':0,'exp':int(time.time())-100}, 'any-secret-32chars-placeholder!!', algorithm='HS256'))
")

curl -s -w "%{http_code}" -o /dev/null $BASE/api/v1/auth/me \
  --cookie "access_token=$EXPIRED_TOKEN"
```

**预期：** 401（过期 or 签名不匹配，均被拒绝）

### 3.5 密码安全

#### TC-ATK-11: 密码长度不足

```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"short@example.com","password":"1234567"}' -w "\nHTTP %{http_code}"
```

**预期：** 422（Pydantic validation: min_length=8）

#### TC-ATK-12: 密码不以明文存储

```bash
# 检查数据库
sqlite3 backend/.deer-flow/users.db "SELECT email, password_hash FROM users LIMIT 3;"
```

**预期：** `password_hash` 以 `$2b$` 开头（bcrypt 格式）

---

## 四、UI 操作测试

> 浏览器中操作，验证前后端联动。

### 4.1 首次登录流程

#### TC-UI-01: 访问首页跳转登录

1. 打开 `http://localhost:2026/workspace`
2. **预期：** 自动跳转到 `/login`

#### TC-UI-02: Login 页面

1. 输入 admin 邮箱和控制台密码
2. 点击 Login
3. **预期：** 跳转到 `/setup`（因为 `needs_setup=true`）

#### TC-UI-03: Setup 页面

1. 输入新邮箱、控制台密码（current）、新密码、确认密码
2. 点击 Complete Setup
3. **预期：** 跳转到 `/workspace`
4. 刷新页面不跳回 `/setup`

#### TC-UI-04: Setup 密码不匹配

1. 新密码和确认密码不一致
2. 点击 Complete Setup
3. **预期：** 显示 "Passwords do not match" 错误

### 4.2 日常使用

#### TC-UI-05: 创建对话

1. 在 workspace 发送一条消息
2. **预期：** 左侧栏出现新 thread

#### TC-UI-06: 对话持久化

1. 创建对话后刷新页面
2. **预期：** 对话列表和内容仍然存在

#### TC-UI-07: 登出

1. 点击头像 → Logout
2. **预期：** 跳转到首页 `/`
3. 直接访问 `/workspace` → 跳转到 `/login`

### 4.3 多用户隔离

#### TC-UI-08: 用户 A 看不到用户 B 的对话

1. 用户 A 在浏览器 1 登录，创建一个对话并发消息
2. 用户 B 在浏览器 2（或隐身窗口）注册并登录
3. **预期：** 用户 B 的 workspace 左侧栏为空，看不到用户 A 的对话

#### TC-UI-09: 直接 URL 访问他人 Thread

1. 复制用户 A 的 thread URL
2. 在用户 B 的浏览器中访问
3. **预期：** 404 或空白页，不显示对话内容

### 4.4 Session 管理

#### TC-UI-10: Tab 切换 Session 检查

1. 登录 workspace
2. 切换到其他 tab 等待 60+ 秒
3. 切回 workspace tab
4. **预期：** 静默检查 session，页面正常（控制台无 401 刷屏）

#### TC-UI-11: Session 过期后 Tab 切回

1. 登录 workspace
2. 在另一个 tab 改密码（使当前 session 失效）
3. 切回 workspace tab
4. **预期：** 自动跳转到 `/login`

#### TC-UI-12: 改密码后 Settings 页面

1. 进入 Settings → Account
2. 修改密码
3. **预期：** 成功提示，页面不需要重新登录（cookie 已自动更新）

### 4.5 注册流程

#### TC-UI-13: 从登录页跳转注册

1. 在 `/login` 页面点击注册链接
2. 输入邮箱和密码
3. **预期：** 注册成功后自动跳转 `/workspace`

#### TC-UI-14: 重复邮箱注册

1. 用已注册的邮箱尝试注册
2. **预期：** 显示 "Email already registered" 错误

### 4.6 密码重置（CLI）

#### TC-UI-15: reset_admin 后重新登录

1. 执行 `cd backend && python -m app.gateway.auth.reset_admin`
2. 使用新密码登录
3. **预期：** 跳转到 `/setup` 页面（`needs_setup` 被重置为 true）
4. 旧 session 已失效

---

## 五、升级测试

> 模拟从无 auth 版本（main 分支）升级到 auth 版本（feat/rfc-001-auth-module）。

### 5.1 准备旧版数据

```bash
# 1. 切到 main 分支，启动服务
git stash && git checkout main
make dev

# 2. 创建一些对话数据（无 auth，直接访问）
curl -s -X POST http://localhost:2026/api/langgraph/threads \
  -H "Content-Type: application/json" \
  -d '{"metadata":{"title":"old-thread-1"}}' | jq .thread_id

curl -s -X POST http://localhost:2026/api/langgraph/threads \
  -H "Content-Type: application/json" \
  -d '{"metadata":{"title":"old-thread-2"}}' | jq .thread_id

# 3. 记录 thread 数量
curl -s http://localhost:2026/api/langgraph/threads | jq length
# 预期: 2+

# 4. 停止服务
make stop
```

### 5.2 升级并启动

```bash
# 5. 切到 auth 分支
git checkout feat/rfc-001-auth-module && git stash pop
make install
make dev
```

#### TC-UPG-01: 首次启动创建 admin

**预期：**
- [ ] 控制台输出 admin 邮箱（`admin@deerflow.dev`）和随机密码
- [ ] 无报错，正常启动

#### TC-UPG-02: 旧 Thread 迁移到 admin

```bash
# 登录 admin
curl -s -X POST http://localhost:2026/api/v1/auth/login/local \
  -d "username=admin@deerflow.dev&password=<控制台密码>" \
  -c cookies.txt

# 查看 thread 列表
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')
curl -s -X POST http://localhost:2026/api/threads/search \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{}' | jq length
```

**预期：**
- [ ] 返回的 thread 数量 ≥ 旧版创建的数量
- [ ] 控制台日志有 `Migrated N orphaned thread(s) to admin`
- [ ] 每个 thread 的 `metadata.owner_id` 都已被设为 admin 的 ID

#### TC-UPG-03: 旧 Thread 内容完整

```bash
# 检查某个旧 thread 的内容
curl -s http://localhost:2026/api/threads/<old-thread-id> \
  -b cookies.txt | jq .metadata
```

**预期：**
- [ ] `metadata.title` 保留原值（如 `old-thread-1`）
- [ ] `metadata.owner_id` 已填充

#### TC-UPG-04: 新用户看不到旧 Thread

```bash
# 注册新用户
curl -s -X POST http://localhost:2026/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"newuser@example.com","password":"NewPass123!"}' \
  -c newuser.txt

CSRF2=$(grep csrf_token newuser.txt | awk '{print $NF}')
curl -s -X POST http://localhost:2026/api/threads/search \
  -b newuser.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF2" \
  -d '{}' | jq length
```

**预期：** 返回 0（旧 thread 属于 admin，新用户不可见）

### 5.3 数据库 Schema 兼容

#### TC-UPG-05: 无 users.db 时自动创建

```bash
ls -la backend/.deer-flow/users.db
```

**预期：** 文件存在，`sqlite3` 可查到 `users` 表含 `needs_setup`、`token_version` 列

#### TC-UPG-06: users.db WAL 模式

```bash
sqlite3 backend/.deer-flow/users.db "PRAGMA journal_mode;"
```

**预期：** 返回 `wal`

### 5.4 配置兼容

#### TC-UPG-07: 无 AUTH_JWT_SECRET 的旧 .env 文件

```bash
# 确认 .env 中没有 AUTH_JWT_SECRET
grep AUTH_JWT_SECRET backend/.env || echo "NOT SET"
```

**预期：**
- [ ] 启动时 warning：`AUTH_JWT_SECRET is not set — using auto-generated ephemeral secret`
- [ ] 服务正常可用
- [ ] 重启后旧 session 失效（临时密钥变了）

#### TC-UPG-08: 旧 config.yaml 无 auth 相关配置

```bash
# 检查 config.yaml 没有 auth 段
grep -c "auth" config.yaml || echo "0"
```

**预期：** auth 模块不依赖 config.yaml（配置走环境变量），旧 config.yaml 不影响启动

### 5.5 前端兼容

#### TC-UPG-09: 旧前端缓存

1. 用旧版前端的浏览器缓存访问升级后的服务
2. **预期：** 被 AuthMiddleware 拦截返回 401（旧前端无 cookie），页面自然刷新后加载新前端

#### TC-UPG-10: 书签 URL

1. 用升级前保存的 workspace URL（如 `localhost:2026/workspace/chats/xxx`）直接访问
2. **预期：** 跳转到 `/login`，登录后跳回原 URL（`?next=` 参数）

### 5.6 降级回滚

#### TC-UPG-11: 回退到 main 分支

```bash
make stop
git checkout main
make dev
```

**预期：**
- [ ] 服务正常启动（忽略 `users.db`，无 auth 相关代码不报错）
- [ ] 旧对话数据仍然可访问
- [ ] `users.db` 文件残留但不影响运行

#### TC-UPG-12: 再次升级到 auth 分支

```bash
make stop
git checkout feat/rfc-001-auth-module
make dev
```

**预期：**
- [ ] 识别已有 `users.db`，不重新创建 admin
- [ ] 旧的 admin 账号仍可登录（如果回退期间未删 `users.db`）

### 5.7 休眠 Admin（初始密码未使用/未更改）

> 首次启动生成 admin + 随机密码，但运维未登录、未改密码。
> 密码只在首次启动的控制台闪过一次，后续启动不再显示。

#### TC-UPG-13: 重启后自动重置密码并打印

```bash
# 首次启动，记录密码
rm -f backend/.deer-flow/users.db
make dev
# 控制台输出密码 P0，不登录
make stop

# 隔了几天，再次启动
make dev
# 控制台输出新密码 P1
```

**预期：**
- [ ] 控制台输出 `Admin account setup incomplete — password reset`
- [ ] 输出新密码 P1（P0 已失效）
- [ ] 用 P1 可以登录，P0 不可以
- [ ] 登录后 `needs_setup=true`，跳转 `/setup`
- [ ] `token_version` 递增（旧 session 如有也失效）

#### TC-UPG-14: 密码丢失 — 无需 CLI，重启即可

```bash
# 忘记了控制台密码 → 直接重启服务
make stop && make dev
# 控制台自动输出新密码
```

**预期：**
- [ ] 无需 `reset_admin`，重启服务即可拿到新密码
- [ ] `reset_admin` CLI 仍然可用作手动备选方案

#### TC-UPG-15: 休眠 admin 期间普通用户注册

```bash
# admin 存在但从未登录，普通用户先注册
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"earlybird@example.com","password":"EarlyPass1!"}' \
  -c early.txt -w "\nHTTP %{http_code}"
```

**预期：**
- [ ] 注册成功（201），角色为 `user`
- [ ] 无法提权为 admin
- [ ] 普通用户的数据与 admin 隔离

#### TC-UPG-16: 休眠 admin 不影响后续操作

```bash
# 普通用户正常创建 thread、发消息
CSRF=$(grep csrf_token early.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/threads \
  -b early.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"metadata":{}}' | jq .thread_id
```

**预期：** 正常创建，不受休眠 admin 影响

#### TC-UPG-17: 休眠 admin 最终完成 Setup

```bash
# 运维终于登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@deerflow.dev&password=<P0或P1>" \
  -c admin.txt | jq .needs_setup
# 预期: true

# 完成 setup
CSRF=$(grep csrf_token admin.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b admin.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"current_password":"<密码>","new_password":"AdminFinal1!","new_email":"admin@real.com"}' \
  -c admin.txt

# 验证
curl -s $BASE/api/v1/auth/me -b admin.txt | jq '{email, needs_setup}'
```

**预期：**
- [ ] `email` 变为 `admin@real.com`
- [ ] `needs_setup` 变为 `false`
- [ ] 后续重启控制台不再有 warning

#### TC-UPG-18: 长期未用后 JWT 密钥轮换

```bash
# 场景：admin 未登录期间，运维更换了 AUTH_JWT_SECRET
# 1. 首次启动用自动生成的临时密钥
# 2. 某天运维在 .env 设置了固定密钥
echo "AUTH_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
make stop && make dev
```

**预期：**
- [ ] 服务正常启动
- [ ] 旧密码仍可登录（密码存在 DB，与 JWT 密钥无关）
- [ ] 旧的 JWT token 失效（密钥变了签名不匹配）— 但因为从未登录过也没有旧 token

---

## 六、可重入测试

> 验证 auth 模块在重复操作、并发、中断恢复等场景下行为正确，无竞态条件。

### 6.1 启动可重入

#### TC-REENT-01: 连续重启不重复创建 admin

```bash
# 连续启动 3 次（daemon 模式，避免前台阻塞）
for i in 1 2 3; do
  make dev-daemon && sleep 10 && make stop
done

# 检查 admin 数量
sqlite3 backend/.deer-flow/users.db \
  "SELECT COUNT(*) FROM users WHERE system_role='admin';"
```

**预期：** 始终为 1。不会因重启创建多个 admin。

#### TC-REENT-02: 多进程同时启动

```bash
# 模拟两个 gateway 进程同时启动（竞争 admin 创建）
cd backend
PYTHONPATH=. uv run python -c "
import asyncio
from app.gateway.app import create_app, _ensure_admin_user

async def boot():
    app = create_app()
    # 模拟两个并发 ensure_admin
    await asyncio.gather(
        _ensure_admin_user(app),
        _ensure_admin_user(app),
    )

asyncio.run(boot())
" 2>&1 | grep -i "admin\|error\|duplicate"
```

**预期：**
- [ ] 不报错（SQLite UNIQUE 约束捕获竞争，第二个静默跳过）
- [ ] 最终只有 1 个 admin

#### TC-REENT-03: Thread 迁移幂等

```bash
# 连续调用 _migrate_orphaned_threads 两次
# 第二次应无 thread 需要迁移（已有 user_id）
```

**预期：** 第二次 `migrated = 0`，无副作用

### 6.2 登录可重入

#### TC-REENT-04: 重复登录获取新 cookie

```bash
# 同一用户连续登录 3 次
for i in 1 2 3; do
  curl -s -X POST $BASE/api/v1/auth/login/local \
    -d "username=admin@example.com&password=正确密码" \
    -c "cookies_$i.txt" -o /dev/null
done

# 三个 cookie 都有效
for i in 1 2 3; do
  echo "Cookie $i: $(curl -s -w '%{http_code}' -o /dev/null $BASE/api/v1/auth/me -b cookies_$i.txt)"
done
```

**预期：** 三个 cookie 都返回 200（未改密码，token_version 相同，多 session 共存）

#### TC-REENT-05: 登录-登出-登录

```bash
# 登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" \
  -c cookies.txt -o /dev/null

# 登出
curl -s -X POST $BASE/api/v1/auth/logout -b cookies.txt -o /dev/null

# 再次登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" \
  -c cookies.txt

curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b cookies.txt
```

**预期：** 200。登出→再登录流程无状态残留。

### 6.3 改密码可重入

#### TC-REENT-06: 连续两次改密码

```bash
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

# 第一次改密码
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"current_password":"Pass1","new_password":"Pass2"}' \
  -c cookies.txt

# 用新 cookie 的 CSRF 再改一次
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"current_password":"Pass2","new_password":"Pass3"}' \
  -c cookies.txt

curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b cookies.txt
```

**预期：**
- [ ] 两次改密码都成功
- [ ] 最终密码为 Pass3
- [ ] `token_version` 递增两次（+2）
- [ ] 最新 cookie 有效

#### TC-REENT-07: 改密码后旧 cookie 全部失效

```bash
# 保存三个时间点的 cookie
# t1: 初始登录 → cookies_t1.txt
# t2: 第一次改密码后 → cookies_t2.txt
# t3: 第二次改密码后 → cookies_t3.txt

# 用 t1 和 t2 的 cookie 访问
curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b cookies_t1.txt  # 预期 401
curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b cookies_t2.txt  # 预期 401
curl -s -w "%{http_code}" $BASE/api/v1/auth/me -b cookies_t3.txt  # 预期 200
```

**预期：** 只有最新的 cookie 有效，历史 cookie 因 token_version 不匹配全部 401

### 6.4 注册可重入

#### TC-REENT-08: 同一邮箱并发注册

```bash
# 并发发送两个相同邮箱的注册请求
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"race@example.com","password":"RacePass1!"}' &
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"race@example.com","password":"RacePass1!"}' &
wait

# 检查用户数
sqlite3 backend/.deer-flow/users.db \
  "SELECT COUNT(*) FROM users WHERE email='race@example.com';"
```

**预期：**
- [ ] 一个成功（201），一个失败（400 `email_already_exists`）
- [ ] 数据库中只有 1 条记录（UNIQUE 约束保护）

### 6.5 Rate Limiter 可重入

#### TC-REENT-09: 限速过期后重新计数

```bash
# 触发锁定（5 次错误）
for i in $(seq 1 5); do
  curl -s -o /dev/null -X POST $BASE/api/v1/auth/login/local \
    -d "username=admin@example.com&password=wrong"
done

# 确认被锁定
curl -s -w "%{http_code}" -o /dev/null -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=wrong"
# 预期: 429

# 等待锁定过期（5 分钟）或重启服务清除内存计数器
make stop && make dev

# 重新尝试 — 计数器应已重置
curl -s -w "%{http_code}" -o /dev/null -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=wrong"
# 预期: 401（不是 429）
```

**预期：** 锁定过期后恢复正常限速（从 0 开始计数），而非累积

#### TC-REENT-10: 成功登录重置计数后再次失败

```bash
# 3 次失败
for i in $(seq 1 3); do
  curl -s -o /dev/null -X POST $BASE/api/v1/auth/login/local \
    -d "username=admin@example.com&password=wrong"
done

# 1 次成功（重置计数）
curl -s -o /dev/null -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码"

# 再 4 次失败（从 0 重新计数，未达阈值 5）
for i in $(seq 1 4); do
  curl -s -w "attempt $i: %{http_code}\n" -o /dev/null -X POST $BASE/api/v1/auth/login/local \
    -d "username=admin@example.com&password=wrong"
done
```

**预期：** 4 次全部返回 401（未锁定），因为成功登录已重置计数器

### 6.6 CSRF Token 可重入

#### TC-REENT-11: 登录后多次 POST 使用同一 CSRF token

```bash
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

# 同一 CSRF token 多次使用
for i in 1 2 3; do
  echo "Request $i: $(curl -s -w '%{http_code}' -o /dev/null \
    -X POST $BASE/api/threads \
    -b cookies.txt \
    -H 'Content-Type: application/json' \
    -H "X-CSRF-Token: $CSRF" \
    -d '{"metadata":{}}')"
done
```

**预期：** 三次都成功（CSRF token 是 Double Submit Cookie，不是一次性 nonce）

### 6.7 Thread 操作可重入

#### TC-REENT-12: 重复删除同一 Thread

```bash
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

# 创建 thread
TID=$(curl -s -X POST $BASE/api/threads \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"metadata":{}}' | jq -r .thread_id)

# 第一次删除
curl -s -w "%{http_code}" -X DELETE "$BASE/api/threads/$TID" \
  -b cookies.txt -H "X-CSRF-Token: $CSRF"
# 预期: 200

# 第二次删除（幂等）
curl -s -w "%{http_code}" -X DELETE "$BASE/api/threads/$TID" \
  -b cookies.txt -H "X-CSRF-Token: $CSRF"
```

**预期：** 第二次返回 200 或 404，不报 500

### 6.8 reset_admin 可重入

#### TC-REENT-13: 连续两次 reset_admin

```bash
cd backend
python -m app.gateway.auth.reset_admin
# 记录密码 P1

python -m app.gateway.auth.reset_admin
# 记录密码 P2
```

**预期：**
- [ ] P1 ≠ P2（每次生成新随机密码）
- [ ] P1 不可用，只有 P2 有效
- [ ] `token_version` 递增了 2
- [ ] `needs_setup` 为 True

### 6.9 Setup 流程可重入

#### TC-REENT-14: 完成 Setup 后再访问 /setup 页面

1. 完成 admin setup（改邮箱 + 改密码）
2. 直接访问 `/setup`
3. **预期：** 应跳转到 `/workspace`（`needs_setup` 已为 false，SSR guard 不会返回 `needs_setup` tag）

#### TC-REENT-15: Setup 中途刷新页面

1. 在 `/setup` 页面填写一半
2. 刷新页面
3. **预期：** 仍在 `/setup`（`needs_setup` 仍为 true），表单清空但不报错

---

## 七、模式差异测试

> 以下用 `GW=http://localhost:8001` 表示直连 Gateway，`BASE=http://localhost:2026` 表示经 nginx。
> Gateway 模式启动命令：`make dev-pro`（或 `./scripts/serve.sh --dev --gateway`）。

### 7.1 标准模式独有

> 启动命令：`make dev`（或 `./scripts/serve.sh --dev`）

#### TC-MODE-01: LangGraph Server 独立运行，需 cookie

```bash
# 无 cookie 访问 LangGraph
curl -s -w "%{http_code}" -o /dev/null $BASE/api/langgraph/threads/search
# 预期: 403（LangGraph auth handler 拒绝）
```

#### TC-MODE-02: LangGraph auth 的 token_version 检查

```bash
# 登录拿 cookie
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -c cookies.txt

# 改密码（bumps token_version）
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/v1/auth/change-password \
  -b cookies.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"current_password":"正确密码","new_password":"NewPass1!"}' -c new_cookies.txt

# 用旧 cookie 访问 LangGraph
curl -s -w "%{http_code}" $BASE/api/langgraph/threads/search -b cookies.txt
# 预期: 403（token_version 不匹配）

# 用新 cookie 访问
CSRF2=$(grep csrf_token new_cookies.txt | awk '{print $NF}')
curl -s -w "%{http_code}" -X POST $BASE/api/langgraph/threads/search \
  -b new_cookies.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF2" -d '{}'
# 预期: 200
```

#### TC-MODE-03: LangGraph auth 的 owner filter 隔离

```bash
# user1 创建 thread
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=user1@example.com&password=UserPass1!" -c u1.txt
CSRF1=$(grep csrf_token u1.txt | awk '{print $NF}')
TID=$(curl -s -X POST $BASE/api/langgraph/threads \
  -b u1.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF1" \
  -d '{"metadata":{}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])")

# user2 搜索 — 应看不到 user1 的 thread
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=user2@example.com&password=UserPass2!" -c u2.txt
CSRF2=$(grep csrf_token u2.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/langgraph/threads/search \
  -b u2.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF2" -d '{}' | python3 -c "
import sys,json
threads = json.load(sys.stdin)
ids = [t['thread_id'] for t in threads]
assert '$TID' not in ids, 'LEAK: user2 can see user1 thread'
print('OK: user2 sees', len(threads), 'threads, none belong to user1')
"
```

### 7.2 Gateway 模式独有

> 启动命令：`make dev-pro`（或 `./scripts/serve.sh --dev --gateway`）
> 无 LangGraph Server 进程，agent runtime 嵌入 Gateway。

#### TC-MODE-04: 所有请求经 AuthMiddleware

```bash
# 确认 LangGraph Server 未运行
curl -s -w "%{http_code}" -o /dev/null http://localhost:2024/ok
# 预期: 000（连接被拒）

# Gateway API 受保护
curl -s -w "%{http_code}" -o /dev/null $BASE/api/models
# 预期: 401

# LangGraph 兼容路由（rewrite 到 Gateway）也受保护
curl -s -w "%{http_code}" -o /dev/null -X POST $BASE/api/langgraph/threads/search \
  -H "Content-Type: application/json" -d '{}'
# 预期: 401
```

#### TC-MODE-05: Gateway 模式下完整 auth 流程

```bash
# 登录
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -c cookies.txt

CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

# 创建 thread（走 Gateway 内嵌 runtime）
curl -s -X POST $BASE/api/langgraph/threads \
  -b cookies.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"metadata":{}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])"
# 预期: 返回 thread_id

# CSRF 保护（Gateway 模式下 CSRFMiddleware 直接覆盖所有路由）
curl -s -w "%{http_code}" -o /dev/null -X POST $BASE/api/langgraph/threads \
  -b cookies.txt -H "Content-Type: application/json" -d '{"metadata":{}}'
# 预期: 403（CSRF token missing）
```

### 7.3 直连 Gateway（无 nginx）

> 启动命令：`cd backend && make gateway`（端口 8001）
> 不经过 nginx，直接测试 Gateway 的 auth 层。

#### TC-GW-01: AuthMiddleware 保护所有非 public 路由

```bash
GW=http://localhost:8001

for path in /api/models /api/mcp/config /api/memory /api/skills \
            /api/v1/auth/me /api/v1/auth/change-password; do
  echo "$path: $(curl -s -w '%{http_code}' -o /dev/null $GW$path)"
done
# 预期: 全部 401
```

#### TC-GW-02: Public 路由不需要 cookie

```bash
GW=http://localhost:8001

for path in /health /api/v1/auth/setup-status /api/v1/auth/login/local /api/v1/auth/register; do
  echo "$path: $(curl -s -w '%{http_code}' -o /dev/null $GW$path)"
done
# 预期: 200 或 405/422（方法不对但不是 401）
```

#### TC-GW-03: 直连 Gateway 注册 + 登录 + CSRF 完整流程

```bash
GW=http://localhost:8001

# 注册
curl -s -X POST $GW/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"gwtest@example.com","password":"GwTest123!"}' \
  -c gw_cookies.txt -w "\nHTTP %{http_code}"
# 预期: 201

# 登录
curl -s -X POST $GW/api/v1/auth/login/local \
  -d "username=gwtest@example.com&password=GwTest123!" \
  -c gw_cookies.txt -w "\nHTTP %{http_code}"
# 预期: 200

# GET（不需要 CSRF）
curl -s -w "%{http_code}" $GW/api/models -b gw_cookies.txt
# 预期: 200

# POST 无 CSRF
curl -s -w "%{http_code}" -o /dev/null -X POST $GW/api/memory/reload -b gw_cookies.txt
# 预期: 403（CSRF token missing）

# POST 有 CSRF
CSRF=$(grep csrf_token gw_cookies.txt | awk '{print $NF}')
curl -s -w "%{http_code}" -o /dev/null -X POST $GW/api/memory/reload \
  -b gw_cookies.txt -H "X-CSRF-Token: $CSRF"
# 预期: 200
```

#### TC-GW-04: 直连 Gateway 的 Rate Limiter

```bash
GW=http://localhost:8001

# 直连时 request.client.host 是真实 IP（无 nginx 代理），不读 X-Real-IP
for i in $(seq 1 6); do
  echo -n "attempt $i: "
  curl -s -w "%{http_code}\n" -o /dev/null -X POST $GW/api/v1/auth/login/local \
    -d "username=admin@example.com&password=wrong"
done
# 预期: 前 5 次 401，第 6 次 429
```

#### TC-GW-05: 直连 Gateway 不受 X-Real-IP 欺骗

```bash
GW=http://localhost:8001

# 直连时 client.host 不是 trusted proxy，X-Real-IP 被忽略
for i in $(seq 1 6); do
  echo -n "attempt $i (X-Real-IP spoofed): "
  curl -s -w "%{http_code}\n" -o /dev/null -X POST $GW/api/v1/auth/login/local \
    -H "X-Real-IP: 10.0.0.$i" \
    -d "username=admin@example.com&password=wrong"
done
# 预期: 前 5 次 401，第 6 次 429（伪造的 X-Real-IP 无效，所有请求共享真实 IP 的桶）
```

### 7.4 Docker 部署

> 启动命令：`./scripts/deploy.sh`（标准）或 `./scripts/deploy.sh --gateway`（Gateway 模式）
> Docker Compose 文件：`docker/docker-compose.yaml`
>
> 前置条件：
> - `.env` 中设置 `AUTH_JWT_SECRET`（否则每次容器重启 session 全部失效）
> - `DEER_FLOW_HOME` 挂载到宿主机目录（持久化 `users.db`）

#### TC-DOCKER-01: users.db 通过 volume 持久化

```bash
# 启动容器
./scripts/deploy.sh

# 等待启动完成
sleep 15
BASE=http://localhost:2026

# 注册用户
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"docker-test@example.com","password":"DockerTest1!"}' -w "\nHTTP %{http_code}"

# 检查宿主机上的 users.db
ls -la ${DEER_FLOW_HOME:-backend/.deer-flow}/users.db
sqlite3 ${DEER_FLOW_HOME:-backend/.deer-flow}/users.db \
  "SELECT email FROM users WHERE email='docker-test@example.com';"
```

**预期：** users.db 在宿主机 `DEER_FLOW_HOME` 目录中，查询可见刚注册的用户。

#### TC-DOCKER-02: 重启容器后 session 保持

```bash
# 登录拿 cookie
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=docker-test@example.com&password=DockerTest1!" \
  -c docker_cookies.txt -o /dev/null

# 验证 cookie 有效
curl -s -w "%{http_code}" -o /dev/null $BASE/api/v1/auth/me -b docker_cookies.txt
# 预期: 200

# 重启容器（不删 volume）
./scripts/deploy.sh down && ./scripts/deploy.sh
sleep 15

# 用旧 cookie 访问
curl -s -w "%{http_code}" -o /dev/null $BASE/api/v1/auth/me -b docker_cookies.txt
```

**预期：**
- 有 `AUTH_JWT_SECRET` → 200（session 保持）
- 无 `AUTH_JWT_SECRET` → 401（每次启动生成新临时密钥，旧 JWT 签名失效）

#### TC-DOCKER-03: 多 Worker 下 Rate Limiter 独立

```bash
# docker-compose.yaml 中 gateway 默认 4 workers
# 每个 worker 有独立的 _login_attempts dict
# 限速可能不精确（请求分散到不同 worker），但不会完全失效

for i in $(seq 1 20); do
  echo -n "attempt $i: "
  curl -s -w "%{http_code}\n" -o /dev/null -X POST $BASE/api/v1/auth/login/local \
    -d "username=docker-test@example.com&password=wrong"
done
```

**预期：** 在某个点开始返回 429（每个 worker 独立计数，阈值可能在 5~20 之间触发，取决于负载均衡分布）。

**已知限制：** In-process rate limiter 不跨 worker 共享。生产环境如需精确限速，需要 Redis 等外部存储。

#### TC-DOCKER-04: IM 渠道不经过 auth

```bash
# IM 渠道（Feishu/Slack/Telegram）在 gateway 容器内部通过 LangGraph SDK 通信
# 不走 nginx，不经过 AuthMiddleware

# 验证方式：检查 gateway 日志中 channel manager 的请求不包含 auth 错误
docker logs deer-flow-gateway 2>&1 | grep -E "ChannelManager|channel" | head -10
```

**预期：** 无 auth 相关错误。渠道通过 `langgraph-sdk` 直连 LangGraph Server（`http://langgraph:2024`），不走 auth 层。

#### TC-DOCKER-05: admin 密码写入 0600 凭证文件（不再走日志）

```bash
# 凭证文件写在挂载到宿主机的 DEER_FLOW_HOME 下
ls -la ${DEER_FLOW_HOME:-backend/.deer-flow}/admin_initial_credentials.txt
# 预期文件权限: -rw------- (0600)

cat ${DEER_FLOW_HOME:-backend/.deer-flow}/admin_initial_credentials.txt
# 预期内容: email + password 行

# 容器日志只输出文件路径，不输出密码本身
docker logs deer-flow-gateway 2>&1 | grep -E "Credentials written to|Admin account"
# 预期看到: "Credentials written to: /...../admin_initial_credentials.txt (mode 0600)"

# 反向验证: 日志里 NEVER 出现明文密码
docker logs deer-flow-gateway 2>&1 | grep -iE "Password: .{15,}" && echo "FAIL: leaked" || echo "OK: not leaked"
```

**预期：**
- 凭证文件存在于 `DEER_FLOW_HOME` 下，权限 `0600`
- 容器日志输出**路径**（不是密码本身），符合 CodeQL `py/clear-text-logging-sensitive-data` 规则
- `grep "Password:"` 在日志中**应当无匹配**（旧行为已废弃，simplify pass 移除了日志泄露路径）

#### TC-DOCKER-06: Gateway 模式 Docker 部署

```bash
# Gateway 模式：无 langgraph 容器
./scripts/deploy.sh --gateway
sleep 15

# 确认 langgraph 容器不存在
docker ps --filter name=deer-flow-langgraph --format '{{.Names}}' | wc -l
# 预期: 0

# auth 流程正常
curl -s -w "%{http_code}" -o /dev/null $BASE/api/models
# 预期: 401

curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@deerflow.dev&password=<日志密码>" \
  -c cookies.txt -w "\nHTTP %{http_code}"
# 预期: 200
```

### 7.4 补充边界用例

#### TC-EDGE-01: 格式正确但随机 JWT

```bash
RANDOM_JWT=$(python3 -c "
import jwt, time, uuid
print(jwt.encode({'sub':str(uuid.uuid4()),'ver':0,'exp':int(time.time())+3600}, 'wrong-secret-32chars-placeholder!!', algorithm='HS256'))
")
curl -s --cookie "access_token=$RANDOM_JWT" $BASE/api/v1/auth/me | jq .detail
```

**预期：** `{"code": "token_invalid", "message": "Token error: invalid_signature"}`

#### TC-EDGE-02: 注册时传 system_role=admin

```bash
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"hacker@example.com","password":"HackPass1!","system_role":"admin"}' | jq .system_role
```

**预期：** `"user"`（`system_role` 字段被忽略）

#### TC-EDGE-03: 并发改密码

```bash
# 注册用户，登录两个 session
curl -s -X POST $BASE/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"edge03@example.com","password":"EdgePass3!"}' -o /dev/null
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=edge03@example.com&password=EdgePass3!" -c s1.txt -o /dev/null
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=edge03@example.com&password=EdgePass3!" -c s2.txt -o /dev/null

CSRF1=$(grep csrf_token s1.txt | awk '{print $NF}')
CSRF2=$(grep csrf_token s2.txt | awk '{print $NF}')

# 并发改密码
curl -s -w "S1: %{http_code}\n" -o /dev/null -X POST $BASE/api/v1/auth/change-password \
  -b s1.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF1" \
  -d '{"current_password":"EdgePass3!","new_password":"NewEdge3a!"}' &
curl -s -w "S2: %{http_code}\n" -o /dev/null -X POST $BASE/api/v1/auth/change-password \
  -b s2.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF2" \
  -d '{"current_password":"EdgePass3!","new_password":"NewEdge3b!"}' &
wait
```

**预期：** 一个 200、一个 400（current_password 已变导致验证失败）。极端并发下可能两个都 200（SQLite 串行写），但最终只有一个密码生效。

#### TC-EDGE-04: Cookie SameSite 验证

> 完整的 HTTP/HTTPS cookie 属性对比见 §3.3 TC-ATK-06/07/07a。

```bash
curl -s -D - -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" 2>/dev/null | grep -i set-cookie
```

**预期：** `access_token` → `SameSite=lax`，`csrf_token` → `SameSite=strict`

#### TC-EDGE-05: HTTP 无 max_age / HTTPS 有 max_age

```bash
# HTTP
curl -s -D - -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" 2>/dev/null \
  | grep "access_token=" | grep -oi "max-age=[0-9]*" || echo "NO max-age (HTTP session cookie)"

# HTTPS
curl -s -D - -X POST $BASE/api/v1/auth/login/local \
  -H "X-Forwarded-Proto: https" \
  -d "username=admin@example.com&password=正确密码" 2>/dev/null \
  | grep "access_token=" | grep -oi "max-age=[0-9]*"
```

**预期：** HTTP 无 `Max-Age`（session cookie，浏览器关闭即失效），HTTPS 有 `Max-Age=604800`（7 天）

#### TC-EDGE-06: public 路径 trailing slash

```bash
for path in /api/v1/auth/login/local/ /api/v1/auth/register/ \
            /api/v1/auth/logout/ /api/v1/auth/setup-status/; do
  echo "$path: $(curl -s -w '%{http_code}' -o /dev/null $BASE$path)"
done
```

**预期：** 全部 307（redirect 去掉 trailing slash）或 200/405，不是 401

### 7.5 红队对抗测试

> 模拟攻击者视角，验证防线没有可利用的缝隙。

#### 7.5.1 路径混淆绕过

```bash
# 通过编码/双斜杠/路径穿越尝试绕过 AuthMiddleware 公开路径判断
for path in \
  "//api/v1/auth/me" \
  "/api/v1/auth/login/local/../me" \
  "/api/v1/auth/login/local%2f..%2fme" \
  "/api/v1/auth/login/local/..%2Fme" \
  "/API/V1/AUTH/ME"; do
  echo "$path: $(curl -s -w '%{http_code}' -o /dev/null $BASE$path)"
done
```

**预期：** 全部 401 或 404。不应有路径混淆导致跳过 auth 检查。

#### 7.5.2 CSRF 对抗矩阵

```bash
# 登录拿 cookie
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -c cookies.txt

CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

# Case 1: 有 cookie 无 header → 403
curl -s -w "%{http_code}" -o /dev/null \
  -X POST $BASE/api/threads -b cookies.txt \
  -H "Content-Type: application/json" -d '{"metadata":{}}'

# Case 2: 有 header 无 cookie → 403（删除 cookie 中的 csrf_token）
curl -s -w "%{http_code}" -o /dev/null \
  -X POST $BASE/api/threads \
  -b cookies.txt \
  -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/json" -d '{"metadata":{}}'

# Case 3: header 和 cookie 不匹配 → 403
curl -s -w "%{http_code}" -o /dev/null \
  -X POST $BASE/api/threads -b cookies.txt \
  -H "X-CSRF-Token: wrong-token" \
  -H "Content-Type: application/json" -d '{"metadata":{}}'

# Case 4: 旧 CSRF token（登出再登录后） → 旧 token 应失效
curl -s -X POST $BASE/api/v1/auth/logout -b cookies.txt
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -c cookies.txt
# 用旧 CSRF 发请求
curl -s -w "%{http_code}" -o /dev/null \
  -X POST $BASE/api/threads -b cookies.txt \
  -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/json" -d '{"metadata":{}}'
```

**预期：** Case 1-3 全部 403。Case 4 应 403（旧 CSRF 与新 cookie 不匹配）。

#### 7.5.3 Token Replay（登出后旧 token 重放）

```bash
# 登录，保存 cookie
curl -s -X POST $BASE/api/v1/auth/login/local \
  -d "username=admin@example.com&password=正确密码" -c cookies.txt

# 提取 access_token 值
TOKEN=$(grep access_token cookies.txt | awk '{print $NF}')

# 登出
curl -s -X POST $BASE/api/v1/auth/logout -b cookies.txt

# 手工注入旧 token（模拟攻击者窃取了 token）
curl -s -w "%{http_code}" -o /dev/null \
  $BASE/api/v1/auth/me --cookie "access_token=$TOKEN"
```

**预期：** 200（已知限制：登出只清客户端 cookie，不 bump `token_version`。旧 token 在过期前仍有效）。
**安全备注：** 如需严格防重放，需在登出时 `token_version += 1`。当前设计选择不做，因为成本是所有设备的 session 全部失效。

#### 7.5.4 跨站强制登出

```bash
# 攻击者从第三方站点 POST /logout（无需认证、无需 CSRF）
curl -s -X POST $BASE/api/v1/auth/logout -w "%{http_code}"
```

**预期：** 200（logout 是 public + CSRF 豁免）。
**风险评估：** 低——只影响可用性（被强制登出），不泄露数据。浏览器 `SameSite=Lax` 限制了真实跨站场景下 cookie 不会被带上，所以实际上第三方站点的 POST 不会清除用户 cookie。

#### 7.5.5 Metadata 注入攻击（所有权伪造）

```bash
# 尝试在创建 thread 时注入其他用户的 user_id
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')
curl -s -X POST $BASE/api/threads \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"metadata":{"owner_id":"victim-user-id"}}' | jq .metadata.owner_id
```

**预期：** 返回的 `metadata.owner_id` 应为当前登录用户的 ID，不是请求中注入的 `victim-user-id`。服务端应覆盖客户端提供的 `user_id`。

#### 7.5.6 HTTP Method 探测

```bash
# HEAD/OPTIONS 不应泄露受保护资源信息
for method in HEAD OPTIONS TRACE; do
  echo "$method /api/models: $(curl -s -w '%{http_code}' -o /dev/null -X $method $BASE/api/models)"
done
```

**预期：** HEAD/OPTIONS 返回 401 或 405。TRACE 应返回 405。

#### 7.5.7 Rate Limiter IP 维度缺陷验证

```bash
# 通过不同的 X-Forwarded-For 绕过限速（验证是否用 client.host 而非 header）
for i in $(seq 1 6); do
  curl -s -w "attempt $i: %{http_code}\n" -o /dev/null \
    -X POST $BASE/api/v1/auth/login/local \
    -H "X-Forwarded-For: 10.0.0.$i" \
    -d "username=admin@example.com&password=wrong"
done
```

**预期：** 如果 rate limiter 基于 `request.client.host`（实际 TCP 连接 IP），所有请求来自同一 IP，第 6 个应返回 429。X-Forwarded-For 不应影响限速判断。

#### 7.5.8 Junk Cookie 穿透验证

```bash
# middleware 只检查 cookie 存在性，不验证 JWT
# 确认 junk cookie 能过 middleware 但被下游 @require_auth 拦截
curl -s -w "%{http_code}" $BASE/api/v1/auth/me \
  --cookie "access_token=not-a-jwt"
```

**预期：** 401（middleware 放行，`get_current_user_from_request` 解码失败返回 401）。
**安全备注：** middleware 是 presence-only 检查，有意设计。完整验证交给 `@require_auth`。

#### 7.5.9 路由覆盖审计

```bash
# 列出所有注册的路由，检查哪些没有 @require_auth
cd backend && PYTHONPATH=. python3 -c "
from app.gateway.app import create_app
app = create_app()
public_prefixes = ['/health', '/docs', '/redoc', '/openapi.json',
                   '/api/v1/auth/login', '/api/v1/auth/register',
                   '/api/v1/auth/logout', '/api/v1/auth/setup-status']
for route in app.routes:
    path = getattr(route, 'path', '')
    if not path or not path.startswith('/api'):
        continue
    is_public = any(path.startswith(p) for p in public_prefixes)
    if not is_public:
        print(f'  {path}')
" 2>/dev/null
```

**预期：** 列出的所有路由都应由 AuthMiddleware（cookie 存在性）+ `@require_auth`/`@require_permission`（JWT 验证）双层保护。检查是否有遗漏。

---

## 八、回归清单

每次 auth 相关代码变更后必须通过：

```bash
# 单元测试（168 个）
cd backend && PYTHONPATH=. uv run pytest \
  tests/test_auth.py \
  tests/test_auth_config.py \
  tests/test_auth_errors.py \
  tests/test_auth_type_system.py \
  tests/test_auth_middleware.py \
  tests/test_langgraph_auth.py \
  -v

# 核心接口冒烟
curl -s $BASE/health                              # 200
curl -s $BASE/api/models                          # 401 (无 cookie)
curl -s -X POST $BASE/api/v1/auth/setup-status    # 200
curl -s $BASE/api/v1/auth/me -b cookies.txt       # 200 (有 cookie)
```
