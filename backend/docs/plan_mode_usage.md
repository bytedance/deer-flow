# Plan Mode with TodoList Middleware（计划模式使用指南）

> **文档目的**：说明如何在DeerFlow 2.0中启用和使用Plan Mode功能

## 概述

**什么是Plan Mode**：

Plan Mode 为代理添加 TodoList 中间件，提供 `write_todos` 工具，帮助代理：
- 将复杂任务分解为更小、可管理的步骤
- 在工作进展中跟踪进度
- 向用户提供任务执行的可视性

**为什么需要Plan Mode**：
- **任务分解**：复杂任务需要系统化的分步处理
- **进度透明**：用户可以实时看到代理正在做什么
- **质量控制**：通过待办事项确保不遗漏重要步骤

**技术实现**：
- TodoList 中间件基于 LangChain 的 `TodoListMiddleware`
- 通过运行时配置动态启用/禁用
- 使用自定义的DeerFlow风格提示词

## 配置

### 启用 Plan Mode

Plan mode 通过 **运行时配置** 控制，使用 `RunnableConfig` 的 `configurable` 部分中的 `is_plan_mode` 参数。这允许你按请求动态启用或禁用计划模式。

**为什么使用运行时配置**：
- **灵活性**：不同任务可以有不同设置
- **无全局状态**：不需要管理全局配置
- **按需启用**：只为复杂任务启用，简单任务不干扰

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

# 通过运行时配置启用计划模式
config = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # 启用计划模式
    }
)

# 创建启用了计划模式的代理
agent = make_lead_agent(config)
```

### 配置选项

- **is_plan_mode** (bool): 是否启用带 TodoList 中间件的计划模式。默认值：`False`
  - 通过 `config.get("configurable", {}).get("is_plan_mode", False)` 传递
  - 可以为每次代理调用动态设置
  - 不需要全局配置

## 默认行为

当启用计划模式时，代理将可以访问具有以下行为的 `write_todos` 工具：

### 何时使用 TodoList

**代理将在以下情况使用待办事项列表**：
1. 复杂的多步骤任务（3个或更多不同的步骤）
2. 需要仔细规划的非平凡任务
3. 用户明确请求待办事项列表时
4. 用户提供多个任务时

**为什么这样设计**：
- 避免简单任务的过度工程化
- 只在真正需要时提供结构化任务跟踪
- 保持用户体验的流畅性

### 何时不使用 TodoList

**代理将跳过使用待办事项列表**：
1. 单个、直接的任务
2. 平凡任务（少于3个步骤）
3. 纯对话或信息性请求

### 任务状态

- **pending**（待处理）：任务尚未开始
- **in_progress**（进行中）：当前正在工作（可以有多个并行任务）
- **completed**（已完成）：任务已成功完成

**为什么允许并行进行中的任务**：
- 某些任务可以并行执行（如下载多个文件）
- 更真实地反映实际工作流程
- 提高执行效率

## 使用示例

### 基本用法

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

# 创建启用计划模式的代理
config_with_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # TodoList 中间件将被添加
    }
)
agent_with_todos = make_lead_agent(config_with_plan_mode)

# 创建禁用计划模式的代理（默认）
config_without_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "another-thread",
        "thinking_enabled": True,
        "is_plan_mode": False,  # 没有 TodoList 中间件
    }
)
agent_without_todos = make_lead_agent(config_without_plan_mode)
```

### 按请求动态启用计划模式

你可以为不同的对话或任务动态启用/禁用计划模式：

```python
from langchain_core.runnables import RunnableConfig
from deerflow.agents.lead_agent.agent import make_lead_agent

def create_agent_for_task(task_complexity: str):
    """根据任务复杂度创建代理。"""
    is_complex = task_complexity in ["high", "very_high"]

    config = RunnableConfig(
        configurable={
            "thread_id": f"task-{task_complexity}",
            "thinking_enabled": True,
            "is_plan_mode": is_complex,  # 仅对复杂任务启用
        }
    )

    return make_lead_agent(config)

# 简单任务 - 不需要 TodoList
simple_agent = create_agent_for_task("low")

# 复杂任务 - 启用 TodoList 以更好地跟踪
complex_agent = create_agent_for_task("high")
```

**为什么这样设计**：
- **自适应**：根据任务复杂度自动调整行为
- **资源优化**：简单任务不消耗额外资源
- **用户友好**：复杂任务自动提供更好的可视化

## 工作原理

**执行流程**：

1. 调用 `make_lead_agent(config)` 时，从 `config.configurable` 提取 `is_plan_mode`
2. 配置传递给 `_build_middlewares(config)`
3. `_build_middlewares()` 读取 `is_plan_mode` 并调用 `_create_todo_list_middleware(is_plan_mode)`
4. 如果 `is_plan_mode=True`，创建 `TodoListMiddleware` 实例并添加到中间件链
5. 中间件自动将 `write_todos` 工具添加到代理的工具集
6. 代理可以在执行期间使用此工具管理任务
7. 中间件处理待办事项列表状态并将其提供给代理

**架构设计**：

```
make_lead_agent(config)
  │
  ├─> 提取: is_plan_mode = config.configurable.get("is_plan_mode", False)
  │
  └─> _build_middlewares(config)
        │
        ├─> ThreadDataMiddleware
        ├─> SandboxMiddleware
        ├─> SummarizationMiddleware (如果通过全局配置启用)
        ├─> TodoListMiddleware (如果 is_plan_mode=True) ← 新增
        ├─> TitleMiddleware
        └─> ClarificationMiddleware
```

**为什么这样设计架构**：
- **模块化**：每个中间件独立，易于测试和维护
- **可扩展**：添加新中间件不影响现有代码
- **配置驱动**：行为由配置决定，不需要修改代码

## 实现细节

### 代理模块

- **位置**：`packages/harness/deerflow/agents/lead_agent/agent.py`
- **函数**：`_create_todo_list_middleware(is_plan_mode: bool)` - 如果启用计划模式，创建TodoListMiddleware
- **函数**：`_build_middlewares(config: RunnableConfig)` - 基于运行时配置构建中间件链
- **函数**：`make_lead_agent(config: RunnableConfig)` - 创建具有适当中间件的代理

### 运行时配置

计划模式通过 `RunnableConfig.configurable` 中的 `is_plan_mode` 参数控制：

```python
config = RunnableConfig(
    configurable={
        "is_plan_mode": True,  # 启用计划模式
        # ... 其他可配置选项
    }
)
```

## 关键优势

1. **动态控制**：按请求启用/禁用计划模式，无需全局状态
2. **灵活性**：不同对话可以有不同的计划模式设置
3. **简单性**：无需全局配置管理
4. **上下文感知**：计划模式决策可以基于任务复杂度、用户偏好等

**为什么这样设计优势**：
- **无侵入性**：不影响现有代码和行为
- **按需使用**：只在真正需要时启用
- **易于调试**：可以轻松对比启用和禁用的行为

## 自定义提示词

DeerFlow 为 TodoListMiddleware 使用自定义的 `system_prompt` 和 `tool_description`，与整体DeerFlow提示词风格匹配：

### 系统提示词特性

- 使用XML标签（`<todo_list_system>`）保持与DeerFlow主提示词的结构一致性
- 强调关键规则和最佳实践
- 清晰的"何时使用"与"何时不使用"指南
- 专注于实时更新和即时任务完成

### 工具描述特性

- 带示例的详细使用场景
- 强调不要用于简单任务
- 清晰的任务状态定义（pending、in_progress、completed）
- 全面的最佳实践部分
- 任务完成要求，防止过早标记

**为什么使用自定义提示词**：
- **品牌一致性**：与DeerFlow整体风格保持一致
- **行为优化**：针对DeerFlow的特定用例优化
- **用户体验**：提供更可预测的代理行为

自定义提示词定义在 `/Users/hetao/workspace/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py:57` 的 `_create_todo_list_middleware()` 中。

## 注意事项

- TodoList 中间件使用 LangChain 内置的 `TodoListMiddleware` 配合**自定义DeerFlow风格提示词**
- 计划模式**默认禁用**（`is_plan_mode=False`）以保持向后兼容性
- 中间件位于 `ClarificationMiddleware` 之前，允许在澄清流程期间管理待办事项
- 自定义提示词强调与DeerFlow主系统提示词相同的原则（清晰、行动导向、关键规则）

**为什么默认禁用**：
- **向后兼容**：不影响现有用户的使用体验
- **性能考虑**：不需要的额外开销
- **渐进式采用**：用户可以按需启用
