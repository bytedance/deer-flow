## Why

EHM 通过 DeerFlow deep-link 打开日报、周报、月报和缺陷 AI 分析时，当前使用的都是 `/chats/new` 入口。对日报 / 周报 / 月报这类 `auto_send=1` deep-link 而言，只要浏览器再次加载同一个 `/new?...` URL，DeerFlow 就会再次自动发送并重新执行。

这会带来两个不一致的交互：

- 用户只是刷新浏览器或宿主 iframe 重建，期望恢复刚才那次会话历史，但 DeerFlow 会再次执行
- 用户显式再次点击同一个业务入口，期望重新执行，但当前系统无法区分“刷新恢复”与“显式再开一次”

需要引入一个可恢复的启动会话标识，让 DeerFlow 能区分：

- 同一个启动会话的恢复
- 相同 deep-link 参数下的一次新的显式打开

## What Changes

- 为 deep-link API 新增前端保留参数 `launch_id`
- DeerFlow 前端为 `/chats/new` deep-link 建立 `launch_id -> threadId` 的会话级映射
- 同一浏览器会话内再次打开相同 `launch_id` 时，优先恢复已创建线程，而不是重复 auto-send
- 调用方若希望相同业务参数重新执行，必须生成新的 `launch_id`
- 更新 deep-link API 文档，明确 `launch_id` 的恢复语义和调用方约定

## Capabilities

### New Capabilities

- `deep-link-launch-recovery`: DeerFlow 支持在同一浏览器会话内恢复已由 deep-link 创建的线程，而不重复触发自动发送

### Modified Capabilities

- `deep-link-passthrough`: 增加前端保留参数 `launch_id`，该参数不透传给 Agent，只用于 DeerFlow 前端恢复逻辑

## Impact

- Frontend deep-link parsing: 解析 `launch_id`
- Frontend new-thread chat pages: 在 auto-send 前优先尝试恢复历史 thread
- Frontend session storage helpers: 保存 `launch_id -> threadId`
- Documentation: 更新 `docs/deep-link-api.md`
- No backend API or database schema changes are required
