# 管理页面保持登录方案

## 方案结论

实现“保持登录”，不实现“记住密码”。密码只随登录表单提交一次，不写入浏览器存储、日志、运行上下文或沙盒环境。

本次改造沿用现有认证链路：

`LoginPage -> /api/v1/auth/login/local -> LocalAuthProvider -> JWT -> HttpOnly access_token cookie -> AuthProvider / fetchWithAuth / AuthMiddleware`

新增点只挂在原链路上：

- 前端登录页新增“保持登录”勾选项。
- 登录表单新增 `remember_me` 字段。
- Gateway 新增统一会话 cookie 策略。
- CSRF cookie 使用与 access cookie 相同的最终生命周期。

## 背景与目标

Issue #4194 的用户诉求是“不要每次登录都填写账号密码”。现有 Gateway 已使用 `HttpOnly access_token` cookie 和双提交 `csrf_token` cookie。问题不应通过保存密码解决，而应通过更明确的会话持久化策略解决。

目标：

- 提升再次打开页面时的登录体验。
- 保持密码不落盘。
- 覆盖本地、HTTPS 反代、远程沙盒等部署形态。
- 避免 `access_token` 和 `csrf_token` 生命周期不一致导致“已登录但 POST 403”。

## 链路设计

### 前端

登录页新增两个状态：

- `rememberMe`：是否保持登录，默认 `true`。
- remembered email：仅在用户选择保持登录时保存邮箱到 `localStorage`，便于下次预填。

登录成功后：

- `rememberMe=true`：保存邮箱和偏好。
- `rememberMe=false`：清除已保存邮箱和偏好。

前端不保存密码，不保存 token。

### Gateway

登录接口接收 `remember_me`：

```text
username=<email>&password=<password>&remember_me=true|false
```

`SessionCookiePolicy` 统一决策：

| 场景 | 策略 |
| ---- | ---- |
| `remember_me=false` | session cookie |
| HTTPS 或可信反代后的 HTTPS | `Secure + Max-Age` |
| `localhost` / loopback HTTP | 允许 `Max-Age`，便于本地开发 |
| 公网 HTTP / 临时沙盒 HTTP | 降级为 session cookie |
| 显式运维开关允许公网 HTTP 持久化 | 非默认，需环境变量显式开启 |

Gateway 在设置 `access_token` 后，把最终 `max_age` 写入 `request.state`。CSRF middleware 设置 `csrf_token` 时读取同一个值，确保两枚 cookie 同寿命。

Gateway 还会写入一个 `HttpOnly` 的会话偏好 cookie，用于改密、管理员初始化、OIDC callback 等重新签发 session 的路径。这样用户在登录时取消“保持登录”后，后续重新签发 token 不会被静默升级成持久 cookie。

### 沙盒边界

认证 cookie 只属于浏览器和 Gateway：

- 不传入 agent runtime context。
- 不注入 sandbox env。
- 不写入 checkpoint。
- 不影响 IM channel 内部鉴权链路。

远程沙盒如果每次使用不同公网域名，浏览器 cookie 无法跨域复用，这是浏览器隔离规则，不在本 issue 内解决。

### 非目标

本次不处理跨站 iframe 持久登录。该场景需要 `SameSite=None; Secure`、明确嵌入 allowlist 和额外 CSRF/点击劫持评估，应作为单独方案。

## 验证计划

- 后端 cookie policy 单测：
  - HTTPS 持久化。
  - `localhost` HTTP 持久化。
  - 公网 HTTP 降级 session。
  - `remember_me=false` 降级 session。
  - 运维开关允许公网 HTTP 持久化。
- 后端 API 契约测试：
  - 登录表单携带 `remember_me=false` 时 `access_token` 无 `Max-Age`。
  - `access_token` 和 `csrf_token` 的 `Max-Age` 一致。
  - 失败登录、改密、初始化、OIDC helper 路径保留正确 cookie 生命周期。
  - logout 清理 `access_token` 和 `csrf_token`。
- 前端单测：
  - 只保存邮箱和偏好。
  - 关闭保持登录会清理邮箱。
  - localStorage 异常时不阻塞登录页。
- 手工验证：
  - `localhost:2026` 登录后重开浏览器仍可访问工作区。
  - HTTPS 反代下 `Set-Cookie` 带 `Secure` 和 `Max-Age`。
  - 公网 HTTP 地址不产生持久 cookie。
