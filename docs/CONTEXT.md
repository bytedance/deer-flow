# CONTEXT — 前端核心领域术语表

前端核心领域的概念定义、生命周期和关系。面向开发者（人类和 AI agent）在阅读和修改代码时使用一致的词汇。

---

## 1. 对话（Thread）

### Thread（对话）

用户与 agent 的一次交互会话。拥有消息历史、运行时配置和动态状态。对应 LangGraph 的 thread。

- **标识**: `thread_id`（LangGraph 分配的 UUID）
- **元数据**: `agent_name`（选择的 agent）
- **状态** (`AgentThreadState`): `title`、`messages`、`artifacts`、`todos`
- **代码**: [frontend/src/core/threads/types.ts](../frontend/src/core/threads/types.ts)

### ThreadContext（对话上下文）

发送消息时附带的运行时参数，控制 agent 的行为模式。

| 字段 | 类型 | 说明 |
|------|------|------|
| `thread_id` | string | 对话 ID |
| `model_name` | string? | 指定模型 |
| `thinking_enabled` | boolean | 是否启用扩展推理 |
| `is_plan_mode` | boolean | 是否启用 Plan 模式（TodoListMiddleware） |
| `subagent_enabled` | boolean | 是否启用子代理派发 |
| `reasoning_effort` | "minimal" / "low" / "medium" / "high" | 推理深度 |
| `agent_name` | string? | 当前使用的 agent |
| `knowledge_base_selection` | { enabled, selected_ids[] }? | 知识库选择 |

mode 到 context 的映射关系：flash → thinking_enabled=false；pro → is_plan_mode=true, reasoning_effort="medium"；ultra → subagent_enabled=true, reasoning_effort="high"。

- **代码**: [frontend/src/core/threads/types.ts](../frontend/src/core/threads/types.ts)

### Stream（流）

通过 LangGraph SDK 建立的 SSE 连接，实时接收 agent 运行过程中的事件。

三种事件类型：
- `values` — 完整状态快照（title、artifacts 变化）
- `messages` / `messages-tuple` — 消息增量更新
- `custom` — 自定义事件（`ui_block`、`task_running`、`llm_retry`）

- **代码**: [frontend/src/core/threads/hooks.ts](../frontend/src/core/threads/hooks.ts) `useThreadStream`

### History（历史）

对话的历史消息，按 run 倒序分页加载。每次加载一个 run 的消息，通过 `appendUniqueMessages` 与当前消息列表去重合并。加载完的 run 记录在 `loadedRunIds` 中防止重复加载。

- **代码**: [frontend/src/core/threads/hooks.ts](../frontend/src/core/threads/hooks.ts) `useThreadHistory`

### Merge（消息合并）

三段消息的合并策略：
1. **History messages**（历史消息，已持久化）
2. **Live messages**（当前 SSE 流中的消息）
3. **Optimistic messages**（前端先行展示的临时消息）

合并算法：从 history 末尾向前扫描，找到与 live 重叠的后缀（通过 message.id 或 tool_call_id 匹配），截断 history 后拼接 `history + live + optimistic`。

- **代码**: [frontend/src/core/threads/hooks.ts](../frontend/src/core/threads/hooks.ts) `mergeMessages`

### Export（导出）

将对话导出为文件下载。支持两种格式：Markdown（`formatThreadAsMarkdown`）和 JSON（`formatThreadAsJSON`）。Markdown 导出包含推理内容折叠区、工具调用列表、并剥离 `<uploaded_files>` 标签。

- **代码**: [frontend/src/core/threads/export.ts](../frontend/src/core/threads/export.ts)

---

## 2. 消息（Message）

### Message（消息）

LangGraph 定义的消息实体，核心类型：

| 类型 | 含义 |
|------|------|
| `human` | 用户输入 |
| `ai` | Agent 回复（可能包含 tool_calls 和 reasoning） |
| `tool` | 工具执行结果 |
| `system` | 系统提示 |

每条消息有 `id`、`type`、`content`（string 或 content block 数组）、可选的 `tool_calls`、`additional_kwargs`。

### MessageGroup（消息组）

将连续消息按交互阶段分组的抽象，用于渲染决策。

| 组类型 | 含义 | 展示方式 |
|--------|------|----------|
| `human` | 用户消息 | 直接展示 |
| `assistant:processing` | 推理 + 工具调用的中间 AI 消息 | 不直接展示，作为 assistant 组的前置上下文 |
| `assistant` | Agent 的最终文本回复 | 直接展示 |
| `assistant:present-files` | 展示产物的 AI 消息 | 产物展示 |
| `assistant:clarification` | Agent 请求用户澄清 | 醒目展示 |
| `assistant:subagent` | 派发子代理的消息 | 子代理任务卡片 |

分组规则：`human` 和 `assistant` 是终结组（不再追加后续消息），`assistant:processing` 是开放式组（后续 tool 消息和 AI 推理消息都归入此组）。

- **代码**: [frontend/src/core/messages/utils.ts](../frontend/src/core/messages/utils.ts) `getMessageGroups`

### Deduplication（消息去重）

通过 `message.id` 集合去重：`appendUniqueMessages(prev, incoming)` 过滤掉已在 `prev` 中的消息，确保历史和直播流之间不重复。

- **代码**: [frontend/src/core/threads/message-history.ts](../frontend/src/core/threads/message-history.ts)

### Reasoning（推理内容）

从 AI 消息中提取的"思考过程"内容，支持三种提取路径（按优先级）：
1. `additional_kwargs.reasoning_content` — 服务端直接提供的推理字段
2. `<think>...</think>` — 内联在 content 中的 XML 标签
3. `thinking` content block — Anthropic 格式的 thinking block

推理内容在渲染时折叠展示，在导出时包裹在 `<details>` 标签中。

- **代码**: [frontend/src/core/messages/utils.ts](../frontend/src/core/messages/utils.ts) `extractReasoningContentFromMessage`

### Embedded tags（嵌入标签）

消息内容中嵌入的 XML 标签，在渲染前需要解析并剥离：

| 标签 | 含义 | 处理方式 |
|------|------|----------|
| `<uploaded_files>...</uploaded_files>` | 已上传文件列表 | `stripUploadedFilesTag` 剥离，`parseUploadedFiles` 解析为 FileInMessage[] |
| `<retrieval_trace>...</retrieval_trace>` | 知识库检索来源 | `extractRetrievalTrace` 解析为 RetrievalSource[] |

- **代码**: [frontend/src/core/messages/utils.ts](../frontend/src/core/messages/utils.ts)

### Hidden message（隐藏消息）

部分消息标记为不展示给用户：
- `additional_kwargs.hide_from_ui === true` — 显式隐藏
- `name === "summary"` — 摘要消息
- `name === "loop_warning"` — 循环检测警告
- `name === "todo_reminder"` — Plan 模式提醒

- **代码**: [frontend/src/core/messages/utils.ts](../frontend/src/core/messages/utils.ts) `isHiddenFromUIMessage`

---

## 3. UI Block（动态 UI 区块）

### UIBlock

Agent 通过 `render_ui` 工具在对话中创建的动态 UI 组件。由后端通过 SSE 推送到前端，经折叠后渲染。

**核心字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `block_id` | string | 唯一标识 |
| `component` | string | 组件类型：chart、echart、table、card、form、confirm、code、timeline、markdown、layout、image |
| `action` | "create" / "update" / "delete" | 操作类型 |
| `props` | object | 组件属性 |
| `interactive` | boolean | 是否接受用户交互 |
| `callback_id` | string? | 交互路由标识（interactive=true 时必填） |
| `parent_id` | string? | 父 Block ID（嵌套在容器内时使用） |
| `sequence` | number? | 排序序号（越小越靠前） |
| `functional_interaction` | boolean? | 标记为功能交互，该 Block 在历史回合中保持可见 |

- **代码**: [frontend/src/core/genui/store.ts](../frontend/src/core/genui/store.ts)
- **后端**: [backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py](../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py)

### Folding（折叠）

将 create/update/delete 三种 action 的 Block 事件序列折叠为最终可见状态：
- **create** → 添加 Block
- **update** → 合并 props 到现有 Block（不改变其他字段）
- **delete** → 移除 Block

折叠逻辑目前存在于两处：前端 `store.ts:applyBlock`（直播流）和后端 `genui_persistence.py:_fold_blocks`（持久化存储）。

### Interaction（交互）

用户与 interactive Block 的交互（提交表单、点击确认等）。

**状态机**: `idle` → `loading` → `submitted` | `error` | `expired`

- `idle`: 初始状态
- `loading`: 正在提交交互到后端
- `submitted`: 提交成功，Block 不再可交互
- `error`: 提交失败，显示错误信息
- `expired`: 超过 `callback_timeout_ms`，交互超时
- `readonly`: 当 `disableExpiration=true` 且暂无交互状态时，显示为只读

**提交流程**: `submitInteraction()` → `POST /api/threads/{id}/ui-interaction`（带 CSRF token）→ 前端标记 submitted → 后端注入 HumanMessage 到 graph → agent 继续执行

- **代码**: [frontend/src/core/genui/interaction.ts](../frontend/src/core/genui/interaction.ts)
- **后端**: [backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py](../backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py)

### Standalone Block（顶层 Block）

没有 `parent_id` 的 Block，直接出现在聊天流中。所有可见性规则作用于 Standalone Block。

### Child Block（子 Block）

有 `parent_id` 的 Block，嵌套在 layout 或其他容器 Block 内部。只在父 Block 渲染子元素时才展示，不参与可见性计算。

### Block visibility（Block 可见性规则）

决定哪些 Standalone Block 显示在界面上的规则集：

1. **Superseded rule**: 同一 `callback_id` 有多个 interactive Block 时，只保留最新的
2. **Submitted rule**: 已提交的 interactive Block 不显示
3. **Functional interaction rule**: 带 `functional_interaction: true` 的 Block 在历史回合中保持可见
4. **Orphan rule**: 无流边界且无消息锚点的 interactive Block 不显示（孤立的交互 Block）
5. **Partition**: Block 分为两类——历史区（historical，上个回合之前的 Block）和当前回合区（tail，当前回合产生的 Block）

- **代码**: [frontend/src/core/genui/visibility.ts](../frontend/src/core/genui/visibility.ts)

### Block registry（Block 注册表）

将 component type 字符串映射到 React lazy 组件的注册表。支持 schema version 检查——大版本不匹配时降级到 markdown 渲染。

- **代码**: [frontend/src/core/genui/registry.ts](../frontend/src/core/genui/registry.ts)

### Block sanitizer（Block 属性清洗）

按组件类型白名单过滤 props key，递归 DOMPurify 清洗字符串值，过滤非法 form field 和 option。

- **代码**: [frontend/src/core/genui/sanitizer.ts](../frontend/src/core/genui/sanitizer.ts)

### Block validator（Block 属性校验）

用 Zod schema 按组件类型校验 props 结构（类型、范围、必填）。校验失败时渲染错误面板而非组件本身。

- **代码**: [frontend/src/core/genui/validator.ts](../frontend/src/core/genui/validator.ts)

### SSE recovery（SSE 恢复）

前端检测到 SSE 断连后，通过 `GET /api/threads/{id}/ui-blocks` 从后端恢复 Block 状态。使用指数退避重试（1s → 30s），只恢复前端 store 中不存在的 Block。

- **代码**: [frontend/src/core/genui/sse-recovery.ts](../frontend/src/core/genui/sse-recovery.ts)

### Checkpoint recovery（检查点恢复）

从 LangGraph checkpoint 消息中解析 `<!--ui_block:...-->` HTML 注释标记来重建历史 Block 状态。用于消息回放和页面刷新后的恢复。

- **代码**: [frontend/src/core/genui/history.ts](../frontend/src/core/genui/history.ts)

### Block ID dedup（Block ID 去重）

同一 `raw_block_id` 在多个历史回合中重复 create 时（例如每轮都重新渲染日报），通过 `{block_id}__{occurrence}` 后缀区分不同回合的实例。

- **代码**: [frontend/src/core/genui/history.ts](../frontend/src/core/genui/history.ts) `buildResolvedBlockHistory`

---

## 4. Artifact（产物）

### Artifact

Agent 在 sandbox 中生成并通过 `present_files` 工具暴露给用户的文件。存储于对话的 `user-data/outputs` 目录中。

两种加载方式：
- **HTTP**: `GET /api/threads/{id}/artifacts{filepath}`，用于已持久化的产物文件
- **Tool-call inline**: 解析 `write-file:<message_id>/<tool_call_id>` URL，直接从消息中的 tool_call args 读取内容（用于尚未持久化的最新产物）

对 `.skill` 文件自动追加 `/SKILL.md` 路径读取。

- **代码**: [frontend/src/core/artifacts/loader.ts](../frontend/src/core/artifacts/loader.ts)

---

## 5. Subtask（子任务）

### Subtask

Agent 通过 `task` 工具派发给子代理执行的工作单元。

| 字段 | 说明 |
|------|------|
| `id` | 子任务 ID |
| `subagent_type` | 子代理类型：`general-purpose` / `bash` |
| `status` | 状态：`in_progress` / `completed` / `failed` |
| `description` | 任务描述 |
| `prompt` | 给子代理的完整提示词 |
| `result` | 执行结果（完成时） |
| `error` | 错误信息（失败时） |
| `latestMessage` | 子代理的最新消息（流式更新） |

子任务状态通过 React Context (`SubtaskContext`) 管理，`useUpdateSubtask` 负责不可变更新——浅比较每个字段，无变化则跳过重渲染。

- **代码**: [frontend/src/core/tasks/types.ts](../frontend/src/core/tasks/types.ts)
- **Context**: [frontend/src/core/tasks/context.tsx](../frontend/src/core/tasks/context.tsx)

### Subagent（子代理）

在独立线程池中运行的 agent，由 lead agent 通过 `task` 工具调用派发。最大并发 3 个（`MAX_CONCURRENT_SUBAGENTS`），15 分钟超时。事件类型：`task_started`、`task_running`、`task_completed`、`task_failed`、`task_timed_out`。

- **后端**: `backend/packages/harness/deerflow/subagents/`

---

## 6. Upload（文件上传）

### Upload

用户上传文件到对话。后端用 `markitdown` 自动转换 PDF/PPT/Excel/Word 为 Markdown 文本。上传完成后文件存入对话隔离目录，agent 可通过 sandbox 虚拟路径访问。

### UploadedFileInfo

上传成功后的文件信息：
- `filename`、`size` — 基本信息
- `path`（物理路径）/ `virtual_path`（sandbox 中的虚拟路径） — 路径信息
- `artifact_url` — 产物 API 地址
- `markdown_file` / `markdown_virtual_path` / `markdown_artifact_url` — Markdown 转换结果（文档类文件）

### Optimistic upload（乐观上传）

上传流程的前端展示策略：
1. 用户点击发送 → 立即展示 `status: "uploading"` 的文件信息
2. 上传完成 → 更新为 `status: "uploaded"` 并附带路径
3. 上传失败 → 移除乐观消息，toast 报错

FileInMessage 是嵌入消息 `additional_kwargs.files` 中的文件元数据结构：`{ filename, size, path?, status? }`。

- **代码**: [frontend/src/core/uploads/api.ts](../frontend/src/core/uploads/api.ts)
- **乐观上传**: [frontend/src/core/threads/hooks.ts](../frontend/src/core/threads/hooks.ts) `sendMessage`

---

## 7. API & Config（基础设施）

### API Client

`getAPIClient()` 返回的 LangGraph SDK 单例（Client），按 tenant 缓存。自动行为：
- 注入 CSRF token（状态变更方法）
- 注入 tenant headers
- 过滤不支持的 stream mode

### Gateway API

非 LangGraph 的后端 REST API 调用（threads CRUD、uploads、artifacts、interaction 等），通过 `fetchGateway()` 发出。

### CSRF protection

状态变更方法（POST/PUT/DELETE/PATCH）自动从 cookie 读取 CSRF token 并注入 `X-CSRF-Token` header。

- **代码**: [frontend/src/core/api/](../frontend/src/core/api/)

---

## 概念关系图

```
对话 (Thread)
├── 消息 (Message) ──→ 消息组 (MessageGroup)
│   ├── 内嵌标签 → FileInMessage, RetrievalSource
│   ├── 推理内容 (Reasoning)
│   └── UIBlock 嵌入标记 (<!--ui_block:...-->)
├── UI Block ──→ 折叠 (Folding) → 可见性 (Visibility)
│   ├── 交互 (Interaction) → callback_id → 后端 InteractionStore
│   ├── 恢复 (SSE Recovery / Checkpoint Recovery)
│   └── 安全 (Sanitizer + Validator)
├── 产物 (Artifact) ──→ present_files 工具
├── 子任务 (Subtask) ──→ task 工具 → 子代理 (Subagent)
├── 上传 (Upload) ──→ 乐观上传 → FileInMessage
└── Stream（SSE 流）
    ├── values → title, artifacts, todos 更新
    ├── messages → 消息增量
    └── custom → UIBlock 事件、子任务事件、LLM 重试通知
```
