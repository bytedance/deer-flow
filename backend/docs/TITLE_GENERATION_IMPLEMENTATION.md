# 自动 Title 生成功能实现总结

## ✅ 已完成的工作

### 1. 核心实现文件

#### [`packages/harness/deerflow/agents/thread_state.py`](../packages/harness/deerflow/agents/thread_state.py)
- ✅ 添加 `title: str | None = None` 字段到 `ThreadState`

#### [`packages/harness/deerflow/config/title_config.py`](../packages/harness/deerflow/config/title_config.py) (新建)
- ✅ 创建 `TitleConfig` 配置类
- ✅ 支持配置：enabled, max_words, max_chars, model_name, prompt_template
- ✅ 提供 `get_title_config()` 和 `set_title_config()` 函数
- ✅ 提供 `load_title_config_from_dict()` 从配置文件加载

#### [`packages/harness/deerflow/agents/middlewares/title_middleware.py`](../packages/harness/deerflow/agents/middlewares/title_middleware.py) (新建)
- ✅ 创建 `TitleMiddleware` 类
- ✅ 实现 `_should_generate_title()` 检查是否需要生成
- ✅ 默认使用本地 fallback 生成标题，避免流式回复结束前等待额外 LLM 调用；显式配置 `model_name` 时可使用 LLM 标题
- ✅ 实现 `after_model()` / `aafter_model()` 钩子，在首次对话后自动触发
- ✅ 包含 fallback 策略（LLM 未配置或失败时使用用户消息前几个字符）

#### [`packages/harness/deerflow/config/app_config.py`](../packages/harness/deerflow/config/app_config.py)
- ✅ 导入 `load_title_config_from_dict`
- ✅ 在 `from_file()` 中加载 title 配置

#### [`packages/harness/deerflow/agents/lead_agent/agent.py`](../packages/harness/deerflow/agents/lead_agent/agent.py)
- ✅ 导入 `TitleMiddleware`
- ✅ 注册到 `middleware` 列表：`[SandboxMiddleware(), TitleMiddleware()]`

### 2. 配置文件

#### [`config.yaml`](../../config.example.yaml)
- ✅ 添加 title 配置段：
```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # null = 快速本地 fallback；填模型名才启用 LLM 标题
```

### 3. 文档

#### [`docs/AUTO_TITLE_GENERATION.md`](../docs/AUTO_TITLE_GENERATION.md) (新建)
- ✅ 完整的功能说明文档
- ✅ 实现方式和架构设计
- ✅ 配置说明
- ✅ 客户端使用示例（TypeScript）
- ✅ 工作流程图（Mermaid）
- ✅ 故障排查指南
- ✅ State vs Metadata 对比

#### [`TODO.md`](TODO.md)
- ✅ 添加功能完成记录

### 4. 测试

#### [`tests/test_title_generation.py`](../tests/test_title_generation.py) (新建)
- ✅ 配置类测试
- ✅ Middleware 初始化测试
- ✅ TODO: 集成测试（需要 mock Runtime）

---

## 🎯 核心设计决策

### 为什么使用 State 而非 Metadata？

| 方面 | State (✅ 采用) | Metadata (❌ 未采用) |
|------|----------------|---------------------|
| **持久化** | 自动（通过 checkpointer） | 取决于实现，不可靠 |
| **版本控制** | 支持时间旅行 | 不支持 |
| **类型安全** | TypedDict 定义 | 任意字典 |
| **标准化** | LangGraph 核心机制 | 扩展功能 |

### 工作流程

```
用户发送首条消息
  ↓
Agent 处理并返回回复
  ↓
TitleMiddleware.after_model()/aafter_model() 触发
  ↓
检查：是否首次对话？是否已有 title？
  ↓
默认从首条用户消息生成本地 fallback title
  ↓
如果显式配置 title.model_name，才调用 LLM 生成更精炼的 title
  ↓
返回 {"title": "..."} 更新 state
  ↓
Checkpointer 自动持久化（如果配置了）
  ↓
客户端从 state.values.title 读取
```

---

## 📋 使用指南

### 后端配置

1. **启用/禁用功能**
```yaml
# config.yaml
title:
  enabled: true  # 设为 false 禁用
```

2. **自定义配置**
```yaml
title:
  enabled: true
  max_words: 8      # 标题最多 8 个词
  max_chars: 80     # 标题最多 80 个字符
  model_name: null  # null = 快速本地 fallback；填模型名才启用 LLM 标题
```

3. **配置持久化（可选）**

如果需要在本地开发时持久化 title：

```python
# checkpointer.py
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("deerflow.db")
```

```json
// langgraph.json
{
  "graphs": {
    "lead_agent": "deerflow.agents:lead_agent"
  },
  "checkpointer": "checkpointer:checkpointer"
}
```

### 客户端使用

```typescript
// 获取 thread title
const state = await client.threads.getState(threadId);
const title = state.values.title || "New Conversation";

// 显示在对话列表
<li>{title}</li>
```

**⚠️ 注意**：Title 在 `state.values.title`，而非 `thread.metadata.title`

---

## 🧪 测试

```bash
# 运行测试
pytest tests/test_title_generation.py -v

# 运行所有测试
pytest
```

---

## 🔍 故障排查

### Title 没有生成？

1. 检查配置：`title.enabled = true`
2. 确认是首次对话（1 个用户消息 + 1 个助手回复）
3. 如果显式配置了 `title.model_name`，检查标题模型是否可用；未配置时会走本地 fallback

### Title 生成但看不到？

1. 确认读取位置：`state.values.title`（不是 `thread.metadata.title`）
2. 检查 API 响应是否包含 title
3. 重新获取 state

### Title 重启后丢失？

1. 本地开发需要配置 checkpointer
2. LangGraph Platform 会自动持久化
3. 检查数据库确认 checkpointer 工作正常

### 中断首轮后仍显示默认标题？

1. `runtime/runs/worker.py` 会在 interrupted-run cleanup 中保持 run 处于 finalizing 状态，避免同线程新 run 在 fallback title 写入期间覆盖 checkpoint
2. 如果取消发生在可用 checkpoint 写入前，worker 会使用本次 `graph_input` 中的首条用户消息生成本地 fallback title
3. fallback title 写入前会重新读取 latest checkpoint；如果同线程状态已经前进，只对最新 snapshot 做 title-only 更新，避免旧消息重新成为 latest

---

## 📊 性能影响

- **默认延迟**：默认 `title.model_name: null` 不会发起额外 LLM 调用，仅从首条用户消息生成本地 fallback title
- **显式 LLM 标题延迟**：只有配置 `title.model_name` 时，首轮回复后才会等待一次标题模型调用
- **并发安全**：在 `after_model()` / `aafter_model()` 中更新 state，不需要客户端额外请求
- **资源消耗**：每个 thread 只生成一次

### 优化建议

1. 默认保持 `model_name: null`，避免流式回复结束前的额外 LLM 等待
2. 如需更精炼标题，再显式配置较快的标题模型
3. 减少 `max_words` 和 `max_chars`，并让 prompt 保持简洁

---

## 🚀 下一步

- [ ] 补充 prompt template 的集成测试
- [ ] 支持多语言 title 生成
- [ ] 添加 title 重新生成功能
- [ ] 监控 title 生成成功率和延迟

---

## 📚 相关资源

- [完整文档](../docs/AUTO_TITLE_GENERATION.md)
- [LangGraph Middleware](https://langchain-ai.github.io/langgraph/concepts/middleware/)
- [LangGraph State 管理](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [LangGraph Checkpointer](https://langchain-ai.github.io/langgraph/concepts/persistence/)

---

*实现完成时间: 2026-01-14*
