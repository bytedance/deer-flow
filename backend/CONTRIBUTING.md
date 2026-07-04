# Contributing to DeerFlow Backend

Thank you for your interest in contributing to DeerFlow! This document provides guidelines and instructions for contributing to the backend codebase.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Code Style](#code-style)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Architecture Guidelines](#architecture-guidelines)

## Getting Started

### Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Git
- Docker (optional, for Docker sandbox testing)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/deer-flow.git
   cd deer-flow
   ```

## Development Setup

### Install Dependencies

```bash
# From project root
cp config.example.yaml config.yaml

# Install backend dependencies
cd backend
make install
```

### Configure Environment

Set up your API keys for testing:

```bash
export OPENAI_API_KEY="your-api-key"
# Add other keys as needed
```

### Run the Development Server

```bash
# Gateway API + embedded agent runtime
make dev
```

## Project Structure

```
backend/
├── packages/harness/deerflow/  # deerflow-harness package (import: deerflow.*)
│   ├── agents/                 # Agent system
│   │   ├── lead_agent/         # Main agent (agent.py factory, prompt.py)
│   │   ├── middlewares/        # Agent middleware chain
│   │   ├── memory/             # Memory extraction & storage
│   │   └── thread_state.py     # Thread state definition
│   ├── sandbox/                # Sandbox execution
│   │   ├── local/              # Local sandbox provider
│   │   ├── sandbox.py          # Abstract interface
│   │   ├── tools.py            # Sandbox tools (bash, file ops)
│   │   └── middleware.py       # Sandbox lifecycle
│   ├── subagents/              # Subagent delegation
│   ├── tools/builtins/         # Built-in tools
│   ├── mcp/                    # MCP integration
│   ├── models/                 # Model factory
│   ├── skills/                 # Skills system
│   ├── config/                 # Configuration system
│   ├── runtime/                # Embedded run execution (RunManager, StreamBridge)
│   ├── persistence/            # Checkpointer/store engines & schema migrations
│   ├── guardrails/             # Pre-tool-call authorization providers
│   ├── tracing/                # Tracer factory & trace metadata
│   ├── uploads/                # Uploads manager
│   ├── tui/                    # Terminal UI (`deerflow` console script)
│   ├── community/              # Community tools (tavily/, jina_ai/, firecrawl/, …)
│   ├── reflection/             # Dynamic module loading
│   └── utils/                  # Utilities
└── app/                        # FastAPI Gateway + IM channels (import: app.*)
    ├── gateway/                # Gateway API
    │   ├── app.py              # FastAPI application
    │   └── routers/            # Route handlers (threads, models, mcp, skills, uploads, …)
    └── channels/               # IM channel integrations (Feishu, Slack, Telegram, …)
```

See [AGENTS.md](AGENTS.md) for the full module-by-module breakdown.

## Code Style

### Linting and Formatting

We use `ruff` for both linting and formatting:

```bash
# Check for issues
make lint

# Auto-fix and format
make format
```

### Style Guidelines

- **Line length**: 240 characters maximum
- **Python version**: 3.12+ features allowed
- **Type hints**: Use type hints for function signatures
- **Quotes**: Double quotes for strings
- **Indentation**: 4 spaces (no tabs)
- **Imports**: Group by standard library, third-party, local

### Docstrings

Use docstrings for public functions and classes:

```python
def create_chat_model(name: str, thinking_enabled: bool = False) -> BaseChatModel:
    """Create a chat model instance from configuration.

    Args:
        name: The model name as defined in config.yaml
        thinking_enabled: Whether to enable extended thinking

    Returns:
        A configured LangChain chat model instance

    Raises:
        ValueError: If the model name is not found in configuration
    """
    ...
```

## Making Changes

### Branch Naming

Use descriptive branch names:

- `feature/add-new-tool` - New features
- `fix/sandbox-timeout` - Bug fixes
- `docs/update-readme` - Documentation
- `refactor/config-system` - Code refactoring

### Commit Messages

Write clear, concise commit messages:

```
feat: add support for Claude 3.5 model

- Add model configuration in config.yaml
- Update model factory to handle Claude-specific settings
- Add tests for new model
```

Prefix types:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `refactor:` - Code refactoring
- `test:` - Tests
- `chore:` - Build/config changes

## Testing

### Running Tests

```bash
uv run pytest
```

### Writing Tests

Place tests in the `tests/` directory mirroring the source structure:

```
tests/
├── test_models/
│   └── test_factory.py
├── test_sandbox/
│   └── test_local.py
└── test_gateway/
    └── test_models_router.py
```

Example test:

```python
import pytest
from deerflow.models.factory import create_chat_model

def test_create_chat_model_with_valid_name():
    """Test that a valid model name creates a model instance."""
    model = create_chat_model("gpt-4")
    assert model is not None

def test_create_chat_model_with_invalid_name():
    """Test that an invalid model name raises ValueError."""
    with pytest.raises(ValueError):
        create_chat_model("nonexistent-model")
```

## Pull Request Process

### Before Submitting

1. **Ensure tests pass**: `uv run pytest`
2. **Run linter**: `make lint`
3. **Format code**: `make format`
4. **Update documentation** if needed

### PR Description

Include in your PR description:

- **What**: Brief description of changes
- **Why**: Motivation for the change
- **How**: Implementation approach
- **Testing**: How you tested the changes

### Review Process

1. Submit PR with clear description
2. Address review feedback
3. Ensure CI passes
4. Maintainer will merge when approved

## Architecture Guidelines

### Adding New Tools

1. Create tool in `packages/harness/deerflow/tools/builtins/` or `packages/harness/deerflow/community/`:

```python
# packages/harness/deerflow/tools/builtins/my_tool.py
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """Tool description for the agent.

    Args:
        param: Description of the parameter

    Returns:
        Description of return value
    """
    return f"Result: {param}"
```

2. Register in `config.yaml`:

```yaml
tools:
  - name: my_tool
    group: my_group
    use: deerflow.tools.builtins.my_tool:my_tool
```

### Adding New Middleware

1. Create middleware in `packages/harness/deerflow/agents/middlewares/`:

```python
# packages/harness/deerflow/agents/middlewares/my_middleware.py
from langchain.agents.middleware import BaseMiddleware
from langchain_core.runnables import RunnableConfig

class MyMiddleware(BaseMiddleware):
    """Middleware description."""

    def transform_state(self, state: dict, config: RunnableConfig) -> dict:
        """Transform the state before agent execution."""
        # Modify state as needed
        return state
```

2. Register in `packages/harness/deerflow/agents/lead_agent/agent.py`:

```python
middlewares = [
    ThreadDataMiddleware(),
    SandboxMiddleware(),
    MyMiddleware(),  # Add your middleware
    TitleMiddleware(),
    ClarificationMiddleware(),
]
```

### Adding New API Endpoints

1. Create router in `app/gateway/routers/`:

```python
# app/gateway/routers/my_router.py
from fastapi import APIRouter

router = APIRouter(prefix="/my-endpoint", tags=["my-endpoint"])

@router.get("/")
async def get_items():
    """Get all items."""
    return {"items": []}

@router.post("/")
async def create_item(data: dict):
    """Create a new item."""
    return {"created": data}
```

2. Register in `app/gateway/app.py`:

```python
from app.gateway.routers import my_router

app.include_router(my_router.router)
```

### Configuration Changes

When adding new configuration options:

1. Update `packages/harness/deerflow/config/app_config.py` with new fields
2. Add default values in `config.example.yaml`
3. Document in `docs/CONFIGURATION.md`

### MCP Server Integration

To add support for a new MCP server:

1. Add configuration in `extensions_config.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@my-org/mcp-server"],
      "description": "My MCP Server"
    }
  }
}
```

2. Update `extensions_config.example.json` with the new server

### Skills Development

To create a new skill:

1. Create directory in `skills/public/` or `skills/custom/`:

```
skills/public/my-skill/
└── SKILL.md
```

2. Write `SKILL.md` with YAML front matter:

```markdown
---
name: My Skill
description: What this skill does
license: MIT
allowed-tools:
  - read_file
  - write_file
  - bash
---

# My Skill

Instructions for the agent when this skill is enabled...
```

## Questions?

If you have questions about contributing:

1. Check existing documentation in `docs/`
2. Look for similar issues or PRs on GitHub
3. Open a discussion or issue on GitHub

Thank you for contributing to DeerFlow!
