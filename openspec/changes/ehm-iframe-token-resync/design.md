## Context

当前 DeerFlow 前端的 `fetcher` 在 `401` 时会按顺序尝试：

1. 使用当前 `ehm_token` 调 `/api/v1/auth/ins-base/authenticate`
2. 使用 `InS-refresh` 调 `/api/v1/auth/ins-base/refresh`
3. 使用 DeerFlow 自己的 `refresh_token` cookie 调 `/api/v1/auth/refresh`
4. 最终跳登录页

问题是第 1 步依赖的 `ehm_token` 是 iframe 页面现有 cookie 中的值。若宿主已经刷新了 EHM token，而 DeerFlow 没收到，那么它在整个会话里都会拿旧 token 做重认证。

## Goals / Non-Goals

**Goals**

- DeerFlow 能在 iframe 长驻期间接收宿主发来的新 EHM token
- DeerFlow 在 `401` 时能够先向宿主请求“最新可用 token”，而不是只消费当前 cookie 中的旧 token
- 收到后立即更新本地 `ehm_token` / `ehm_user`
- 收到后主动重建 DeerFlow session，减少后续 `401`
- 即使已经落到 `/login`，也仍能接收宿主恢复消息

**Non-Goals**

- 不引入新的后端数据库状态
- 不改变 `/api/v1/auth/ins-base/authenticate` 的入参协议
- 不把宿主消息协议扩展成通用 RPC 系统

## Decisions

### 1. 新增宿主消息类型 `AI_TOKEN_REFRESH`

DeerFlow 前端新增一类宿主消息：

- `AI_TOKEN_REFRESH`

消息体包含：

- `ehmToken`
- `ehmUser`
- `issuedAt`

前端只接受来自允许宿主 origin 的消息，并校验消息结构。

### 1.1 继续使用 `AI_REQUEST_USER`，但语义升级为“请求最新可用 token”

当 DeerFlow 发现：

- 当前 `ehm_token` 已过期
- 或 `401` 后用现有 `ehm_token` 重认证失败

前端应向宿主发送 `AI_REQUEST_USER`，请求宿主返回“最新可用 token”。

这里的关键约束是：DeerFlow 不假设宿主当前内存里的 token 一定可用，宿主可以先执行 refresh 后再回复。

### 2. 收到消息后更新 EHM Cookie

DeerFlow 前端在收到 `AI_TOKEN_REFRESH` 后：

- 用新值覆盖当前 `ehm_token`
- 如有 `ehm_user`，同步覆盖 `ehm_user`

这样后续 `buildAuthHeaders()` 和 `reauthenticateEhmSession()` 读取到的就是最新 token。

### 3. 更新 Cookie 后主动重建 DeerFlow session

仅更新 `ehm_token` 还不够，因为 DeerFlow 当前业务请求多数依赖自己的 `access_token` cookie。

因此收到 `AI_TOKEN_REFRESH` 后，前端应主动调用：

- `/api/v1/auth/ins-base/authenticate`

用新的 `Authorization: Bearer <ehm_token>` 立即换回 DeerFlow 的最新 session cookie，减少下一次业务请求再先经历一次 `401`。

### 4. 用时间戳避免旧消息覆盖新 token

如果宿主因重试、延迟或补发发送了多条消息，前端需要避免旧 token 覆盖新 token。

因此前端保存最近一次接受的 `issuedAt`：

- 仅当消息 `issuedAt` 更新时才覆盖 cookie 和重建 session
- 缺失 `issuedAt` 的消息按最低优先级处理

### 5. 失败时保持现有 401 恢复链路

如果宿主消息同步或主动重建 session 失败：

- 不新增额外跳转
- 保持当前 `401 -> reauthenticate -> refresh -> login` 兜底链路

这样宿主消息机制只是提升成功率和稳定性，不替代现有恢复逻辑。

### 6. 宿主桥接需要覆盖登录页

若 DeerFlow 已经因为 `401` 落到了 `/login`，而宿主桥接只挂在 workspace layout 下，则登录页接收不到宿主后续发来的 `AI_TOKEN_REFRESH`，会导致：

- 宿主已经拿到新 token
- iframe 仍停留在登录页
- 页面无法自动恢复

因此宿主桥接应提升到能覆盖：

- `/workspace/...`
- `/login`

使 iframe 即便已经落到登录页，也仍能在宿主返回新 token 后恢复会话。

### 7. 登录页需要主动重试宿主 token 拉取

仅把桥接挂到根布局还不够。若 `401` 当下向宿主请求 token 的那一次已经超时，页面再跳到 `/login` 后不会自动重新请求，除非登录页显式再发一次 `AI_REQUEST_USER`。

因此登录页在 iframe 场景下应：

- 在未认证状态主动请求一次宿主最新 token
- 等待宿主回传 `AI_TOKEN_REFRESH`
- 收到并重建 session 成功后自动跳回 `next` 或 `/workspace`

### 8. 宿主 token 请求超时需要覆盖真实 refresh 时延

`AI_REQUEST_USER` 不是纯内存读操作；宿主可能先执行一次 refresh 再回包。

因此 DeerFlow 侧等待宿主 token 的超时必须覆盖一次真实 refresh RTT，避免在宿主尚未回包时就先判失败并跳登录页。

## Risks / Trade-offs

- 如果宿主 origin 校验配置错误，消息会被丢弃。缓解：沿用现有 iframe origin 配置来源。
- 若宿主发来无效 token，前端主动 authenticate 仍会失败。缓解：保留原兜底链路。
- 若没有统一桥接模块，消息处理代码可能分散。缓解：优先抽成共享 helper。

## Verification

- 前端能够接收并校验 `AI_TOKEN_REFRESH`
- 前端在 `401` 且当前 EHM token 不可用时会向宿主发送 `AI_REQUEST_USER`
- 收到后更新 `ehm_token` / `ehm_user`
- 收到后主动调用 `/api/v1/auth/ins-base/authenticate`
- 登录页同样能够接收宿主刷新消息并恢复会话
- 登录页会主动再次请求宿主 token，而不是只依赖 401 当下那一次请求
- 宿主 refresh 发生在数秒内时，前端不会因为过短超时而过早放弃恢复
- 后续 `401` 恢复路径读取的是最新同步 token
