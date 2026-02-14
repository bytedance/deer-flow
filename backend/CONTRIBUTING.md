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
cp extensions_config.example.json extensions_config.json

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
# Terminal 1: LangGraph server
make dev

# Terminal 2: Gateway API
make gateway
```

## Project Structure

```
backend/src/
├── agents/                  # Agent system
│   ├── lead_agent/         # Main agent implementation
│   │   └── agent.py        # Agent factory and creation
│   ├── middlewares/        # Agent middlewares
│   │   ├── thread_data_middleware.py
│   │   ├── sandbox_middleware.py
│   │   ├── title_middleware.py
│   │   ├── uploads_middleware.py
│   │   ├── view_image_middleware.py
│   │   └── clarification_middleware.py
│   └── thread_state.py     # Thread state definition
│
├── gateway/                 # FastAPI Gateway
│   ├── app.py              # FastAPI application
│   └── routers/            # Route handlers
│       ├── models.py       # /api/models endpoints
│       ├── mcp.py          # /api/mcp endpoints
│       ├── skills.py       # /api/skills endpoints
│       ├── artifacts.py    # /api/threads/.../artifacts
│       └── uploads.py      # /api/threads/.../uploads
│
├── sandbox/                 # Sandbox execution
│   ├── __init__.py         # Sandbox interface
│   ├── local.py            # Local sandbox provider
│   └── tools.py            # Sandbox tools (bash, file ops)
│
├── tools/                   # Agent tools
│   └── builtins/           # Built-in tools
│       ├── present_file_tool.py
│       ├── ask_clarification_tool.py
│       └── view_image_tool.py
│
├── mcp/                     # MCP integration
│   └── manager.py          # MCP server management
│
├── models/                  # Model system
│   └── factory.py          # Model factory
│
├── skills/                  # Skills system
│   └── loader.py           # Skills loader
│
├── config/                  # Configuration
│   ├── app_config.py       # Main app config
│   ├── extensions_config.py # Extensions config
│   └── summarization_config.py
│
├── community/               # Community tools
│   ├── tavily/             # Tavily web search
│   ├── jina/               # Jina web fetch
│   ├── firecrawl/          # Firecrawl scraping
│   └── aio_sandbox/        # Docker sandbox
│
├── reflection/              # Dynamic loading
│   └── __init__.py         # Module resolution
│
└── utils/                   # Utilities
    └── __init__.py
```

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
from src.models.factory import create_chat_model

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

1. Create tool in `src/tools/builtins/` or `src/community/`:

```python
# src/tools/builtins/my_tool.py
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
    use: src.tools.builtins.my_tool:my_tool
```

### Adding New Middleware

1. Create middleware in `src/agents/middlewares/`:

```python
# src/agents/middlewares/my_middleware.py
from langchain.agents.middleware import BaseMiddleware
from langchain_core.runnables import RunnableConfig

class MyMiddleware(BaseMiddleware):
    """Middleware description."""

    def transform_state(self, state: dict, config: RunnableConfig) -> dict:
        """Transform the state before agent execution."""
        # Modify state as needed
        return state
```

2. Register in `src/agents/lead_agent/agent.py`:

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

1. Create router in `src/gateway/routers/`:

```python
# src/gateway/routers/my_router.py
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

2. Register in `src/gateway/app.py`:

```python
from src.gateway.routers import my_router

app.include_router(my_router.router)
```

### Configuration Changes

When adding new configuration options:

1. Update `src/config/app_config.py` with new fields
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
