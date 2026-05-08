from typing import Any

from langchain.tools import ToolRuntime

from deerflow.agents.thread_state import ThreadState

# Concrete runtime type used by all DeerFlow tools.
# Using dict[str, Any] for the context parameter instead of the unbound ContextT
# TypeVar prevents PydanticSerializationUnexpectedValue warnings when LangChain
# calls model_dump() on a tool's auto-generated args_schema.
Runtime = ToolRuntime[dict[str, Any], ThreadState]
