# 自动 Thread Title 生成功能

## 功能说明

自动为对话线程生成标题，在用户首次提问并收到回复后自动触发。

## 实现方式

使用 `TitleMiddleware` 在 `after_model` 钩子中：
1. 检测是否是首次对话（1个用户消息 + 1个助手回复）
2. 检查 state 是否已有 title
3. 默认从首条用户消息生成本地 fallback 标题，避免在流式回复结束前额外等待一次 LLM 调用；显式配置 `model_name` 时才调用 LLM 生成标题（默认最多6个词）
4. 将 title 存储到 `ThreadState` 中（会被 checkpointer 持久化）

TitleMiddleware 会先把 LangChain message content 里的结构化 block/list 内容归一化为纯文本，再拼到 title prompt 里，避免把 Python/JSON 的原始 repr 泄漏到标题生成模型。

## ⚠️ 重要：存储机制

### Title 存储位置

Title 存储在 **`ThreadState.title`** 中，而非 thread metadata：

```python
class ThreadState(AgentState):
    sandbox: SandboxState | None = None
    title: str | None = None  # ✅ Title stored here
```

### 持久化说明

| 部署方式 | 持久化 | 说明 |
|---------|--------|------|
| **LangGraph Studio (本地)** | ❌ 否 | 仅内存存储，重启后丢失 |
| **LangGraph Platform** | ✅ 是 | 自动持久化到数据库 |
| **自定义 + Checkpointer** | ✅ 是 | 需配置 PostgreSQL/SQLite checkpointer |

### 如何启用持久化

如果需要在本地开发时也持久化 title，需要配置 checkpointer：

```python
# 在 langgraph.json 同级目录创建 checkpointer.py
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost/dbname"
)
```

然后在 `langgraph.json` 中引用：

```json
{
  "graphs": {
    "lead_agent": "deerflow.agents:lead_agent"
  },
  "checkpointer": "checkpointer:checkpointer"
}
```

## 配置

在 `config.yaml` 中添加（可选）：

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # null = 快速本地 fallback；填模型名才启用 LLM 标题
```

或在代码中配置：

```python
from deerflow.config.title_config import TitleConfig, set_title_config

set_title_config(TitleConfig(
    enabled=True,
    max_words=8,
    max_chars=80,
))
```

## 客户端使用

### 获取 Thread Title

```typescript
// 方式1: 从 thread state 获取
const state = await client.threads.getState(threadId);
const title = state.values.title || "New Conversation";

// 方式2: 监听 stream 事件
for await (const chunk of client.runs.stream(threadId, assistantId, {
  input: { messages: [{ role: "user", content: "Hello" }] }
})) {
  if (chunk.event === "values" && chunk.data.title) {
    console.log("Title:", chunk.data.title);
  }
}
```

### 显示 Title

```typescript
// 在对话列表中显示
function ConversationList() {
  const [threads, setThreads] = useState([]);

  useEffect(() => {
    async function loadThreads() {
      const allThreads = await client.threads.list();
      
      // 获取每个 thread 的 state 来读取 title
      const threadsWithTitles = await Promise.all(
        allThreads.map(async (t) => {
          const state = await client.threads.getState(t.thread_id);
          return {
            id: t.thread_id,
            title: state.values.title || "New Conversation",
            updatedAt: t.updated_at,
          };
        })
      );
      
      setThreads(threadsWithTitles);
    }
    loadThreads();
  }, []);

  return (
    <ul>
      {threads.map(thread => (
        <li key={thread.id}>
          <a href={`/chat/${thread.id}`}>{thread.title}</a>
        </li>
      ))}
    </ul>
  );
}
```

## 工作流程

```mermaid
sequenceDiagram
    participant User
    participant Client
    participant LangGraph
    participant TitleMiddleware
    participant TitleModel as Title model (optional)
    participant Checkpointer

    User->>Client: 发送首条消息
    Client->>LangGraph: POST /threads/{id}/runs
    LangGraph->>Agent: 处理消息
    Agent-->>LangGraph: 返回回复
    LangGraph->>TitleMiddleware: after_model()/aafter_model()
    TitleMiddleware->>TitleMiddleware: 检查是否需要生成 title
    alt title.model_name 为空（默认）
        TitleMiddleware->>TitleMiddleware: 从首条用户消息生成本地 fallback title
    else 显式配置 title.model_name
        TitleMiddleware->>TitleModel: 生成 LLM title
        TitleModel-->>TitleMiddleware: 返回 title
    end
    TitleMiddleware->>LangGraph: return {"title": "..."}
    LangGraph->>Checkpointer: 保存 state (含 title)
    LangGraph-->>Client: 返回响应
    Client->>Client: 从 state.values.title 读取
```

## 优势

✅ **可靠持久化** - 使用 LangGraph 的 state 机制，自动持久化  
✅ **完全后端处理** - 客户端无需额外逻辑  
✅ **自动触发** - 首次对话后自动生成  
✅ **可配置** - 支持自定义长度、模型等  
✅ **容错性强** - 失败时使用 fallback 策略  
✅ **架构一致** - 与现有 SandboxMiddleware 保持一致  

## 注意事项

1. **读取方式不同**：Title 在 `state.values.title` 而非 `thread.metadata.title`
2. **性能考虑**：默认配置不调用标题模型；只有显式配置 `title.model_name` 时，才会在首轮回复后额外等待一次 LLM title 生成
3. **并发安全**：middleware 在 agent 首次完整回复后更新 state，不需要客户端额外请求
4. **Fallback 策略**：默认使用用户消息前几个字符作为 title；如果显式启用的 LLM 调用失败，也会回退到该策略

## 测试

```bash
cd backend
uv run pytest tests/test_title_middleware_core_logic.py tests/test_title_generation.py
```

## 故障排查

### Title 没有生成

1. 检查配置是否启用：`get_title_config().enabled == True`
2. 确认是首次对话：只有 1 个用户消息和 1 个助手回复时才会触发
3. 如果显式配置了 `title.model_name`，检查标题模型是否可用；未配置时会走本地 fallback

### Title 生成但客户端看不到

1. 确认读取位置：应该从 `state.values.title` 读取，而非 `thread.metadata.title`
2. 检查 API 响应：确认 state 中包含 title 字段
3. 尝试重新获取 state：`client.threads.getState(threadId)`

### Title 重启后丢失

1. 检查是否配置了 checkpointer（本地开发需要）
2. 确认部署方式：LangGraph Platform 会自动持久化
3. 查看数据库：确认 checkpointer 正常工作

## 架构设计

### 为什么使用 State 而非 Metadata？

| 特性 | State | Metadata |
|------|-------|----------|
| **持久化** | ✅ 自动（通过 checkpointer） | ⚠️ 取决于实现 |
| **版本控制** | ✅ 支持时间旅行 | ❌ 不支持 |
| **类型安全** | ✅ TypedDict 定义 | ❌ 任意字典 |
| **可追溯** | ✅ 每次更新都记录 | ⚠️ 只有最新值 |
| **标准化** | ✅ LangGraph 核心机制 | ⚠️ 扩展功能 |

### 实现细节

```python
# TitleMiddleware 核心逻辑
@override
async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
    return await self._agenerate_title_result(state)

async def _agenerate_title_result(self, state: TitleMiddlewareState) -> dict | None:
    if not self._should_generate_title(state):
        return None

    config = self._get_title_config()
    if not config.model_name:
        return self._generate_title_result(state)

    # 显式配置 title.model_name 时才调用标题模型；失败会回退到本地 title。
    ...
```

## 相关文件

- [`packages/harness/deerflow/agents/thread_state.py`](../packages/harness/deerflow/agents/thread_state.py) - ThreadState 定义
- [`packages/harness/deerflow/agents/middlewares/title_middleware.py`](../packages/harness/deerflow/agents/middlewares/title_middleware.py) - TitleMiddleware 实现
- [`packages/harness/deerflow/config/title_config.py`](../packages/harness/deerflow/config/title_config.py) - 配置管理
- [`config.yaml`](../../config.example.yaml) - 配置文件
- [`packages/harness/deerflow/agents/lead_agent/agent.py`](../packages/harness/deerflow/agents/lead_agent/agent.py) - Middleware 注册

## 参考资料

- [LangGraph Checkpointer 文档](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph State 管理](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [LangGraph Middleware](https://langchain-ai.github.io/langgraph/concepts/middleware/)
