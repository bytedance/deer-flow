# DeerFlow 对话上下文设计报告

## 一、整体架构概览

DeerFlow 是一个基于 LangGraph 的 AI Agent 框架，它的对话系统分为**前端**（Next.js）、**后端网关**（FastAPI）、**LangGraph 运行时**三层。消息在这三者之间流转，形成了完整的对话上下文管理体系。

### 消息流转示意图

```
用户输入
    ↓
前端（React） ────── HTTP POST（发送消息）
    ↑                    ↓
    │               后端网关（FastAPI）
SSE 流式响应           ↓
    │         ┌──────────────┐
    │         │ LangGraph    │
    │         │ Agent Runtime │
    │         └──────────────┘
    ↑                    ↓
前端消息列表更新    返回 AI 回复
```

---

## 二、前端：消息如何展示和管理

### 2.1 消息的分组显示

前端使用 `getMessageGroups` 函数将消息分组，组类型有：

| 组类型 | 含义 |
|--------|------|
| `human` | 用户发送的消息 |
| `assistant` | AI 的最终回复 |
| `assistant:processing` | AI 正在思考或调用工具（流式处理中） |
| `assistant:present-files` | AI 呈现文件给用户 |
| `assistant:clarification` | AI 请求澄清 |
| `assistant:subagent` | AI 调用了子代理 |

```typescript
// 消息分组逻辑简化
if (message.type === "human") {
  groups.push({ type: "human", messages: [message] });
} else if (message.type === "ai") {
  if (hasPresentFiles(message)) {
    groups.push({ type: "assistant:present-files" });
  } else if (hasToolCalls(message)) {
    groups.push({ type: "assistant:processing" });
  }
  if (hasContent(message)) {
    groups.push({ type: "assistant" }); // 最终回复
  }
}
```

### 2.2 消息去重与合并

前端通过 `mergeMessages` 函数合并多来源消息：

1. **历史消息**（从后端加载的）
2. **线程消息**（当前对话中的）
3. **乐观消息**（用户刚发送但还未收到确认的）

合并时会去重，通过 `messageIdentity` 识别每条消息：
- tool message 用 `tool_call_id`
- 普通 message 用 `message.id`

---

## 三、后端：LangGraph 如何管理上下文

### 3.1 ThreadState — 对话状态的中心

每个线程（Thread）维护一个 `ThreadState`，其中最核心的是 `messages` 列表：

```python
class ThreadState(AgentState):
    messages: list[BaseMessage]  # 对话消息历史
    thread_data: ThreadDataState  # 线程数据目录信息
    # ... 其他字段
```

### 3.2 中间件链 — 18个拦截器

LangGraph 的 Lead Agent 执行时，会依次经过 18 个中间件，每个中间件负责不同的职责：

**关键中间件的作用：**

| 中间件 | 职责 |
|--------|------|
| `ThreadDataMiddleware` | 创建线程数据目录（workspace/uploads/outputs） |
| `UploadsMiddleware` | 将上传文件注入上下文 |
| `SandboxMiddleware` | 获取沙箱执行环境 |
| `MemoryMiddleware` | **对话结束后排队更新长期记忆** |
| `SummarizationMiddleware` | 当 token 超限时压缩上下文 |
| `TitleMiddleware` | 自动生成对话标题 |
| `ViewImageMiddleware` | 为视觉模型注入图片数据 |
| `ClarificationMiddleware` | 拦截澄清请求（必须最后执行） |

---

## 四、短期记忆 vs 长期记忆

这是理解 DeerFlow 上下文设计的核心。

### 4.1 短期记忆 — 对话消息（Messages）

**定义**：当前对话轮次中的消息历史，存在 `ThreadState.messages` 中。

**生命周期**：
- 随对话进行实时增长
- 每个用户消息 + AI 回复构成一轮
- 当 token 接近上限时，`SummarizationMiddleware` 会压缩历史

**工作原理**：
1. 用户发送消息 → 存入 `ThreadState.messages`
2. AI 响应 → 也存入 `ThreadState.messages`
3. 每轮对话结束后，`MemoryMiddleware` 检测是否有值得记住的内容

### 4.2 长期记忆 — UserMemory

**定义**：跨对话持久化的用户记忆，存储在 `memory.json` 文件中。

**结构**：分为 6 个区域 + Facts 列表

```
UserMemory
├── user（用户上下文）
│   ├── workContext      # 工作相关
│   ├── personalContext  # 个人相关
│   └── topOfMind        # 当前最关心的
├── history（历史背景）
│   ├── recentMonths       # 最近几个月
│   ├── earlierContext     # 更早的上下文
│   └── longTermBackground # 长期背景
└── facts（具体事实列表）
    ├── id
    ├── content（内容）
    ├── category（分类）
    ├── confidence（置信度）
    └── createdAt / source
```

### 4.3 记忆如何更新

```
对话结束
    ↓
MemoryMiddleware.after_agent() 被调用
    ↓
过滤消息（只保留 user 输入 + AI 最终回复）
    ↓
检测 correction（纠正）或 reinforcement（强化）
    ↓
加入 MemoryUpdateQueue（带防抖，默认30秒）
    ↓
异步调用 LLM 总结 → 更新 memory.json
```

### 4.4 记忆如何注入

当新的对话开始时，`MemoryMiddleware` 会：

1. 读取用户的 `UserMemory`
2. 将记忆内容格式化成文本片段
3. 注入到 System Prompt 中（最多 2000 tokens）
4. AI 在回答时可以参考这些记忆

---

## 五、消息流转的完整生命周期

### 5.1 发送消息

```
用户在前端输入文字
    ↓
前端调用 /api/threads/{thread_id}/messages（HTTP POST）
    ↓
后端网关接收请求
    ↓
调用 LangGraph 的 agent runtime
    ↓
消息被添加到 ThreadState.messages
    ↓
LangGraph 执行 Agent 逻辑（经过 18 个中间件）
```

### 5.2 接收响应（流式）

```
LangGraph 执行中...
    ↓
通过 SSE（Server-Sent Events）流式返回
    ↓
前端用 Streamdown 组件解析流数据
    ↓
实时更新 UI（打字机效果）
    ↓
消息状态从 "processing" 变为 "assistant"
```

### 5.3 消息持久化

```
对话完成后
    ↓
ThreadState.messages 持久化到数据库
    ↓
MemoryMiddleware 检测到对话结束
    ↓
将对话内容加入记忆更新队列
    ↓
异步处理：LLM 总结 → 更新 memory.json
```

---

## 六、存储结构

### 6.1 线程数据目录

每个线程有一个独立的目录：

```
.deer-flow/
└── threads/
    └── {thread_id}/
        └── user-data/
            ├── workspace/   # 工作区文件
            ├── uploads/     # 用户上传的文件
            └── outputs/     # AI 生成的输出
```

### 6.2 长期记忆文件

默认存储在 `{base_dir}/users/{user_id}/memory.json`

也可以配置为全局共享路径（所有用户共用）。

---

## 七、总结

| 维度 | 短期记忆 | 长期记忆 |
|------|----------|----------|
| **存储位置** | ThreadState.messages | memory.json |
| **生命周期** | 单次对话 | 跨对话持久化 |
| **更新方式** | 实时添加 | 对话结束后异步总结 |
| **用途** | 当前对话的上下文 | 跨对话的个性化信息 |
| **管理组件** | LangGraph State | MemoryMiddleware |

**核心流程**：用户消息 → 前端 → 后端 LangGraph → 响应 + 更新记忆 → 前端展示