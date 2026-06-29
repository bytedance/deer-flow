## Why

DeerFlow 当前支持两类 EHM 免登恢复方式：

- 读取 `ehm_token` / `ehm_user`
- 在 `401` 后使用现有 `ehm_token` 重新调用 `/api/v1/auth/ins-base/authenticate`

但在 EHM iframe 长驻场景下，宿主 token 会静默刷新，而 DeerFlow 侧并不会自动收到新的 `ehm_token`。这样一旦 DeerFlow 内部 session 失效，它仍然会使用旧 token 重认证，导致：

- `/api/v1/auth/me` 或业务接口出现 `401`
- `authenticate` 尝试失败
- 最终跳回登录页或反复重试

需要让 DeerFlow 能接收宿主发来的新 EHM token，并在不重载页面的前提下更新自身 EHM 鉴权状态和内部 session。

## What Changes

- 为 DeerFlow 前端新增宿主 iframe token 刷新消息协议
- 收到宿主新 token 后，更新前端保存的 `ehm_token` / `ehm_user`
- 收到新 token 后，主动调用一次 `/api/v1/auth/ins-base/authenticate` 重建 DeerFlow session cookie
- 让后续 `401` 恢复逻辑优先使用最新同步的 EHM token
- 让首次 `401` 仅作为恢复触发器，不直接把 iframe 判定为必须跳转登录页
- 更新文档，明确 EHM iframe 长驻场景下的 token 重同步协议

## Capabilities

### New Capabilities

- `ehm-iframe-token-resync`: DeerFlow 支持在 iframe 长驻场景下接收宿主刷新后的 EHM token，并无刷新页面地重建内部 session

### Modified Capabilities

- `user-auth`: EHM 免登用户在宿主 token 刷新后，可以继续通过最新 token 恢复 DeerFlow session

## Impact

- `frontend/src/core/auth/ehm-auth.ts`
- `frontend/src/core/api/fetcher.ts`
- DeerFlow 前端 iframe 宿主桥接模块或 AI 工作台入口页
- `docs/deep-link-api.md`
- `openspec/changes/ehm-iframe-token-resync/specs/user-auth/spec.md`
