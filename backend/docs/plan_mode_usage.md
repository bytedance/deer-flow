# Plan Mode with TodoList Middleware

This document describes how to enable and use the Plan Mode feature with TodoList middleware in DeerFlow 2.0.

## Overview

Plan Mode adds a TodoList middleware to the agent, which provides a `write_todos` tool that helps the agent:
- Break down complex tasks into smaller, manageable steps
- Track progress as work progresses
- Provide visibility to users about what's being done

The TodoList middleware is built on LangChain's `TodoListMiddleware`.

## Configuration

### Enabling Plan Mode

Plan mode is controlled via **runtime configuration** through the `is_plan_mode` parameter in the `configurable` section of `RunnableConfig`. This allows you to dynamically enable or disable plan mode on a per-request basis.

```python
from langchain_core.runnables import RunnableConfig
from src.agents.lead_agent.agent import make_lead_agent

# Enable plan mode via runtime configuration
config = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # Enable plan mode
    }
)

# Create agent with plan mode enabled
agent = make_lead_agent(config)
```

### Configuration Options

- **is_plan_mode** (bool): Whether to enable plan mode with TodoList middleware. Default: `False`
  - Pass via `config.get("configurable", {}).get("is_plan_mode", False)`
  - Can be set dynamically for each agent invocation
  - No global configuration needed

## Default Behavior

When plan mode is enabled with default settings, the agent will have access to a `write_todos` tool with the following behavior:

### When to Use TodoList

The agent will use the todo list for:
1. Complex multi-step tasks (3+ distinct steps)
2. Non-trivial tasks requiring careful planning
3. When user explicitly requests a todo list
4. When user provides multiple tasks

### When NOT to Use TodoList

The agent will skip using the todo list for:
1. Single, straightforward tasks
2. Trivial tasks (< 3 steps)
3. Purely conversational or informational requests

### Task States

- **pending**: Task not yet started
- **in_progress**: Currently working on (can have multiple parallel tasks)
- **completed**: Task finished successfully

## Usage Examples

### Basic Usage

```python
from langchain_core.runnables import RunnableConfig
from src.agents.lead_agent.agent import make_lead_agent

# Create agent with plan mode ENABLED
config_with_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "example-thread",
        "thinking_enabled": True,
        "is_plan_mode": True,  # TodoList middleware will be added
    }
)
agent_with_todos = make_lead_agent(config_with_plan_mode)

# Create agent with plan mode DISABLED (default)
config_without_plan_mode = RunnableConfig(
    configurable={
        "thread_id": "another-thread",
        "thinking_enabled": True,
        "is_plan_mode": False,  # No TodoList middleware
    }
)
agent_without_todos = make_lead_agent(config_without_plan_mode)
```

### Dynamic Plan Mode per Request

You can enable/disable plan mode dynamically for different conversations or tasks:

```python
from langchain_core.runnables import RunnableConfig
from src.agents.lead_agent.agent import make_lead_agent

def create_agent_for_task(task_complexity: str):
    """Create agent with plan mode based on task complexity."""
    is_complex = task_complexity in ["high", "very_high"]

    config = RunnableConfig(
        configurable={
            "thread_id": f"task-{task_complexity}",
            "thinking_enabled": True,
            "is_plan_mode": is_complex,  # Enable only for complex tasks
        }
    )

    return make_lead_agent(config)

# Simple task - no TodoList needed
simple_agent = create_agent_for_task("low")

# Complex task - TodoList enabled for better tracking
complex_agent = create_agent_for_task("high")
```

## How It Works

1. When `make_lead_agent(config)` is called, it extracts `is_plan_mode` from `config.configurable`
2. The config is passed to `_build_middlewares(config)`
3. `_build_middlewares()` reads `is_plan_mode` and calls `_create_todo_list_middleware(is_plan_mode)`
4. If `is_plan_mode=True`, a `TodoListMiddleware` instance is created and added to the middleware chain
5. The middleware automatically adds a `write_todos` tool to the agent's toolset
6. The agent can use this tool to manage tasks during execution
7. The middleware handles the todo list state and provides it to the agent

## Architecture

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

## Implementation Details

### Agent Module
- **Location**: `src/agents/lead_agent/agent.py`
- **Function**: `_create_todo_list_middleware(is_plan_mode: bool)` - Creates TodoListMiddleware if plan mode is enabled
- **Function**: `_build_middlewares(config: RunnableConfig)` - Builds middleware chain based on runtime config
- **Function**: `make_lead_agent(config: RunnableConfig)` - Creates agent with appropriate middlewares

### Runtime Configuration
Plan mode is controlled via the `is_plan_mode` parameter in `RunnableConfig.configurable`:
```python
config = RunnableConfig(
    configurable={
        "is_plan_mode": True,  # Enable plan mode
        # ... other configurable options
    }
)
```

## Key Benefits

1. **Dynamic Control**: Enable/disable plan mode per request without global state
2. **Flexibility**: Different conversations can have different plan mode settings
3. **Simplicity**: No need for global configuration management
4. **Context-Aware**: Plan mode decision can be based on task complexity, user preferences, etc.

## Custom Prompts

DeerFlow uses custom `system_prompt` and `tool_description` for the TodoListMiddleware that match the overall DeerFlow prompt style:

### System Prompt Features
- Uses XML tags (`<todo_list_system>`) for structure consistency with DeerFlow's main prompt
- Emphasizes CRITICAL rules and best practices
- Clear "When to Use" vs "When NOT to Use" guidelines
- Focuses on real-time updates and immediate task completion

### Tool Description Features
- Detailed usage scenarios with examples
- Strong emphasis on NOT using for simple tasks
- Clear task state definitions (pending, in_progress, completed)
- Comprehensive best practices section
- Task completion requirements to prevent premature marking

The custom prompts are defined in `_create_todo_list_middleware()` in `/Users/hetao/workspace/deer-flow/backend/src/agents/lead_agent/agent.py:57`.

## Notes

- TodoList middleware uses LangChain's built-in `TodoListMiddleware` with **custom DeerFlow-style prompts**
- Plan mode is **disabled by default** (`is_plan_mode=False`) to maintain backward compatibility
- The middleware is positioned before `ClarificationMiddleware` to allow todo management during clarification flows
- Custom prompts emphasize the same principles as DeerFlow's main system prompt (clarity, action-oriented, critical rules)
