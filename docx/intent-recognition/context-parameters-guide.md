# DeerFlow Context 参数使用指南

本文档提供 DeerFlow API 请求中 `context` 参数的完整指南，包括使用场景、API 调用示例，以及触发 `dify_knowledge` 等工具的意图识别方法。

---

## 目录

1. [概述](#1-概述)
2. [Context 参数白名单](#2-context-参数白名单)
3. [参数详解](#3-参数详解)
4. [使用示例](#4-使用示例)
5. [工具触发意图识别](#5-工具触发意图识别)
6. [前端后端映射](#6-前端后端映射)
7. [总结表格](#7-总结表格)

---

## 1. 概述

`context` 参数是 DeerFlow 的特有扩展，允许客户端在创建运行时覆盖配置。它在 `/api/threads/{thread_id}/runs/stream` 及类似端点的请求体中传递。

**请求中的位置：**
```json
{
  "input": {
    "messages": [
      {"role": "user", "content": "您的问题"}
    ]
  },
  "context": {
    "model_name": "deepseek-v4-flash",
    "mode": "pro",
    "thinking_enabled": true,
    "reasoning_effort": "medium"
  }
}
```

**核心原则：** 只有白名单中的 key 才会被 DeerFlow 处理，未知 key 会被静默忽略。

---

## 2. Context 参数白名单

从 `backend/app/gateway/services.py` 可以看到，只有以下 key 才会被识别：

```python
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset({
    "model_name",                # 模型名称
    "mode",                      # 输入模式
    "thinking_enabled",          # 启用思考模式
    "reasoning_effort",          # 推理强度
    "is_plan_mode",              # 计划模式
    "subagent_enabled",          # 启用子代理
    "max_concurrent_subagents",  # 最大并发子代理数
    "agent_name",                # 代理名称
    "is_bootstrap",              # 引导模式
})
```

---

## 3. 参数详解

### 3.1 `model_name` - 模型选择

**类型：** `string`

**说明：** 指定该请求使用的 LLM 模型。

**使用场景：**
- 想用不同的模型处理不同类型的请求
- 测试不同模型的响应效果
- 根据任务复杂度选择性价比模型

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "解释量子计算"}]},
    "context": {"model_name": "deepseek-v4-flash"},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 3.2 `thinking_enabled` - 启用思考模式

**类型：** `boolean`

**默认值：** `false`

**说明：** 启用模型的"思考链"功能（类似 CoT），模型会先展示推理过程再给出答案。

**使用场景：**
- 复杂问题需要分步推理
- 需要模型展示推理过程
- 数学、逻辑、代码等需要推理的任务

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "如何实现一个分布式锁？"}]},
    "context": {
      "model_name": "deepseek-v4-flash",
      "thinking_enabled": true
    },
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 3.3 `reasoning_effort` - 推理强度

**类型：** `string`

**可选值：** `"minimal"` | `"low"` | `"medium"` | `"high"`

**说明：** 控制思考模式的深度（需要模型支持）。

| 值 | 说明 | 适用场景 |
|---|---|---|
| `"minimal"` | 最小推理 | 简单问题，快速响应 |
| `"low"` | 低推理 | Thinking 模式默认 |
| `"medium"` | 中等推理 | Pro 模式默认 |
| `"high"` | 高推理 | Ultra 模式默认 |

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "分析2024年全球经济趋势"}]},
    "context": {
      "model_name": "deepseek-v4-flash",
      "thinking_enabled": true,
      "reasoning_effort": "high"
    },
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 3.4 `mode` - 输入模式（快捷方式）

**类型：** `string`

**可选值：** `"flash"` | `"thinking"` | `"pro"` | `"ultra"`

**说明：** 预设模式的快捷方式，会自动设置 `thinking_enabled` 和 `reasoning_effort`。

| 模式 | thinking_enabled | reasoning_effort | 特点 |
|---|---|---|---|
| `"flash"` | false | minimal | 最快响应，无思考 |
| `"thinking"` | true | low | 轻量思考 |
| `"pro"` | true | medium | 平衡模式 |
| `"ultra"` | true | high | 深度思考 |

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "帮我写一个排序算法"}]},
    "context": {"mode": "pro"},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

**注意：** `mode` 与单独设置 `thinking_enabled` + `reasoning_effort` 是互斥的，`mode` 会自动设置后两者。

---

### 3.5 `is_plan_mode` - 计划模式

**类型：** `boolean`

**默认值：** `false`

**说明：** 启用计划模式，模型会先生成一个执行计划供用户确认，而非直接执行。

**使用场景：**
- 复杂任务需要分步确认
- 用户需要控制执行流程
- 敏感操作需要用户审核

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "帮我重构整个项目"}]},
    "context": {"is_plan_mode": true},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 3.6 `subagent_enabled` - 启用子代理

**类型：** `boolean`

**默认值：** `true`

**说明：** 是否允许 Agent 创建和使用子代理处理复杂任务。

**使用场景：**
- 需要并行处理多个独立子任务
- 复杂任务可以分解为简单子任务

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "分析这三个竞争对手的策略"}]},
    "context": {
      "model_name": "deepseek-v4-flash",
      "subagent_enabled": true
    },
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 3.7 `agent_name` - 代理名称

**类型：** `string`

**默认值：** `"lead-agent"`

**说明：** 指定该请求使用的代理名称。

**示例：**
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "你好"}]},
    "context": {"agent_name": "my-custom-agent"},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

## 4. 使用示例

### 4.1 场景 1：快速简单问答（Flash）
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "今天天气怎么样？"}]},
    "context": {"mode": "flash"},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 4.2 场景 2：复杂问题深度分析（Ultra）
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "分析 AI 对未来就业市场的影响"}]},
    "context": {"mode": "ultra"},
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 4.3 场景 3：自定义配置
```bash
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "帮我写一段代码"}]},
    "context": {
      "model_name": "deepseek-v4-flash",
      "thinking_enabled": true,
      "reasoning_effort": "medium",
      "subagent_enabled": true
    },
    "stream_mode": ["values", "messages-tuple"]
  }'
```

---

### 4.4 Python SDK 示例
```python
from deerflow import DeerFlowClient

client = DeerFlowClient()

# 示例 1：Flash 模式（快速问答）
print("=== Flash 模式 ===")
for event in client.stream(
    "1+1等于几？",
    thread_id="demo-flash",
    mode="flash"
):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data.get("content", ""), end="", flush=True)
print()

# 示例 2：Ultra 模式（深度思考）
print("\n=== Ultra 模式 ===")
for event in client.stream(
    "分析为什么月亮是圆的",
    thread_id="demo-ultra",
    mode="ultra"
):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data.get("content", ""), end="", flush=True)
print()

# 示例 3：自定义配置
print("\n=== 自定义配置 ===")
for event in client.stream(
    "帮我写一个快速排序算法",
    thread_id="demo-custom",
    model_name="deepseek-v4-flash",
    thinking_enabled=True,
    reasoning_effort="medium"
):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data.get("content", ""), end="", flush=True)
print()
```

---

## 5. 工具触发意图识别

### 5.1 工具触发机制

`dify_knowledge` 等 LangChain 工具的触发依赖于 LLM 的决策：

1. **工具描述 (Tool Description)** - 工具函数的 docstring 被解析后发送给 LLM
2. **用户查询 (User Query)** - LLM 将用户输入与工具描述进行对比
3. **决策 (Decision)** - LLM 根据语义匹配决定是否调用工具

### 5.2 `dify_knowledge` 工具定义

来自 `backend/packages/zens/zens/community/dify/workflows/knowledge.py`：

```python
@tool("dify_knowledge", parse_docstring=True)
def dify_knowledge_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """知识问答工作流（需在 query 中包含"dify"或"知识库"关键词触发）。

    当用户显式要求查询知识库时调用本工具：
    - 知识库检索 / 知识查询 / 文档查阅
    - 产品说明 / 操作指南 / 业务介绍

    注意：query 中需包含"dify"、"知识库"或"查询知识库"等关键词，模型才会触发本工具。

    Args:
        query: 用户的知识性或百科类问题。
    """
    return invoke_workflow("dify_knowledge", query, config)
```

### 5.3 当前触发关键词

| 关键词 | 说明 |
|--------|------|
| `dify` | 工具名称 |
| `知识库` | 知识库 |
| `查询知识库` | 查询知识库 |

### 5.4 会触发与不会触发的情况

**会触发：**
- "查询知识库：如何开通账户"
- "从知识库查找产品说明"
- "帮我查一下知识库里的操作指南"

**不会触发：**
- "如何开通账户" - 缺少关键词
- "帮我查下产品功能" - 缺少关键词
- "这是什么政策" - 缺少关键词

### 5.5 优化方案：改进工具 Docstring

**当前问题：** docstring 充当"限制条件"而非"场景描述"。

**方案 A：扩大触发场景（推荐）**

```python
"""知识问答工作流。

当用户需要从知识库中查找答案时调用本工具：
- 查找产品说明、操作指南或业务介绍
- 检索文档、FAQ 或常见问题
- 询问关于公司制度、流程规范等问题
- 查询技术文档或使用手册
- 任何需要查询内部知识的问题

Args:
    query: 用户的知识性或百科类问题。
"""
```

**效果：**
- ✅ "如何开通账户" → 会触发（涉及"产品说明"）
- ✅ "帮我查下产品功能" → 会触发（涉及"产品说明"）
- ✅ "这是什么政策" → 会触发（涉及"制度"）
- ✅ "查询知识库" → 仍然触发

**方案 B：添加工具名称提示**

```python
"""知识问答工作流（使用 dify_knowledge 工具）。

当用户询问以下类型的问题时调用本工具：
- 关于产品、服务、政策的查询
- 操作流程或使用说明
- 任何需要从内部知识库获取答案的问题
- 直接要求"查询知识库"或"查一下"

Args:
    query: 用户的知识性或百科类问题。
"""
```

**方案 C：添加更多触发场景示例**

```python
"""知识问答工作流。

本工具用于从企业知识库中检索相关文档和答案。

适用场景：
- 用户询问"怎么..."、"如何..."
- 用户询问"是什么"关于产品/服务/政策
- 用户要求"查一下"或"帮我找"
- 用户说"从知识库查询"
- 任何涉及公司内部文档的问题

Args:
    query: 用户的知识性或百科类问题。
"""
```

### 5.6 工具描述最佳实践

1. **描述使用场景，而非限制条件** - 告诉 LLM 何时使用，而非必须包含什么关键词
2. **覆盖常见表达** - 包含用户可能的各种表达方式
3. **明确但不僵化** - 提供足够的上下文让 LLM 做出好的决策
4. **避免"必须包含 X"的说法** - 这会限制工具的发现性

---

## 6. 前端后端映射

来自 `frontend/src/components/workspace/input-box.tsx`：

```typescript
// 前端 context 结构
interface AgentThreadContext {
  mode: "flash" | "thinking" | "pro" | "ultra";
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  model_name: string;
  thinking_enabled?: boolean;
  subagent_enabled?: boolean;
  is_plan_mode?: boolean;
}

// Mode -> reasoning_effort 映射
const modeToEffort = {
  ultra: "high",
  pro: "medium",
  thinking: "low",
  flash: "minimal"
};

// Mode 选择处理器
const handleModeSelect = useCallback(
  (mode: InputMode) => {
    onContextChange?.({
      ...context,
      mode: getResolvedMode(mode, supportThinking),
      reasoning_effort:
        mode === "ultra"
          ? "high"
          : mode === "pro"
            ? "medium"
            : mode === "thinking"
              ? "low"
              : "minimal",
    });
  },
  [onContextChange, context, supportThinking],
);
```

---

## 7. 总结表格

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_name` | string | 配置中的第一个模型 | LLM 模型选择 |
| `mode` | flash/thinking/pro/ultra | - | 快捷模式设置 |
| `thinking_enabled` | boolean | false | 是否启用思考模式 |
| `reasoning_effort` | minimal/low/medium/high | - | 推理强度 |
| `is_plan_mode` | boolean | false | 是否先规划再执行 |
| `subagent_enabled` | boolean | true | 是否启用子代理 |
| `agent_name` | string | "lead-agent" | 代理名称选择 |
| `max_concurrent_subagents` | int | - | 最大并发子代理数 |
| `is_bootstrap` | boolean | - | 引导模式 |

---

## 8. 相关文件

- `backend/app/gateway/services.py` - `merge_run_context_overrides()` 函数
- `backend/app/gateway/routers/thread_runs.py` - `RunCreateRequest` 模型
- `backend/packages/harness/deerflow/models/factory.py` - `create_chat_model()` 函数
- `frontend/src/components/workspace/input-box.tsx` - 前端 context 处理
- `backend/packages/zens/zens/community/dify/workflows/knowledge.py` - `dify_knowledge` 工具

---

## 9. 修订历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-06-01 | 1.0 | 初始文档创建 |

---

*本文档属于 DeerFlow 意图识别文档系列。*
