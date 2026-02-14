# Conversation Summarization

DeerFlow includes automatic conversation summarization to handle long conversations that approach model token limits. When enabled, the system automatically condenses older messages while preserving recent context.

## Overview

The summarization feature uses LangChain's `SummarizationMiddleware` to monitor conversation history and trigger summarization based on configurable thresholds. When activated, it:

1. Monitors message token counts in real-time
2. Triggers summarization when thresholds are met
3. Keeps recent messages intact while summarizing older exchanges
4. Maintains AI/Tool message pairs together for context continuity
5. Injects the summary back into the conversation

## Configuration

Summarization is configured in `config.yaml` under the `summarization` key:

```yaml
summarization:
  enabled: true
  model_name: null  # Use default model or specify a lightweight model

  # Trigger conditions (OR logic - any condition triggers summarization)
  trigger:
    - type: tokens
      value: 4000
    # Additional triggers (optional)
    # - type: messages
    #   value: 50
    # - type: fraction
    #   value: 0.8  # 80% of model's max input tokens

  # Context retention policy
  keep:
    type: messages
    value: 20

  # Token trimming for summarization call
  trim_tokens_to_summarize: 4000

  # Custom summary prompt (optional)
  summary_prompt: null
```

### Configuration Options

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

**Default Prompt Behavior:**
The default LangChain prompt instructs the model to:
- Extract highest quality/most relevant context
- Focus on information critical to the overall goal
- Avoid repeating completed actions
- Return only the extracted context

## How It Works

### Summarization Flow

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

## Best Practices

### Choosing Trigger Thresholds

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

## Implementation Details

### Code Structure

- **Configuration**: `src/config/summarization_config.py`
- **Integration**: `src/agents/lead_agent/agent.py`
- **Middleware**: Uses `langchain.agents.middleware.SummarizationMiddleware`

### Middleware Order

Summarization runs after ThreadData and Sandbox initialization but before Title and Clarification:

1. ThreadDataMiddleware
2. SandboxMiddleware
3. **SummarizationMiddleware** ← Runs here
4. TitleMiddleware
5. ClarificationMiddleware

### State Management

- Summarization is stateless - configuration is loaded once at startup
- Summaries are added as regular messages in the conversation history
- The checkpointer persists the summarized history automatically

## Example Configurations

### Minimal Configuration
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
