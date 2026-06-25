## Context

当前 DeerFlow deep-link 语义以 `/workspace/chats/new` 和 `/workspace/agents/[agent_name]/chats/new` 为核心。`auto_send=1` 被定义为页面打开后自动发送消息或自动启动 Agent，且 deep-link 参数仅在 `isNewThread === true` 时生效。

这套设计适合“直达新任务”，但不适合“恢复刚才那次任务”：

- 同一个 `/new?...auto_send=1` URL 被重新加载时，DeerFlow 无法知道这是浏览器刷新，还是调用方明确要求再次执行
- 当前线程一旦创建成功，DeerFlow 会把 URL 从 `/chats/new` 替换为 `/chats/{threadId}`，但这个 threadId 只存在 DeerFlow 前端本地状态中，宿主系统并不知道

因此需要一个纯前端、同浏览器会话内的恢复协议。

## Goals / Non-Goals

**Goals:**

- 为 deep-link 新增 `launch_id`，让调用方显式区分一次“启动会话”
- DeerFlow 在同一浏览器会话内把 `launch_id` 绑定到创建后的 `threadId`
- 刷新或重新进入同一个 `launch_id` 时，直接恢复对应 thread，而不是重复 auto-send
- 当调用方传入新的 `launch_id` 时，即使其他业务参数完全相同，也应视为一次新的显式执行

**Non-Goals:**

- 不新增后端接口或数据库表保存 `launch_id`
- 不保证跨浏览器、跨设备、跨标签页长期恢复
- 不改变 `auto_send=1` 的基础语义；无 `launch_id` 时仍保持现有行为
- 不让 `launch_id` 进入 Agent passthrough 参数

## Decisions

1. **`launch_id` 是前端保留参数，不透传给 Agent**
   - `launch_id` 仅用于 DeerFlow 前端恢复逻辑
   - 它应从 deep-link 参数中解析，但不进入 `passthroughParams`
   - 这样不会污染 Agent 的业务参数空间

2. **使用 `sessionStorage` 保存 `launch_id -> threadId`**
   - 恢复语义只要求同一浏览器会话内有效
   - `sessionStorage` 正好满足：刷新保留、关闭标签页失效
   - 数据结构按 `launch_id` 索引保存 `{ threadId, routeKey, updatedAt }`
   - `routeKey` 用于区分普通 chat 与不同 Agent chat，避免相同 `launch_id` 被错误恢复到别的页面
   - 为防止单标签页长期累积映射，前端只保留最近更新的有限条目并按 `updatedAt` 裁剪

3. **恢复检查发生在 auto-send 之前**
   - 当 `isNewThread === true` 且 deep-link 带 `launch_id` 时：
     - 先检查 `sessionStorage` 是否已有映射
     - 若有，直接 `setThreadId(threadId)`、`setIsNewThread(false)`，并用 `history.replaceState()` 切到对应的 thread URL
     - 不再执行 auto-send
   - 若无映射，再按现有逻辑执行 auto-send / auto_start

4. **线程创建成功后立即写回映射**
   - 当 `/chats/new` 首次通过 deep-link 创建线程成功时，`onStart(createdThreadId)` 已经拿到真实 threadId
   - 此时同步写入 `launch_id -> createdThreadId`
   - 之后同一 `launch_id` 的刷新即可恢复

5. **相同业务参数的“再次执行”由新的 `launch_id` 决定**
   - DeerFlow 不尝试比较 deep-link 参数是否完全相同
   - 对 DeerFlow 来说，是否恢复只由 `launch_id` 是否命中已有映射决定
   - 这让宿主系统可以稳定表达：
     - 刷新恢复：复用旧 `launch_id`
     - 显式重开：生成新 `launch_id`

## Risks / Trade-offs

- **宿主不传 `launch_id`** -> DeerFlow 无法区分刷新与重开，行为维持现状。缓解：文档明确 EHM / 外部系统集成建议。
- **`sessionStorage` 生命周期有限** -> 关闭标签页后无法恢复。缓解：本次目标仅覆盖刷新和同标签页 iframe 重建场景。
- **错误恢复到跨 Agent thread** -> 若不同 Agent 误用同一个 `launch_id` 可能恢复错误线程。缓解：映射记录中保存 `routeKey`，恢复时做路径校验。
- **普通 `/workspace/chats/new` 与 Agent chat 页实现重复** -> 两个页面都支持 deep-link，需要共享 helper，避免分叉逻辑。

## Migration Plan

1. 发布 DeerFlow 前端改动，同时保持没有 `launch_id` 时完全兼容旧行为。
2. EHM 开始为日报、周报、月报和 AI 分析 deep-link 生成并持久化 `launch_id`。
3. 刷新或宿主 iframe 重建时，EHM 复用同一个 `launch_id`，DeerFlow 自动恢复历史 thread。
