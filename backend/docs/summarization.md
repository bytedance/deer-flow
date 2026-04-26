# 对话摘要功能

===================
设计思路说明
===================

**为什么需要对话摘要**：
1. **突破Token限制**：长对话会超过模型的上下文窗口限制
2. **保持上下文连续性**：压缩旧消息同时保留关键信息
3. **降低成本**：减少每次请求的token数量
4. **提升响应速度**：更短的上下文意味着更快的推理

**核心设计原则**：
- **自动化**：无需手动干预，系统自动触发摘要
- **智能保留**：保留最近的完整对话，压缩历史消息
- **可配置**：灵活的触发和保留策略
- **上下文保护**：确保AI/Tool消息对不被分离

DeerFlow包含自动对话摘要功能，用于处理接近模型token限制的长对话。启用后，系统会自动压缩旧消息，同时保留最近的上下文。

## 功能概述

摘要功能使用LangChain的`SummarizationMiddleware`来监控对话历史，并根据可配置的阈值触发摘要。激活时，它会：

1. **实时监控**消息历史中的token计数
2. **触发摘要**：当满足配置的阈值时
3. **保留最近消息**：保持最近的对话完整
4. **维护AI/Tool消息对**：确保上下文连续性
5. **注入摘要**：将生成的摘要添加回对话

**为什么这样设计摘要流程**：
- **实时监控**：每次模型调用前检查，确保及时摘要
- **智能分区**：将消息分为需要摘要和需要保留两部分
- **上下文保护**：AI消息和对应的Tool消息保持在一起
- **无缝集成**：摘要作为普通消息注入，对上层透明

## 配置说明

摘要功能在`config.yaml`中的`summarization`键下配置：

```yaml
summarization:
  enabled: true
  model_name: null  # 使用默认模型或指定轻量级模型

  # 触发条件（OR逻辑 - 任一条件触发摘要）
  trigger:
    - type: tokens
      value: 4000
    # 附加触发器（可选）
    # - type: messages
    #   value: 50
    # - type: fraction
    #   value: 0.8  # 模型最大输入token的80%

  # 上下文保留策略
  keep:
    type: messages
    value: 20

  # 摘要调用的token修剪
  trim_tokens_to_summarize: 4000

  # 自定义摘要提示词（可选）
  summary_prompt: null
```

**为什么这样设计配置结构**：
- **灵活性**：支持多种触发条件组合
- **可控性**：精确控制何时摘要以及保留多少上下文
- **成本优化**：可使用更便宜的模型生成摘要
- **可扩展性**：预留自定义提示词接口

### 配置选项详解

#### `enabled`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable or disable automatic summarization

#### `model_name`
- **Type**: String or null
- **Default**: `null` (uses default model)
- **Description**: Model to use for generating summaries. Recommended to use a lightweight, cost-effective model like `gpt-4o-mini` or equivalent.

#### `trigger`
- **Type**: Single `ContextSize` or list of `ContextSize` objects
- **Required**: At least one trigger must be specified when enabled
- **Description**: Thresholds that trigger summarization. Uses OR logic - summarization runs when ANY threshold is met.

**ContextSize Types:**

1. **Token-based trigger**: Activates when token count reaches the specified value
   ```yaml
   trigger:
     type: tokens
     value: 4000
   ```

2. **Message-based trigger**: Activates when message count reaches the specified value
   ```yaml
   trigger:
     type: messages
     value: 50
   ```

3. **Fraction-based trigger**: Activates when token usage reaches a percentage of the model's maximum input tokens
   ```yaml
   trigger:
     type: fraction
     value: 0.8  # 80% of max input tokens
   ```

**Multiple Triggers:**
```yaml
trigger:
  - type: tokens
    value: 4000
  - type: messages
    value: 50
```

#### `keep`
- **Type**: `ContextSize` object
- **Default**: `{type: messages, value: 20}`
- **Description**: Specifies how much recent conversation history to preserve after summarization.

**Examples:**
```yaml
# Keep most recent 20 messages
keep:
  type: messages
  value: 20

# Keep most recent 3000 tokens
keep:
  type: tokens
  value: 3000

# Keep most recent 30% of model's max input tokens
keep:
  type: fraction
  value: 0.3
```

#### `trim_tokens_to_summarize`
- **Type**: Integer or null
- **Default**: `4000`
- **Description**: Maximum tokens to include when preparing messages for the summarization call itself. Set to `null` to skip trimming (not recommended for very long conversations).

#### `summary_prompt`
- **Type**: String or null
- **Default**: `null` (uses LangChain's default prompt)
- **Description**: Custom prompt template for generating summaries. The prompt should guide the model to extract the most important context.

**默认提示词行为**：
LangChain的默认提示词指导模型：
- 提取最高质量/最相关的上下文
- 专注于对整体目标关键的信息
- 避免重复已完成的操作
- 仅返回提取的上下文

**为什么使用这些指导原则**：
- **质量优先**：确保摘要包含最重要的信息
- **目标导向**：保留与任务目标相关的上下文
- **避免冗余**：不重复已完成操作的细节
- **简洁输出**：直接返回摘要，无额外内容

## 工作原理

### 摘要流程

1. **Monitoring**: Before each model call, the middleware counts tokens in the message history
2. **Trigger Check**: If any configured threshold is met, summarization is triggered
3. **Message Partitioning**: Messages are split into:
   - Messages to summarize (older messages beyond the `keep` threshold)
   - Messages to preserve (recent messages within the `keep` threshold)
4. **Summary Generation**: The model generates a concise summary of the older messages
5. **Context Replacement**: The message history is updated:
   - All old messages are removed
   - A single summary message is added
   - Recent messages are preserved
6. **AI/Tool Pair Protection**: The system ensures AI messages and their corresponding tool messages stay together

### Token Counting

- Uses approximate token counting based on character count
- For Anthropic models: ~3.3 characters per token
- For other models: Uses LangChain's default estimation
- Can be customized with a custom `token_counter` function

### Message Preservation

The middleware intelligently preserves message context:

- **Recent Messages**: Always kept intact based on `keep` configuration
- **AI/Tool Pairs**: Never split - if a cutoff point falls within tool messages, the system adjusts to keep the entire AI + Tool message sequence together
- **Summary Format**: Summary is injected as a HumanMessage with the format:
  ```
  Here is a summary of the conversation to date:

  [Generated summary text]
  ```

## 最佳实践

### 选择触发阈值

1. **Token-based triggers**: Recommended for most use cases
   - Set to 60-80% of your model's context window
   - Example: For 8K context, use 4000-6000 tokens

2. **Message-based triggers**: Useful for controlling conversation length
   - Good for applications with many short messages
   - Example: 50-100 messages depending on average message length

3. **Fraction-based triggers**: Ideal when using multiple models
   - Automatically adapts to each model's capacity
   - Example: 0.8 (80% of model's max input tokens)

### Choosing Retention Policy (`keep`)

1. **Message-based retention**: Best for most scenarios
   - Preserves natural conversation flow
   - Recommended: 15-25 messages

2. **Token-based retention**: Use when precise control is needed
   - Good for managing exact token budgets
   - Recommended: 2000-4000 tokens

3. **Fraction-based retention**: For multi-model setups
   - Automatically scales with model capacity
   - Recommended: 0.2-0.4 (20-40% of max input)

### Model Selection

- **Recommended**: Use a lightweight, cost-effective model for summaries
  - Examples: `gpt-4o-mini`, `claude-haiku`, or equivalent
  - Summaries don't require the most powerful models
  - Significant cost savings on high-volume applications

- **Default**: If `model_name` is `null`, uses the default model
  - May be more expensive but ensures consistency
  - Good for simple setups

### Optimization Tips

1. **Balance triggers**: Combine token and message triggers for robust handling
   ```yaml
   trigger:
     - type: tokens
       value: 4000
     - type: messages
       value: 50
   ```

2. **Conservative retention**: Keep more messages initially, adjust based on performance
   ```yaml
   keep:
     type: messages
     value: 25  # Start higher, reduce if needed
   ```

3. **Trim strategically**: Limit tokens sent to summarization model
   ```yaml
   trim_tokens_to_summarize: 4000  # Prevents expensive summarization calls
   ```

4. **Monitor and iterate**: Track summary quality and adjust configuration

## Troubleshooting

### Summary Quality Issues

**Problem**: Summaries losing important context

**Solutions**:
1. Increase `keep` value to preserve more messages
2. Decrease trigger thresholds to summarize earlier
3. Customize `summary_prompt` to emphasize key information
4. Use a more capable model for summarization

### Performance Issues

**Problem**: Summarization calls taking too long

**Solutions**:
1. Use a faster model for summaries (e.g., `gpt-4o-mini`)
2. Reduce `trim_tokens_to_summarize` to send less context
3. Increase trigger thresholds to summarize less frequently

### Token Limit Errors

**Problem**: Still hitting token limits despite summarization

**Solutions**:
1. Lower trigger thresholds to summarize earlier
2. Reduce `keep` value to preserve fewer messages
3. Check if individual messages are very large
4. Consider using fraction-based triggers

## 实现细节

### 代码结构

- **配置**：`packages/harness/deerflow/config/summarization_config.py`
- **集成**：`packages/harness/deerflow/agents/lead_agent/agent.py`
- **中间件**：使用`langchain.agents.middleware.SummarizationMiddleware`

**为什么这样组织代码**：
- **配置分离**：配置逻辑独立，便于测试和维护
- **集中集成**：在lead_agent中统一注册中间件
- **复用LangChain**：利用成熟的中间件实现

### 中间件执行顺序

摘要在ThreadData和Sandbox初始化之后，但在Title和Clarification之前运行：

1. ThreadDataMiddleware
2. SandboxMiddleware
3. **SummarizationMiddleware** ← 在此处运行
4. TitleMiddleware
5. ClarificationMiddleware

**为什么需要这个顺序**：
- **先准备数据**：ThreadData和Sandbox先初始化必要的上下文
- **再摘要历史**：摘要需要完整的对话历史
- **后生成标题**：标题生成依赖摘要后的上下文
- **最后澄清**：澄清可能在摘要后触发

### 状态管理

- 摘要是无状态的 - 配置在启动时加载一次
- 摘要作为普通消息添加到对话历史中
- checkpointer自动持久化摘要后的历史

**为什么这样设计状态管理**：
- **无状态设计**：简化中间件实现，避免副作用
- **消息集成**：摘要作为普通消息，对其他组件透明
- **自动持久化**：利用现有checkpointer机制，无需额外逻辑

## 示例配置

### 最小化配置
```yaml
summarization:
  enabled: true
  trigger:
    type: tokens
    value: 4000
  keep:
    type: messages
    value: 20
```

### Production Configuration
```yaml
summarization:
  enabled: true
  model_name: gpt-4o-mini  # Lightweight model for cost efficiency
  trigger:
    - type: tokens
      value: 6000
    - type: messages
      value: 75
  keep:
    type: messages
    value: 25
  trim_tokens_to_summarize: 5000
```

### Multi-Model Configuration
```yaml
summarization:
  enabled: true
  model_name: gpt-4o-mini
  trigger:
    type: fraction
    value: 0.7  # 70% of model's max input
  keep:
    type: fraction
    value: 0.3  # Keep 30% of max input
  trim_tokens_to_summarize: 4000
```

### Conservative Configuration (High Quality)
```yaml
summarization:
  enabled: true
  model_name: gpt-4  # Use full model for high-quality summaries
  trigger:
    type: tokens
    value: 8000
  keep:
    type: messages
    value: 40  # Keep more context
  trim_tokens_to_summarize: null  # No trimming
```

## References

- [LangChain Summarization Middleware Documentation](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)
- [LangChain Source Code](https://github.com/langchain-ai/langchain)
