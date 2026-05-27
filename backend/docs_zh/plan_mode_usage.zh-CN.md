# Plan Mode 与 TodoList Middleware

本文档说明如何在 DeerFlow 2.0 中启用并使用带 TodoList middleware 的 Plan Mode 功能。

## 概述

Plan Mode 会为 agent 添加 TodoList middleware，并提供 `write_todos` 工具，帮助 agent：
- 将复杂任务拆分为更小、可管理的步骤
- 在执行过程中持续跟踪进度
- 向用户提供当前工作内容的可见性

TodoList middleware 基于 LangChain 的 `TodoListMiddleware`。

## 配置

### 启用 Plan Mode

Plan Mode 通过 **运行时配置** 控制：在 `RunnableConfig` 的 `configurable` 部分设置 `is_plan_mode` 参数。这使你可以按请求动态启用或关闭 Plan Mode。

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

# 通过运行时配置启用 plan mode
config = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # 启用 plan mode
    }
)

# 创建启用 plan mode 的 agent
agent = make_lead_agent(config)
```

### 配置项

- **is_plan_mode**（bool）：是否启用带 TodoList middleware 的 plan mode。默认值：`False`
  - 通过 `config.get("configurable", {}).get("is_plan_mode", False)` 读取
  - 可对每次 agent 调用动态设置
  - 不需要全局配置

## 默认行为

启用 plan mode 且使用默认设置时，agent 可使用 `write_todos` 工具，行为如下：

### 何时使用 TodoList

agent 会在以下场景使用 todo list：
1. 复杂多步骤任务（3 个及以上独立步骤）
2. 需要谨慎规划的非简单任务
3. 用户明确要求 todo list
4. 用户一次提供多个任务

### 何时不使用 TodoList

agent 会在以下场景跳过 todo list：
1. 单一且直接的任务
2. 琐碎任务（少于 3 步）
3. 纯对话类或信息类请求

### 任务状态

- **pending**：任务尚未开始
- **in_progress**：任务进行中（可并行存在多个任务）
- **completed**：任务已成功完成

## 使用示例

### 基础用法

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

# 创建启用 plan mode 的 agent
config_with_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # 将添加 TodoList middleware
    }
)
agent_with_todos = make_lead_agent(config_with_plan_mode)

# 创建未启用 plan mode 的 agent（默认）
config_without_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "another-thread",
        "thinking_enabled": True,
        "is_plan_mode": False,  # 不添加 TodoList middleware
    }
)
agent_without_todos = make_lead_agent(config_without_plan_mode)
```

### 按请求动态切换 Plan Mode

你可以针对不同对话或任务动态启用/禁用 plan mode：

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

def create_agent_for_task(task_complexity: str):
    """根据任务复杂度创建 agent，并决定是否启用 plan mode。"""
    is_complex = task_complexity in ["high", "very_high"]

    config = RunnableConfig(
        configurable={
            "thread_id": f"task-{task_complexity}",
            "thinking_enabled": True,
            "is_plan_mode": is_complex,  # 仅复杂任务启用
        }
    )

    return make_lead_agent(config)

# 简单任务 - 不需要 TodoList
simple_agent = create_agent_for_task("low")

# 复杂任务 - 启用 TodoList 以更好追踪
complex_agent = create_agent_for_task("high")
```

## 工作机制

1. 调用 `make_lead_agent(config)` 时，从 `config.configurable` 提取 `is_plan_mode`
2. 将配置传给 `_build_middlewares(config)`
3. `_build_middlewares()` 读取 `is_plan_mode`，并调用 `_create_todo_list_middleware(is_plan_mode)`
4. 若 `is_plan_mode=True`，会创建 `TodoListMiddleware` 实例并加入 middleware 链
5. middleware 会自动将 `write_todos` 工具加入 agent 工具集
6. agent 运行时可使用该工具管理任务
7. middleware 负责 todo list 状态管理，并将其提供给 agent

## 架构

```
make_lead_agent(config)
  │
  ├─> Extracts: is_plan_mode = config.configurable.get("is_plan_mode", False)
  │
  └─> _build_middlewares(config)
        │
        ├─> ThreadDataMiddleware
        ├─> SandboxMiddleware
        ├─> SummarizationMiddleware (if enabled via global config)
        ├─> TodoListMiddleware (if is_plan_mode=True) ← NEW
        ├─> TitleMiddleware
        └─> ClarificationMiddleware
```

## 实现细节

### Agent 模块
- **位置**：`packages/harness/deerflow/agents/lead_agent/agent.py`
- **函数**：`_create_todo_list_middleware(is_plan_mode: bool)` —— plan mode 启用时创建 TodoListMiddleware
- **函数**：`_build_middlewares(config: RunnableConfig)` —— 根据运行时配置构建 middleware 链
- **函数**：`make_lead_agent(config: RunnableConfig)` —— 创建并组装对应 middleware 的 agent

### 运行时配置
Plan mode 由 `RunnableConfig.configurable` 中的 `is_plan_mode` 控制：
```python
config = RunnableConfig(
    configurable={
        "is_plan_mode": True,  # 启用 plan mode
        # ... 其他 configurable 选项
    }
)
```

## 关键收益

1. **动态控制**：可按请求启用/禁用 plan mode，无需全局状态
2. **灵活性**：不同对话可采用不同 plan mode 策略
3. **简单性**：无需维护全局配置开关
4. **上下文感知**：可根据任务复杂度、用户偏好等决定是否启用

## 自定义提示词

DeerFlow 为 TodoListMiddleware 提供了自定义 `system_prompt` 与 `tool_description`，与 DeerFlow 整体提示词风格保持一致：

### System Prompt 特性
- 使用 XML 标签（`<todo_list_system>`），与 DeerFlow 主提示词结构一致
- 强调 CRITICAL 规则与最佳实践
- 明确区分“何时使用”与“何时不使用”
- 强调实时更新与任务完成后立即标记

### Tool Description 特性
- 提供详细场景和示例
- 强调简单任务不要使用
- 明确任务状态定义（pending、in_progress、completed）
- 包含完整最佳实践说明
- 包含防止过早标记完成的要求

上述自定义提示词定义在 `_create_todo_list_middleware()`，位置：`/Users/hetao/workspace/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py:57`。

## 说明

- TodoList middleware 使用 LangChain 内置 `TodoListMiddleware`，并配有**DeerFlow 风格自定义提示词**
- 为保持向后兼容，Plan Mode **默认关闭**（`is_plan_mode=False`）
- middleware 位于 `ClarificationMiddleware` 之前，便于在澄清流程中继续进行 todo 管理
- 自定义提示词强调与 DeerFlow 主系统提示词一致的原则（清晰、行动导向、关键规则）
