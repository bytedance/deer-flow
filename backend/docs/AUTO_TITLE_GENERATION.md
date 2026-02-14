# 自动 Thread Title 生成功能

## 功能说明

自动为对话线程生成标题，在用户首次提问并收到回复后自动触发。

## 实现方式

使用 `TitleMiddleware` 在 `after_agent` 钩子中：
1. 检测是否是首次对话（1个用户消息 + 1个助手回复）
2. 检查 state 是否已有 title
3. 调用 LLM 生成简洁的标题（默认最多6个词）
4. 将 title 存储到 `ThreadState` 中（会被 checkpointer 持久化）

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
    "lead_agent": "src.agents:lead_agent"
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
  model_name: null  # 使用默认模型
```

或在代码中配置：

```python
from src.config.title_config import TitleConfig, set_title_config

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
    participant LLM
    participant Checkpointer

    User->>Client: 发送首条消息
    Client->>LangGraph: POST /threads/{id}/runs
    LangGraph->>Agent: 处理消息
    Agent-->>LangGraph: 返回回复
    LangGraph->>TitleMiddleware: after_agent()
    TitleMiddleware->>TitleMiddleware: 检查是否需要生成 title
    TitleMiddleware->>LLM: 生成 title
    LLM-->>TitleMiddleware: 返回 title
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
2. **性能考虑**：title 生成会增加约 0.5-1 秒延迟，可通过使用更快的模型优化
3. **并发安全**：middleware 在 agent 执行后运行，不会阻塞主流程
4. **Fallback 策略**：如果 LLM 调用失败，会使用用户消息的前几个词作为 title

## 测试

```python
# 测试 title 生成
import pytest
from src.agents.title_middleware import TitleMiddleware

def test_title_generation():
    # TODO: 添加单元测试
    pass
```

## 故障排查

### Title 没有生成

1. 检查配置是否启用：`get_title_config().enabled == True`
2. 检查日志：查找 "Generated thread title" 或错误信息
3. 确认是首次对话：只有 1 个用户消息和 1 个助手回复时才会触发

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
def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
    """Generate and set thread title after the first agent response."""
    if self._should_generate_title(state, runtime):
        title = self._generate_title(runtime)
        print(f"Generated thread title: {title}")
        
        # ✅ 返回 state 更新，会被 checkpointer 自动持久化
        return {"title": title}
    
    return None
```

## 相关文件

- [`src/agents/thread_state.py`](../src/agents/thread_state.py) - ThreadState 定义
- [`src/agents/title_middleware.py`](../src/agents/title_middleware.py) - TitleMiddleware 实现
- [`src/config/title_config.py`](../src/config/title_config.py) - 配置管理
- [`config.yaml`](../config.yaml) - 配置文件
- [`src/agents/lead_agent/agent.py`](../src/agents/lead_agent/agent.py) - Middleware 注册

## 参考资料

- [LangGraph Checkpointer 文档](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph State 管理](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [LangGraph Middleware](https://langchain-ai.github.io/langgraph/concepts/middleware/)
