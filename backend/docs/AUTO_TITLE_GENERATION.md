# 自动Thread标题生成功能

## 功能说明

自动为对话线程生成标题，在用户首次提问并收到回复后自动触发。

## 实现方式

使用`TitleMiddleware`在`after_model`钩子中：
1. 检测是否是首次对话（1个用户消息 + 1个助手回复）
2. 检查state是否已有title
3. 调用LLM生成简洁的标题（默认最多6个词）
4. 将title存储到`ThreadState`中（会被checkpointer持久化）

TitleMiddleware会先把LangChain message content里的结构化block/list内容归一化为纯文本，再拼到title prompt里，避免把Python/JSON的原始repr泄漏到标题生成模型。

## ⚠️ 重要：存储机制

### Title存储位置

Title存储在**`ThreadState.title`**中，而非thread metadata：

```python
class ThreadState(AgentState):
    sandbox: SandboxState | None = None
    title: str | None = None  # ✅ Title存储在这里
```

### 持久化说明

| 部署方式 | 持久化 | 说明 |
|---------|--------|------|
| **LangGraph Studio (本地)** | ❌ 否 | 仅内存存储，重启后丢失 |
| **LangGraph Platform** | ✅ 是 | 自动持久化到数据库 |
| **自定义 + Checkpointer** | ✅ 是 | 需配置PostgreSQL/SQLite checkpointer |

### 如何启用持久化

如果需要在本地开发时也持久化title，需要配置checkpointer：

```python
# 在langgraph.json同级目录创建checkpointer.py
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost/dbname"
)
```

然后在`langgraph.json`中引用：

```json
{
  "graphs": {
    "lead_agent": "deerflow.agents:lead_agent"
  },
  "checkpointer": "checkpointer:checkpointer"
}
```

## 配置

在`config.yaml`中添加（可选）：

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # 使用默认模型
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

### 获取Thread Title

```typescript
// 方式1: 从thread state获取
const state = await client.threads.getState(threadId);
const title = state.values.title || "New Conversation";

// 方式2: 监听stream事件
for await (const chunk of client.runs.stream(threadId, assistantId, {
  input: { messages: [{ role: "user", content: "Hello" }] }
})) {
  if (chunk.event === "values" && chunk.data.title) {
    console.log("Title:", chunk.data.title);
  }
}
```

### 显示Title

```typescript
// 在对话列表中显示
function ConversationList() {
  const [threads, setThreads] = useState([]);

  useEffect(() => {
    async function loadThreads() {
      const allThreads = await client.threads.list();

      // 获取每个thread的state来读取title
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
    participant LLM
    participant Checkpointer

    User->>Client: 发送首条消息
    Client->>LangGraph: POST /threads/{id}/runs
    LangGraph->>Agent: 处理消息
    Agent-->>LangGraph: 返回回复
    LangGraph->>TitleMiddleware: after_agent()
    TitleMiddleware->>TitleMiddleware: 检查是否需要生成title
    TitleMiddleware->>LLM: 生成title
    LLM-->>TitleMiddleware: 返回title
    TitleMiddleware->>LangGraph: return {"title": "..."}
    LangGraph->>Checkpointer: 保存state(含title)
    LangGraph-->>Client: 返回响应
    Client->>Client: 从state.values.title读取
```

## 优势

✅ **可靠持久化** - 使用LangGraph的state机制，自动持久化
✅ **完全后端处理** - 客户端无需额外逻辑
✅ **自动触发** - 首次对话后自动生成
✅ **可配置** - 支持自定义长度、模型等
✅ **容错性强** - 失败时使用fallback策略
✅ **架构一致** - 与现有SandboxMiddleware保持一致

## 注意事项

1. **读取方式不同**：Title在`state.values.title`而非`thread.metadata.title`
2. **性能考虑**：title生成会增加约0.5-1秒延迟，可通过使用更快的模型优化
3. **并发安全**：middleware在agent执行后运行，不会阻塞主流程
4. **Fallback策略**：如果LLM调用失败，会使用用户消息的前几个词作为title

## 测试

```python
# 测试title生成
import pytest
from deerflow.agents.title_middleware import TitleMiddleware

def test_title_generation():
    # TODO: 添加单元测试
    pass
```

## 故障排除

### Title没有生成

1. 检查配置是否启用：`get_title_config().enabled == True`
2. 检查日志：查找"Generated thread title"或错误信息
3. 确认是首次对话：只有1个用户消息和1个助手回复时才会触发

### Title生成但客户端看不到

1. 确认读取位置：应该从`state.values.title`读取，而非`thread.metadata.title`
2. 检查API响应：确认state中包含title字段
3. 尝试重新获取state：`client.threads.getState(threadId)`

### Title重启后丢失

1. 检查是否配置了checkpointer（本地开发需要）
2. 确认部署方式：LangGraph Platform会自动持久化
3. 查看数据库：确认checkpointer正常工作

## 架构设计

### 为什么使用State而非Metadata？

| 特性 | State | Metadata |
|------|-------|----------|
| **持久化** | ✅ 自动（通过checkpointer） | ⚠️ 取决于实现 |
| **版本控制** | ✅ 支持时间旅行 | ❌ 不支持 |
| **类型安全** | ✅ TypedDict定义 | ❌ 任意字典 |
| **可追溯** | ✅ 每次更新都记录 | ⚠️ 只有最新值 |
| **标准化** | ✅ LangGraph核心机制 | ⚠️ 扩展功能 |

### 实现细节

```python
# TitleMiddleware核心逻辑
@override
def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
    """在首次代理响应后生成并设置线程标题"""
    if self._should_generate_title(state, runtime):
        title = self._generate_title(runtime)
        print(f"Generated thread title: {title}")

        # ✅ 返回state更新，会被checkpointer自动持久化
        return {"title": title}

    return None
```

## 相关文件

- [`packages/harness/deerflow/agents/thread_state.py`](../packages/harness/deerflow/agents/thread_state.py) - ThreadState定义
- [`packages/harness/deerflow/agents/middlewares/title_middleware.py`](../packages/harness/deerflow/agents/middlewares/title_middleware.py) - TitleMiddleware实现
- [`packages/harness/deerflow/config/title_config.py`](../packages/harness/deerflow/config/title_config.py) - 配置管理
- [`config.yaml`](../config.yaml) - 配置文件
- [`packages/harness/deerflow/agents/lead_agent/agent.py`](../packages/harness/deerflow/agents/lead_agent/agent.py) - Middleware注册

## 参考资料

- [LangGraph Checkpointer文档](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph State管理](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [LangGraph Middleware](https://langchain-ai.github.io/langgraph/concepts/middleware/)
