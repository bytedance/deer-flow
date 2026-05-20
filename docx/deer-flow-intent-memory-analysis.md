# DeerFlow 意图识别与记忆系统机制分析

> 分析时间：2026/05/20
> 版本：基于当前代码库

---

## 一、意图识别机制

### 1.1 整体架构：无显式意图分类器

DeerFlow 采用 **LLM 原生判断** 策略，不使用传统的规则/ML 意图分类器。

```
用户消息 → FastAPI Gateway → normalize_input() → LangGraph Agent → LLM自主判断
                                                        ↓
                                              ask_clarification工具（LLM自行调用）
                                                        ↓
                                          ClarificationMiddleware（拦截并中断）
```

**核心设计思想**：DeerFlow 将意图识别的责任完全交给 LLM，通过系统提示词引导 LLM 在执行前先识别需要澄清的场景，并调用 `ask_clarification` 工具触发 ClarificationMiddleware 进行中断和用户交互。

### 1.2 消息入口点

| 文件 | 作用 |
|------|------|
| `backend/app/gateway/routers/thread_runs.py` | `POST /api/threads/{thread_id}/runs/stream` 消息入口 |
| `backend/app/gateway/services.py:77-96` | `normalize_input()` 消息标准化（转 HumanMessage 等） |
| `packages/harness/deerflow/agents/lead_agent/agent.py` | LangGraph Agent 工厂 `make_lead_agent` |

### 1.3 LLM 自我判断机制 — Clarify → Plan → Act

在 `packages/harness/deerflow/agents/lead_agent/prompt.py` 的 `SYSTEM_PROMPT_TEMPLATE` 中，核心系统提示词：

```python
<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. **FIRST**: Analyze the request in your thinking - identify what's unclear, missing, or ambiguous
2. **SECOND**: If clarification is needed, call `ask_clarification` tool IMMEDIATELY - do NOT start working
3. **THIRD**: Only after all clarifications are resolved, proceed with planning and execution

**MANDATORY Clarification Scenarios - You MUST call ask_clarification BEFORE starting work when:**

1. **Missing Information** (`missing_info`): Required details not provided
   - Example: User says "create a web scraper" but doesn't specify the target website

2. **Ambiguous Requirements** (`ambiguous_requirement`): Multiple valid interpretations exist
   - Example: "Optimize the code" could mean performance, readability, or memory usage

3. **Approach Choices** (`approach_choice`): Several valid approaches exist
   - Example: "Add authentication" could use JWT, OAuth, session-based, or API keys

4. **Risky Operations** (`risk_confirmation`): Destructive actions need confirmation
   - Example: Deleting files, modifying production configs

5. **Suggestions** (`suggestion`): You have a recommendation but want approval
```

### 1.4 中间件链（18+1）

```
... → LoopDetectionMiddleware → ClarificationMiddleware（永远是最后一个）
```

**完整中间件顺序**：
1. ThreadDataMiddleware — 创建per-thread隔离目录
2. UploadsMiddleware — 注入上传文件到上下文
3. SandboxMiddleware — 获取sandbox环境
4. DanglingToolCallMiddleware — 注入中断的tool call占位符
5. LLMErrorHandlingMiddleware — 规范化provider失败
6. GuardrailMiddleware — 预工具调用授权（可选）
7. SandboxAuditMiddleware — 安全审计日志
8. ToolErrorHandlingMiddleware — 工具异常转可恢复错误
9. DynamicContextMiddleware — 动态上下文
10. DeerFlowSummarizationMiddleware — 摘要（可选）
11. TodoMiddleware — 多步任务追踪（可选）
12. TokenUsageMiddleware — Token指标记录（可选）
13. TitleMiddleware — 自动生成对话标题
14. MemoryMiddleware — 异步记忆更新队列
15. ViewImageMiddleware — 图像数据注入
16. DeferredToolFilterMiddleware — 隐藏延迟工具直到搜索启用
17. SubagentLimitMiddleware — 强制最多3个并发子代理
18. LoopDetectionMiddleware — 检测并halt重复tool call循环
19. **ClarificationMiddleware** — 拦截澄清请求（最后）

### 1.5 ClarificationMiddleware

**文件**：`packages/harness/deerflow/agents/middlewares/clarification_middleware.py`

**核心功能**：
- 拦截 `ask_clarification` 工具调用
- 格式化澄清消息（支持JSON字符串选项、中文检测）
- 生成稳定的消息ID（支持幂等重试）
- 返回 `Command(goto=END)` 中断执行

**支持的澄清类型**：
```python
type_icons = {
    "missing_info": "❓",           # 缺少信息
    "ambiguous_requirement": "🤔", # 模糊需求
    "approach_choice": "🔀",       # 方案选择
    "risk_confirmation": "⚠️",     # 风险确认
    "suggestion": "💡",            # 建议
}
```

### 1.6 ask_clarification 工具

```python
ask_clarification(
    question="Your specific question here?",
    clarification_type="missing_info",  # 或其他类型
    context="Why you need this information",  # 可选
    options=["option1", "option2"]  # 可选，用于选择
)
```

**使用示例**：
```
User: "Deploy the application"
You (thinking): Missing environment info - I MUST ask for clarification
You (action): ask_clarification(
    question="Which environment should I deploy to?",
    clarification_type="approach_choice",
    context="I need to know the target environment for proper configuration",
    options=["development", "staging", "production"]
)
[Execution stops - wait for user response]
```

### 1.7 意图识别流程图

```
用户输入
    ↓
LLM 分析（在 thinking 中）
    ↓
是否有不明确/缺失/模糊？
    ├── 否 → 执行工具/动作
    └── 是 → 调用 ask_clarification 工具
                ↓
        ClarificationMiddleware 拦截
                ↓
        返回 Command(goto=END) 中断
                ↓
        向用户展示澄清问题
                ↓
        用户回答后继续执行
```

---

## 二、记忆系统机制

### 2.1 整体架构

```
用户消息 → Agent执行 → MemoryMiddleware.after_agent → MemoryUpdateQueue(debounce 30s) → MemoryUpdater → LLM分析 → 更新memory.json
                                                                                                      ↓
                                                                       下次Agent执行 ← format_memory_for_injection() ← 读取memory.json
```

### 2.2 存储结构

记忆按 **用户维度** 隔离存储，无向量数据库，使用 **JSON 文件存储**。

```
{base_dir}/
├── memory.json                    # legacy全局记忆（已废弃）
└── users/
    └── {user_id}/                 # 用户隔离
        ├── memory.json            # 用户级记忆
        └── agents/
            └── {agent_name}/
                └── memory.json    # 每用户每agent记忆
```

**记忆内容结构**（memory.json）：
```json
{
  "version": "1.0",
  "lastUpdated": "2026-05-18T...",
  "user": {
    "workContext": {"summary": "", "updatedAt": ""},
    "personalContext": {"summary": "", "updatedAt": ""},
    "topOfMind": {"summary": "", "updatedAt": ""}
  },
  "history": {
    "recentMonths": {"summary": "", "updatedAt": ""},
    "earlierContext": {"summary": "", "updatedAt": ""},
    "longTermBackground": {"summary": "", "updatedAt": ""}
  },
  "facts": [
    {
      "id": "fact_abc123",
      "content": "User prefers Python over Java",
      "category": "preference|knowledge|context|behavior|goal|correction",
      "confidence": 0.85,
      "createdAt": "2026-05-18T...",
      "source": "thread_id or 'manual'"
    }
  ]
}
```

### 2.3 多用户记忆隔离机制

DeerFlow 通过 **三层隔离** 实现多用户记忆隔离：

| 隔离层 | 实现方式 |
|--------|----------|
| **ContextVar** | `user_context._current_user` 在请求内传递 |
| **user_id解析优先级** | `runtime.context["user_id"]` > `_current_user` > `DEFAULT_USER_ID` |
| **文件系统** | `user_dir(user_id)` 路径完全隔离 |

**user_id解析优先级**：
```
1. runtime.context["user_id"]      # 最高优先级，跨线程边界
2. _current_user ContextVar         # 请求内可靠
3. DEFAULT_USER_ID ("default")      # 无认证回退
```

**Timer线程边界处理**（避免ContextVar丢失）：
```python
# MemoryMiddleware 中
user_id = get_effective_user_id()  # 在请求上下文存活时立即捕获
queue.add(..., user_id=user_id, ...)  # 存入 ConversationContext

# Timer线程中（无ContextVar）
updater.update_memory(..., user_id=context.user_id)  # 读取已存储的user_id
```

### 2.4 记忆更新流程

| 阶段 | 触发条件 | 行为 |
|------|----------|------|
| 1. 拦截 | `after_agent` | 过滤消息（human + 无tool_calls的ai），检测correction/reinforcement信号 |
| 2. 入队 | `queue.add()` | 合并重复请求，启动30s debounce Timer |
| 3. 处理 | Timer到期 | 创建 `MemoryUpdater`，批量更新 |
| 4. LLM分析 | `updater.update_memory()` | 调用LLM分析对话，输出JSON更新 |
| 5. 合并保存 | `_apply_updates()` | 合并到现有memory，保存到JSON |
| 6. 注入 | 下次Agent执行 | `format_memory_for_injection()` 注入到system prompt |

### 2.5 关键文件列表

| 文件 | 职责 |
|------|------|
| `memory_middleware.py` | 拦截agent执行后触发记忆队列 |
| `queue.py` | Debounce队列，`ConversationContext`封装 |
| `updater.py` | LLM调用、记忆更新逻辑、fact管理 |
| `storage.py` | JSON文件读写，cache管理（thread-safe） |
| `prompt.py` | LLM prompt模板，`format_memory_for_injection` |
| `user_context.py` | ContextVar管理，`get_effective_user_id()` |
| `paths.py` | 路径隔离（per-user） |
| `message_processing.py` | 消息过滤、correction/reinforcement检测 |

---

## 三、意图识别 vs 记忆系统 对比

| 方面 | 意图识别 | 记忆系统 |
|------|----------|----------|
| **实现方式** | Prompt-based LLM原生判断 | LLM分析 + JSON文件存储 |
| **触发机制** | LLM自行决定调用 `ask_clarification` | `MemoryMiddleware.after_agent` 拦截 |
| **处理方式** | ClarificationMiddleware 中断执行 | MemoryUpdateQueue 异步更新 |
| **用户交互** | 是（需用户澄清） | 否（后台默默更新） |
| **无ML模型** | 无机器学习分类器 | 无向量数据库 |
| **无规则引擎** | 无显式规则匹配 | 无规则引擎 |

---

## 四、新项目意图识别方案选择

### 4.1 三种方案对比

| 方案 | 实现方式 | 优点 | 缺点 | 适用场景 |
|------|----------|------|------|----------|
| **方案1：预分类层** | normalize_input() 后插入轻量级分类器 | 独立可控、可迭代、有评估指标 | 需要额外模型/服务 | **新项目追求精确度（推荐）** |
| **方案2：改提示词** | 修改 lead agent 系统提示 | 无架构改动 | 依赖LLM通用能力、无法精确控制 | 快速验证、精度要求不高 |
| **方案3：扩展Clarification** | 自定义 ClarificationMiddleware | 利用现有机制 | 只是事后补救，不提升理解能力 | 扩展澄清类型，非意图识别 |

### 4.2 推荐方案1：预分类层

对于新项目追求"精确理解用户意图"，**方案1是最佳选择**。

#### 为什么最适合新项目

| 因素 | 分析 |
|------|------|
| **精确度** | 可针对意图分类任务专项训练/优化，不依赖LLM的通用能力 |
| **可控性** | 独立模块，可单独测试、调优、替换 |
| **成本** | 轻量模型（如 embedding-based classifier）推理成本远低于大LLM |
| **延迟** | 预分类可并行，不增加主流程延迟 |
| **可迭代** | 有明确的评估指标（准确率/召回率），可量化改进 |

#### 推荐实现路径

```
用户消息 → 预分类器 → [意图类别] → 路由/扩展上下文/触发不同工作流
                     ↓
              若置信度低 → ClarificationMiddleware（原DeerFlow机制）
```

#### 具体实现建议

**1. 轻量模型选择**：

| 方案 | 模型 | 适用场景 |
|------|------|----------|
| **无训练** | Jina AI embeddings + cosine similarity | 快速启动，0标注成本 |
| **有数据** | fine-tuned 7B 模型（如 Qwen2.5-7B-Instruct） | 追求更高精度 |

**2. 意图类别设计（建议起步5类）**：

| 意图类别 | 说明 | 后续动作 |
|----------|------|----------|
| `task` | 明确任务执行 | 进入 LangGraph Agent 正常流程 |
| `clarification_needed` | 需要澄清 | 触发 ClarificationMiddleware |
| `chitchat` | 闲聊 | 直接响应或简单处理 |
| `meta` | 关于系统的元问题 | 专用处理流程 |
| `unknown` | 低置信度 | 触发原 ClarificationMiddleware 兜底 |

**3. 预分类器位置**：

```
backend/app/gateway/services.py 的 normalize_input() 之后
                                    ↓
                          在消息进入 LangGraph 之前做分流
```

**4. 置信度机制**：

```python
if confidence < threshold:
    # 置信度低，交给原 ClarificationMiddleware 处理
    trigger_clarification()
else:
    # 置信度高，根据意图类别路由
    route_to_intent(intent)
```

#### 两步走迭代策略

| 阶段 | 目标 | 实现方式 |
|------|------|----------|
| **Phase 1** | 快速启动 | embedding-based 分类器，无需训练 |
| **Phase 2** | 精度提升 | 积累标注数据后，换成 fine-tuned 模型 |

预分类层的结果可以直接注入到 LangGraph 的 `config.configurable` 中，让后续的 Lead Agent 有更好的上下文。

### 4.3 为什么方案2和方案3不适合"精确理解"

| 方案 | 问题 |
|------|------|
| **方案2（改提示词）** | LLM的意图理解是副产品，受限于模型能力和上下文噪声，无法精确控制 |
| **方案3（扩展Clarification）** | 只是扩展了"澄清"这个事后补救机制，并没有提升"理解"能力 |

### 4.4 记忆系统定制

**当前限制**：
- 无语义检索（基于LLM全量读取）
- 大文件性能可能下降（无索引）
- 无向量相似度匹配

**可能的增强方向**：
1. 添加向量数据库支持（如 Chroma、Pgvector）
2. 实现记忆分层（短期/长期/工作记忆）
3. 添加记忆遗忘策略

## 五、方案一预分类层实现详解

### 5.1 后续流程是否还走 DeerFlow 这套？

**是的，完全走。** 预分类器只是"插队"在 `normalize_input()` 和 `run_agent()` 之间，在消息进入 LangGraph **之前**做一次预判。

```
用户消息
    ↓
normalize_input()  ← 标准化消息格式
    ↓
[预分类器]  ← 轻量级预分类，决定意图（NEW）
    ↓
build_run_config()  ← 把预分类结果注入 config.configurable
    ↓
run_agent()  ← 后续完全走 DeerFlow 原流程
    ↓
LangGraph Agent → Lead Agent → Middlewares → Tools → Skills → Memory
```

预分类器的输出影响的是 `config.configurable["intent_type"]`，Lead Agent 可以读取这个值来：
- 路由到不同的处理流程
- 注入不同的上下文
- 调整系统提示词

---

### 5.2 config.configurable 详解

#### 5.2.1 config.configurable 在 DeerFlow 中的作用

`config.configurable` 是 LangGraph `RunnableConfig` 中的一个字典，用于存储可在运行时修改的配置参数。

在 DeerFlow 中，它已经被用于多个场景：

| 现有配置项 | 说明 | 来源 |
|------------|------|------|
| `thread_id` | 线程标识 | `build_run_config()` 自动添加 |
| `model_name` | 模型名称 | 请求的 `body.context` |
| `thinking_enabled` | 是否启用思维链 | 请求的 `body.context` |
| `is_plan_mode` | 是否启用计划模式 | 请求的 `body.context` |
| `subagent_enabled` | 是否启用子代理 | 请求的 `body.context` |
| `max_concurrent_subagents` | 最大并发子代理数 | 请求的 `body.context` |
| `agent_name` | 自定义代理名称 | `build_run_config()` |

#### 5.2.2 意图预分类结果如何注入

在 `normalize_input()` 之后、调用 `build_run_config()` 之前，将预分类结果注入：

```python
# backend/app/gateway/services.py

# 意图预分类结果注入点
async def start_run(body: Any, thread_id: str, request: Request) -> RunRecord:
    # ... 前置代码 ...
    
    # Step 1: 标准化输入
    graph_input = normalize_input(body.input)
    
    # Step 2: 意图预分类（NEW）
    user_message = graph_input.get("messages", [{}])[-1].get("content", "")
    
    if user_message:
        intent_type, confidence = classify_intent(user_message)
        
        # Step 3: 初始化 config（如果不存在）
        if body.config is None:
            body.config = {}
        
        # Step 4: 初始化 configurable（如果不存在）
        if "configurable" not in body.config:
            body.config["configurable"] = {}
        
        # Step 5: 注入意图预分类结果
        body.config["configurable"]["intent_type"] = intent_type.value
        body.config["configurable"]["intent_confidence"] = confidence
        
        # 可选：标记需要澄清（置信度低时）
        if confidence < 0.7:
            body.config["configurable"]["needs_clarification"] = True
        
        # 可选：携带意图相关的额外信息
        if hasattr(intent_type, "metadata"):
            body.config["configurable"]["intent_metadata"] = intent_type.metadata
    
    # Step 6: 构建 run config（会包含上面的 configurable）
    config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)
    
    # ... 后续代码 ...
```

#### 5.2.3 config.configurable 的完整结构示例

```python
# 预分类完成后的 config.configurable 结构
config = {
    "configurable": {
        # --- 现有字段 ---
        "thread_id": "thread_abc123",          # 线程ID（自动添加）
        "model_name": "claude-3-5-sonnet",     # 模型名称（可选）
        "thinking_enabled": False,            # 思维链开关（可选）
        "is_plan_mode": False,                 # 计划模式（可选）
        "subagent_enabled": True,              # 子代理开关（可选）
        "max_concurrent_subagents": 3,         # 最大并发数（可选）
        "agent_name": None,                    # 自定义代理名（可选）
        
        # --- 意图预分类新增字段（NEW）---
        "intent_type": "task",                 # 意图类型：task | clarification_needed | chitchat | meta | unknown
        "intent_confidence": 0.85,             # 置信度：0.0 ~ 1.0
        "needs_clarification": False,          # 是否需要澄清（置信度低时为 True）
        "intent_metadata": {                  # 可选：意图相关的额外信息
            "detected_slots": ["target", "action"],  # 检测到的槽位
            "alternative_intents": ["clarification_needed"],  # 备选意图
        }
    }
}
```

#### 5.2.4 Lead Agent 如何读取 config.configurable

**方式1：在 `make_lead_agent()` 中读取**

```python
# packages/harness/deerflow/agents/lead_agent/agent.py

def make_lead_agent(config: RunnableConfig) -> Runnable:
    # 读取意图预分类结果
    configurable = config.get("configurable", {})
    intent_type = configurable.get("intent_type", "unknown")
    intent_confidence = configurable.get("intent_confidence", 0.0)
    needs_clarification = configurable.get("needs_clarification", False)
    
    # 根据意图类型调整 agent 行为
    if needs_clarification or intent_type == "clarification_needed":
        # 高优先级澄清模式
        pass
    elif intent_type == "chitchat":
        # 闲聊模式：简化流程
        pass
    elif intent_type == "task":
        # 正常任务模式：完整流程
        pass
    
    # ... 后续代码 ...
```

**方式2：在 `apply_prompt_template()` 中读取**

```python
# packages/harness/deerflow/agents/lead_agent/prompt.py

def apply_prompt_template(..., intent_type: str = "unknown", intent_confidence: float = 0.0) -> str:
    # 根据意图类型注入不同的系统提示词上下文
    if intent_type == "clarification_needed":
        clarification_section = """
        **HIGH PRIORITY CLARIFICATION MODE**
        User intent is unclear. You MUST ask for clarification BEFORE taking any action.
        """
    elif intent_type == "chitchat":
        clarification_section = """
        **CASUAL MODE**
        User seems to be chatting. Keep responses friendly and concise.
        """
    else:
        clarification_section = ""
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        # ... 其他参数 ...
        clarification_section=clarification_section,
    )
```

**方式3：在 Middleware 中读取**

```python
# packages/harness/deerflow/agents/middlewares/clarification_middleware.py

class ClarificationMiddleware:
    def after_model(self, state: AgentState, config: RunnableConfig, response: AIMessage) -> AgentState:
        # 读取预分类结果
        intent_type = config.get("configurable", {}).get("intent_type", "unknown")
        needs_clarification = config.get("configurable", {}).get("needs_clarification", False)
        
        # 如果预分类已经标记需要澄清，可以直接触发
        if needs_clarification:
            # 直接调用 ask_clarification
            pass
        
        return state
```

#### 5.2.5 意图预分类配置与现有配置的融合

意图预分类的配置可以与 DeerFlow 现有的配置项共存：

```python
# 完整的 configurable 配置示例
config = {
    "configurable": {
        # === 线程标识（必须）===
        "thread_id": "thread_abc123",
        
        # === 模型配置（可选）===
        "model_name": "claude-3-5-sonnet",
        "thinking_enabled": True,
        
        # === 运行时模式（可选）===
        "is_plan_mode": False,
        "subagent_enabled": True,
        "max_concurrent_subagents": 3,
        
        # === 自定义代理（可选）===
        "agent_name": None,
        
        # === 意图预分类（NEW）===
        "intent_type": "task",                 # string: task | clarification_needed | chitchat | meta | unknown
        "intent_confidence": 0.85,             # float: 0.0 ~ 1.0
        "needs_clarification": False,          # bool: 置信度低时为 True
        "intent_metadata": {                  # dict: 可选的额外信息
            "source": "embedding_classifier",  # 分类器来源
            "model_version": "v1.0",          # 分类器版本
        }
    }
}
```

#### 5.2.6 从请求的 body.context 注入意图配置

如果客户端通过 HTTP 请求传入意图预分类结果：

```python
# 客户端请求示例
POST /api/threads/{thread_id}/runs/stream
{
    "input": {"messages": [{"role": "user", "content": "optimize the code"}]},
    "config": {
        "configurable": {
            "model_name": "claude-3-5-sonnet",
            "intent_type": "task",
            "intent_confidence": 0.92
        }
    },
    "context": {
        "model_name": "claude-3-5-sonnet",
        "intent_type": "task"
    }
}
```

`merge_run_context_overrides()` 会将这些配置合并到最终的 `config.configurable` 中。

---

### 5.4 完整流程图

#### 高置信度场景（正常任务）

```
用户: "optimize the code"
    ↓
normalize_input()
    ↓
预分类器: classify_intent("optimize the code")
    → IntentType.TASK, confidence=0.85
    ↓
config.configurable = {
    "thread_id": "xxx",
    "intent_type": "task",
    "intent_confidence": 0.85
}
    ↓
build_run_config()
    ↓
run_agent() → LangGraph Agent
    ↓
Lead Agent 读取 intent_type="task"
    → 完整流程：skills, memory, tools
    → 不触发 ClarificationMiddleware（置信度高）
    ↓
Agent 执行
```

#### 低置信度场景（需要澄清）

```
用户: "make it better"
    ↓
normalize_input()
    ↓
预分类器: classify_intent("make it better")
    → IntentType.AMBIGUOUS, confidence=0.35  ← 置信度低
    ↓
config.configurable = {
    "thread_id": "xxx",
    "intent_type": "ambiguous_requirement",
    "intent_confidence": 0.35,
    "needs_clarification": True
}
    ↓
build_run_config()
    ↓
run_agent() → LangGraph Agent
    ↓
Lead Agent 读取 intent_type + needs_clarification
    → 直接调用 ask_clarification 工具
    → ClarificationMiddleware 拦截
    ↓
向用户展示澄清问题
```

---

### 5.5 关键优势

| 优势 | 说明 |
|------|------|
| **无缝接入** | 不改变后续的 LangGraph、skill、memory 流程 |
| **灵活路由** | 意图结果通过 `config.configurable` 传递，Lead Agent 可自由读取和使用 |
| **渐进式** | 可以先实现 embedding-based 快速启动，后续再换成 fine-tuned 模型 |
| **可测试** | 预分类器是独立模块，可以单独做单元测试和评估 |

---

### 5.6 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `backend/app/gateway/services.py` | 在 `start_run()` 中插入预分类逻辑 |
| `packages/harness/deerflow/agents/lead_agent/agent.py` | 读取 `config.configurable["intent_type"]` 并调整行为 |
| `packages/harness/deerflow/agents/lead_agent/prompt.py` | 根据意图类型注入不同的系统提示词上下文 |
| `backend/app/gateway/intent_classifier.py`（新建） | 预分类器实现 |

---

## 六、UserA vs UserB 隔离示例

```
UserA 消息 → get_effective_user_id() → "user_A" → queue.add(user_id="user_A") → memory.json写入 /users/user_A/
UserB 消息 → get_effective_user_id() → "user_B" → queue.add(user_id="user_B") → memory.json写入 /users/user_B/
```

两个用户访问时会读取各自目录，互不干扰。

---

## 七、总结

### 7.1 现有架构

| 方面 | 实现方式 |
|------|----------|
| **意图识别方法** | Prompt-based via LLM system prompt |
| **分类机制** | LLM 根据 `SYSTEM_PROMPT_TEMPLATE` 中的指令自行判断 |
| **检测方式** | LLM 使用内部推理识别不明确/缺失/模糊的请求 |
| **处理不明意图** | LLM 调用 `ask_clarification` 工具，被 ClarificationMiddleware 拦截 |
| **无ML模型** | 没有机器学习分类器 — 纯 prompt 工程 |
| **无规则引擎** | 没有显式规则匹配意图 |

**核心设计思想**：DeerFlow 将意图识别的责任完全交给 LLM，通过系统提示词引导 LLM 在执行前先识别需要澄清的场景，并调用 `ask_clarification` 工具触发 ClarificationMiddleware 进行中断和用户交互。

### 7.2 新项目推荐方案

对于新项目追求**精确理解用户意图**，推荐**方案1：预分类层**。

| 推荐理由 |
|----------|
| 独立可控：可单独测试、调优、替换 |
| 成本低：轻量模型推理成本远低于大LLM |
| 可迭代：有明确的评估指标，可量化改进 |
| 精确度高：针对意图分类任务专项优化 |

### 7.3 迭代路线

```
Phase 1（快速启动）: embedding-based 分类器
        ↓
Phase 2（精度提升）: fine-tuned 模型
```

预分类层结果注入 LangGraph `config.configurable`，为 Lead Agent 提供更好的上下文。