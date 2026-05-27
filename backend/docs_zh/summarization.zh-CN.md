# 对话摘要（Summarization）

DeerFlow 内置自动对话摘要能力，用于处理接近模型 token 上限的长对话。启用后，系统会在保留近期上下文的同时自动压缩较早消息。

## 概述

摘要功能基于 LangChain 的 `SummarizationMiddleware`，会监控对话历史并根据可配置阈值触发摘要。触发后将：

1. 实时监控消息 token 数量
2. 达到阈值时触发摘要
3. 保留近期消息，仅压缩较早交互
4. 保持 AI/Tool 消息配对不被拆分，保证上下文连续性
5. 将摘要结果重新注入对话

## 配置

摘要配置位于 `config.yaml` 的 `summarization` 字段下：

```yaml
summarization:
  enabled: true
  model_name: null  # 使用默认模型，或指定轻量模型

  # 触发条件（OR 逻辑 - 任一条件满足即触发摘要）
  trigger:
    - type: tokens
      value: 4000
    # 额外触发器（可选）
    # - type: messages
    #   value: 50
    # - type: fraction
    #   value: 0.8  # 模型最大输入 token 的 80%

  # 上下文保留策略
  keep:
    type: messages
    value: 20

  # 摘要调用前的 token 裁剪
  trim_tokens_to_summarize: 4000

  # 自定义摘要提示词（可选）
  summary_prompt: null

  # 在技能救援（skill rescue）中视作技能文件读取的工具名
  skill_file_read_tool_names:
    - read_file
    - read
    - view
    - cat
```

### 配置项说明

#### `enabled`
- **类型**：Boolean
- **默认值**：`false`
- **说明**：启用或禁用自动摘要

#### `model_name`
- **类型**：String 或 null
- **默认值**：`null`（使用默认模型）
- **说明**：用于生成摘要的模型。推荐使用轻量、低成本模型，如 `gpt-4o-mini` 或同级模型。

#### `trigger`
- **类型**：单个 `ContextSize` 或 `ContextSize` 列表
- **必填约束**：启用摘要时必须至少配置一个触发条件
- **说明**：触发摘要的阈值，采用 OR 逻辑——任意一个条件满足即触发。

**ContextSize 类型：**

1. **按 token 触发**：当 token 数达到指定值时触发
   ```yaml
   trigger:
     type: tokens
     value: 4000
   ```

2. **按消息数触发**：当消息数达到指定值时触发
   ```yaml
   trigger:
     type: messages
     value: 50
   ```

3. **按比例触发**：当 token 使用量达到模型最大输入 token 的某个比例时触发
   ```yaml
   trigger:
     type: fraction
     value: 0.8  # 最大输入 token 的 80%
   ```

**多触发器示例：**
```yaml
trigger:
  - type: tokens
    value: 4000
  - type: messages
    value: 50
```

#### `keep`
- **类型**：`ContextSize` 对象
- **默认值**：`{type: messages, value: 20}`
- **说明**：指定摘要后要保留的近期对话量。

**示例：**
```yaml
# 保留最近 20 条消息
keep:
  type: messages
  value: 20

# 保留最近 3000 token
keep:
  type: tokens
  value: 3000

# 保留模型最大输入 token 的最近 30%
keep:
  type: fraction
  value: 0.3
```

#### `trim_tokens_to_summarize`
- **类型**：Integer 或 null
- **默认值**：`4000`
- **说明**：执行摘要调用时，最多向摘要模型发送多少 token。设为 `null` 可关闭裁剪（不建议在超长对话中使用）。

#### `summary_prompt`
- **类型**：String 或 null
- **默认值**：`null`（使用 LangChain 默认提示词）
- **说明**：自定义摘要提示词模板，应引导模型提取最关键上下文。

#### `preserve_recent_skill_count`
- **类型**：Integer（≥ 0）
- **默认值**：`5`
- **说明**：从摘要中“救援”最近加载的技能文件数量。仅当工具名位于 `skill_file_read_tool_names` 且目标路径在 `skills.container_path`（如 `/mnt/skills/...`）下时，才被视为技能读取并参与救援。可防止压缩后丢失技能指令。设为 `0` 可完全禁用技能救援。

#### `preserve_recent_skill_tokens`
- **类型**：Integer（≥ 0）
- **默认值**：`25000`
- **说明**：技能救援可使用的总 token 预算。预算耗尽后，较早技能内容将允许进入摘要。

#### `preserve_recent_skill_tokens_per_skill`
- **类型**：Integer（≥ 0）
- **默认值**：`5000`
- **说明**：单个技能读取的 token 上限。若某次技能读取结果超过该值，则不参与救援（按普通内容进入摘要流程）。

#### `skill_file_read_tool_names`
- **类型**：字符串列表
- **默认值**：`["read_file", "read", "view", "cat"]`
- **说明**：摘要技能救援时视为“技能文件读取”的工具名集合。仅当工具名在该列表中，且目标路径位于 `skills.container_path` 下时，调用才有资格参与技能救援。

**默认提示词行为：**
LangChain 默认提示词会指导模型：
- 提取高质量、最相关上下文
- 聚焦总体目标的关键信息
- 避免重复已经完成的动作
- 仅返回抽取后的上下文内容

## 工作机制

### 摘要流程

1. **监控**：每次模型调用前，middleware 统计消息历史 token
2. **触发判断**：任一阈值满足即触发摘要
3. **消息分区**：将消息分为
   - 待摘要消息（超出 `keep` 的较早消息）
   - 保留消息（`keep` 范围内的近期消息）
4. **生成摘要**：模型对较早消息生成简洁摘要
5. **替换上下文**：更新消息历史
   - 移除旧消息
   - 插入一条摘要消息
   - 保留近期消息
6. **AI/Tool 配对保护**：确保 AI 消息与对应 Tool 消息保持成对，不被拆分
7. **技能救援（Skill Rescue）**：生成摘要前，会把最近加载的技能文件（工具名在 `skill_file_read_tool_names`、且目标路径在 `skills.container_path` 下）从待摘要集合中“提起”并前置到保留尾部。选择采用“从新到旧”策略，并受三个预算共同约束：`preserve_recent_skill_count`、`preserve_recent_skill_tokens`、`preserve_recent_skill_tokens_per_skill`。触发该技能读取的 AIMessage 及其成对 ToolMessages 会整体移动，以保持 tool_call ↔ tool_result 配对不被破坏。

### Token 计数

- 采用基于字符数的近似 token 估算
- 对 Anthropic 模型：约 3.3 字符/Token
- 对其他模型：使用 LangChain 默认估算
- 可通过自定义 `token_counter` 函数覆盖

### 消息保留策略

middleware 会智能保留上下文：

- **近期消息**：依据 `keep` 配置始终完整保留
- **AI/Tool 配对**：绝不拆分。若切分点落在工具消息中间，系统会自动调整，保留完整的 AI + Tool 消息序列
- **摘要格式**：摘要以 HumanMessage 注入，格式如下：
  ```
  Here is a summary of the conversation to date:

  [Generated summary text]
  ```

## 最佳实践

### 触发阈值选择

1. **Token 触发**：大多数场景推荐
   - 建议设为模型上下文窗口的 60%-80%
   - 例如：8K 上下文可设 4000-6000 token

2. **消息数触发**：适合控制对话长度
   - 对短消息频繁场景效果好
   - 例如：按平均消息长度设置 50-100 条

3. **比例触发**：适合多模型场景
   - 可自动适配不同模型容量
   - 例如：`0.8`（模型最大输入 token 的 80%）

### 保留策略（`keep`）选择

1. **按消息数保留**：多数场景最佳
   - 更符合自然对话流
   - 推荐：15-25 条消息

2. **按 token 保留**：需要精细预算控制时使用
   - 适合严格管理 token 成本
   - 推荐：2000-4000 token

3. **按比例保留**：适合多模型配置
   - 自动随模型能力缩放
   - 推荐：0.2-0.4（最大输入的 20%-40%）

### 模型选择

- **推荐**：摘要使用轻量、低成本模型
  - 例如：`gpt-4o-mini`、`claude-haiku` 或同类模型
  - 摘要任务通常不需要最强模型
  - 高并发场景下可显著节省成本

- **默认行为**：`model_name` 为 `null` 时使用默认模型
  - 可能更贵，但一致性更高
  - 适合简单部署

### 优化建议

1. **平衡触发器**：组合 token 和消息数触发，鲁棒性更高
   ```yaml
   trigger:
     - type: tokens
       value: 4000
     - type: messages
       value: 50
   ```

2. **保守保留**：先保留更多消息，再按效果逐步收紧
   ```yaml
   keep:
     type: messages
     value: 25  # 先取较高值，必要时再降低
   ```

3. **策略性裁剪**：限制发送到摘要模型的 token 数
   ```yaml
   trim_tokens_to_summarize: 4000  # 避免昂贵的摘要调用
   ```

4. **持续观测与迭代**：跟踪摘要质量并迭代配置

## 故障排查

### 摘要质量问题

**问题**：摘要丢失关键信息

**解决方案：**
1. 增大 `keep` 值以保留更多消息
2. 降低触发阈值，让摘要更早发生
3. 自定义 `summary_prompt`，强调关键内容
4. 使用更强模型进行摘要

### 性能问题

**问题**：摘要调用耗时过长

**解决方案：**
1. 摘要改用更快模型（如 `gpt-4o-mini`）
2. 降低 `trim_tokens_to_summarize`，减少传入上下文
3. 提高触发阈值，降低摘要频次

### Token 超限问题

**问题**：即使启用了摘要仍触发 token 限制错误

**解决方案：**
1. 降低触发阈值，提前摘要
2. 减小 `keep` 值，减少保留消息
3. 检查是否存在超大单条消息
4. 考虑使用按比例触发

## 实现细节

### 代码结构

- **配置**：`packages/harness/deerflow/config/summarization_config.py`
- **集成点**：`packages/harness/deerflow/agents/lead_agent/agent.py`
- **middleware**：使用 `langchain.agents.middleware.SummarizationMiddleware`

### Middleware 顺序

Summarization 在 ThreadData 与 Sandbox 初始化之后、Title 与 Clarification 之前执行：

1. ThreadDataMiddleware
2. SandboxMiddleware
3. **SummarizationMiddleware** ← 在此执行
4. TitleMiddleware
5. ClarificationMiddleware

### 状态管理

- 摘要流程本身是无状态的：配置在启动时加载一次
- 摘要作为常规消息写入对话历史
- checkpointer 会自动持久化摘要后的历史

## 配置示例

### 最小配置
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

### 生产配置
```yaml
summarization:
  enabled: true
  model_name: gpt-4o-mini  # 轻量模型，提升成本效率
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

### 多模型配置
```yaml
summarization:
  enabled: true
  model_name: gpt-4o-mini
  trigger:
    type: fraction
    value: 0.7  # 模型最大输入的 70%
  keep:
    type: fraction
    value: 0.3  # 保留最大输入的 30%
  trim_tokens_to_summarize: 4000
```

### 保守配置（高质量优先）
```yaml
summarization:
  enabled: true
  model_name: gpt-4  # 使用完整模型提升摘要质量
  trigger:
    type: tokens
    value: 8000
  keep:
    type: messages
    value: 40  # 保留更多上下文
  trim_tokens_to_summarize: null  # 不裁剪
```

## 参考链接

- [LangChain Summarization Middleware Documentation](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)
- [LangChain Source Code](https://github.com/langchain-ai/langchain)
