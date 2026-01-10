# Code Style Analysis

## Overview

This document analyzes the existing codebase style conventions to guide new code implementation.

## Data Structures

### Preference for `dict` and Simple Types

- The project primarily uses `dict` and simple types for data structures
- `@dataclass` is used for configuration objects (e.g., `Configuration` in `src/config/configuration.py`)
- Pydantic models are used sparingly (mainly in `src/rag/retriever.py` for data validation)

**Example from `src/config/configuration.py`:**
```python
@dataclass(kw_only=True)
class Configuration:
    resources: list[Resource] = field(default_factory=list)
    max_plan_iterations: int = 1
    enable_tool_result_compression: bool = True
    artifact_storage_path: str = "research_artifacts"
```

**Example from `src/utils/json_utils.py`:**
```python
def sanitize_args(args: Any) -> str:
    """Simple function with plain types."""
```

## Naming Conventions

- **Functions and variables**: `snake_case`
- **Classes**: `PascalCase`
- **Private methods**: `_private` prefix
- **Constants**: `UPPER_SNAKE_CASE`

**Examples:**
- `get_recursion_limit()`, `sanitize_tool_response()`, `compress_messages()`
- `ContextManager`, `Configuration`
- `_sanitize_filename_component()`, `_count_message_tokens()`
- `DEFAULT_ARTIFACT_PATH`

## Type Hints

- Python 3.10+ style: `str | Path` instead of `Union[str, Path]`
- Generic types: `list[str]` instead of `List[str]` (but `List` is also used in some files)
- Optional: `Optional[str]` or `str | None`

**Examples:**
```python
def __init__(self, base_path: str | Path = "research_artifacts"):
    ...
```

## Function Structure

### Standard Pattern

```python
def function_name(param: type, optional_param: type = default) -> return_type:
    """
    Brief description.

    Args:
        param: Description
        optional_param: Description

    Returns:
        Description of return value
    """
    # Implementation
```

### Async Pattern

```python
async def async_function_name(param: type) -> return_type:
    """Async function with same docstring style."""
    ...
```

## Logging

**Module-level logger initialization:**
```python
import logging

logger = logging.getLogger(__name__)
```

**Logging usage:**
- `logger.debug()` - Detailed debug information
- `logger.info()` - General information
- `logger.warning()` - Warning messages
- `logger.error()` - Error messages

## Module Structure

### Utility Modules (`src/utils/`)

- Use standalone functions, not classes (unless state management is needed)
- Example: `src/utils/json_utils.py` has functions like `sanitize_args()`, `repair_json_output()`
- Example: `src/utils/context_manager.py` has `ContextManager` class (needs state) and `validate_message_content()` function (stateless)

### Prompts (`src/prompts/`)

- Prompt templates stored as `.md` files in `src/prompts/`
- Loaded via `src/prompts/template.py:get_prompt_template()`
- Not embedded in Python code

## Error Handling

```python
try:
    # Operation
except Exception as e:
    logger.error(f"Descriptive error message: {e}")
    # Handle or raise
```

## Configuration

Configuration uses the `Configuration` dataclass with environment variable fallback:

```python
@dataclass(kw_only=True)
class Configuration:
    field_name: str = field(default="default_value")

    @classmethod
    def from_runnable_config(cls, config: Optional[RunnableConfig] = None) -> "Configuration":
        configurable = config["configurable"] if config and "configurable" in config else {}
        values: dict[str, Any] = {
            f.name: os.environ.get(f.name.upper(), configurable.get(f.name))
            for f in fields(cls) if f.init
        }
        return cls(**{k: v for k, v in values.items() if v})
```

## File I/O Patterns

```python
from pathlib import Path

file_path = Path("path/to/file")
file_path.parent.mkdir(parents=True, exist_ok=True)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
```

## Imports

- Standard library imports first
- Third-party imports second
- Local imports third
- Sorted alphabetically within groups

```python
# Standard library
import json
import logging
from pathlib import Path

# Third-party
from langchain_core.messages import BaseMessage

# Local
from src.config.configuration import Configuration
```

## Summary: Guidelines for Compression Implementation

1. **Use `dict` and simple types** instead of Pydantic models where possible
2. **Follow snake_case naming** for functions and variables
3. **Use Python 3.10+ type hints** (`str | Path` instead of `Union[str, Path]`)
4. **Include docstrings** with Args/Returns sections
5. **Module-level logger**: `logger = logging.getLogger(__name__)`
6. **Use `Configuration` dataclass** for configuration values
7. **Store prompts in `src/prompts/*.md` files**, not embedded in code
8. **Utility functions in `src/utils/compress.py`** following the pattern of `json_utils.py`
