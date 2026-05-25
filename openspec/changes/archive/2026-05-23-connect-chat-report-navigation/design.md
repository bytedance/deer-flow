## Context

ISSUE-01 定版了主流程对象模型，所有主链页面路由已存在：
- `/workspace/chats/[thread_id]` — 对话
- `/workspace/agents/[agent_name]/chats/[thread_id]` — agent 对话
- `/workspace/report-runs` — 报告历史列表
- `/workspace/report-runs/[run_id]` — 报告运行详情

ISSUE-02 统一了 RunStatus 类型，`ReportRunRecord` 已包含 `thread_id` + `run_id`。

当前跳转基础设施：
- `CrossPageContext` 协议（`frontend/src/core/models/navigation.ts`）：序列化 sourceType/sourceId/threadId/runId → base64 query param
- `SourceBreadcrumb`：读取 query param 渲染"来自{source}"面包屑
- `ChatReportTrigger`：聊天 header 下拉列出当前 thread 的 report runs，点击跳到 report-run detail
- `ReportRunDetailPage`：header 有 SourceBreadcrumb + "Back to source chat" 链接

已覆盖的跳转路径：Chat → Report detail（单向），Report detail → Chat（回跳）

## Goals / Non-Goals

**Goals:**
- 报告列表页（runs tab）每行可看到来源对话并直达
- Chat → 产物（artifact）有直达链接，不需要经过 report run detail
- 所有跳转使用统一的 CrossPageContext 协议
- 跳转日志有结构化 trace id 可供控制台和日志系统消费

**Non-Goals:**
- 不新建独立的产物查看页面（产物预览已在对话内通过 GenUI 渲染）
- 不改变后端 API（数据已齐）
- 不改变 sidebar 结构
- 不改变 closed-loop 跳转链路（ISSUE-12 范围）

## Decisions

### 1. 报告列表增加 thread 列而非独立 tab

已有"对话"tab 按 thread 聚合，runs tab 按 run 展示。在 runs tab 增加"来源对话"列（可点击跳转），提供交叉视角而非新增第三个 tab。

**Alternatives considered:**
- 新增"thread-run 交叉视图" tab → 过度设计，当前两 tab 足够
- 在每行 run ID 旁边加 thread icon → 不够显式，列更清晰

### 2. Chat → Artifact 跳转复用 CrossPageContext 协议

ChatReportTrigger 下拉中已有各 run 的状态信息，增加产物文件的直达链接（Markdown/PDF 下载），携带 `sourceType: "chat"` 上下文参数但不新建中间页面。

产物以文件下载为主（保持现有行为），但在下载 URL 上附加 `?from=...`（CrossPageContext 编码），服务端日志可追踪下载来源。前端下载点击同时记录 `logCrossPageNavigation`。

**Alternatives considered:**
- 为产物建独立查看页 → 产物已在 GenUI 中预览，重复建设
- 不做产物直达 → 用户只能 report run detail → download 两步跳，体验差

### 3. 结构化日志：Trace ID 格式不变，增加 event 对象

`logCrossPageNavigation` 当前输出 `console.info` 字符串。改为同时输出结构化 object（含 traceId、direction、sourceType、sourceId、threadId、runId、timestamp），便于 DevOps 通过浏览器日志或 RUM 工具过滤。

不引入服务端日志端点（那是 ISSUE-07 的可追踪性范围）。

**Alternatives considered:**
- 新增 `/api/telemetry/navigation` 端点 → 过度设计，ISSUE-03 只需最小可观测标识
- 不改 → 达不到"关键跳转链路具备最小可观测标识"验收标准

## Risks / Trade-offs

- [Thread 数据可能缺失] ReportRunRecord.thread_id 理论上可能为空（旧数据/API 创建），列表列应展示"—"而非报错 → 降级处理
- [产物路径可能为 null] artifact_paths.md/pdf 可能为空（运行中断），ChatReportTrigger 下拉应只展示实际存在的产物 → 条件渲染
- [URL 长度] CrossPageContext 经 base64 编码后约 150-200 字符，在 URL 中无问题，但需确保不破坏 Next.js 路由匹配
