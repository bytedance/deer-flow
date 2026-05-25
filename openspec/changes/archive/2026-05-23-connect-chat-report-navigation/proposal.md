## Why

ISSUE-01 定版了主流程（Thread→Run→ReportRun→Artifact）和对象模型，ISSUE-02 统一了生命周期状态语义，但主链页面之间的跳转链路仍有断点：用户从聊天能看到报告按钮、从报告详情能回聊天，但从报告列表视图看不到来源对话，产物下载后无法追溯生成上下文。这导致"页面能访问，但链路无法追踪"，需要补齐剩余的跳转缺口，让结果消费与生成上下文形成闭环。

## What Changes

- 报告运行列表（runs tab）增加"来源对话"列，可直接跳转到对应 thread
- 报告运行详情页已有的 SourceBreadcrumb 和 Source Chat 区块确保在任何进入路径下都可回溯
- ChatReportTrigger 下拉项中增加产物（artifact）直达链接，不只跳报告详情
- 所有跨页跳转统一使用 CrossPageContext 协议，确保 SourceBreadcrumb 在目标页生效
- 跳转链路日志从 `console.info` 升级为可被运维消费的结构化事件（至少包含 trace id、方向、源/目标类型）

## Capabilities

### Modified Capabilities

- `chat-to-report-navigation`: 已有 spec 覆盖了 Chat→Report 和 Report→Chat 基本跳转。本次变更在以下方面扩展该 spec 的 requirements：
  - 报告运行列表页需展示来源对话并可跳转
  - Chat→产物（artifact）直达链接
  - 跳转链路可观测标识的结构化日志要求

## Impact

- Frontend: `report-runs-page.tsx`（增加 thread 列）、`chat-report-trigger.tsx`（产物直达）、`navigation.ts`（结构化日志）
- Backend: 无需变更（ReportRunRecord 已包含 `thread_id`）
- 无破坏性变更，纯增量补全
