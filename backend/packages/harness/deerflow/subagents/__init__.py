from .config import SubagentConfig
from .registry import get_available_subagent_names, get_subagent_config, list_subagents

__all__ = [
    "SubagentConfig",
    "SubagentExecutor",
    "SubagentResult",
    "SubagentRuntime",
    "get_available_subagent_names",
    "get_subagent_config",
    "list_subagents",
]


def __getattr__(name: str):
    if name in {"SubagentExecutor", "SubagentResult"}:
        from .executor import SubagentExecutor, SubagentResult

        exports = {
            "SubagentExecutor": SubagentExecutor,
            "SubagentResult": SubagentResult,
        }
        globals().update(exports)
        return exports[name]
    if name == "SubagentRuntime":
        from .runtime import SubagentRuntime

        globals()[name] = SubagentRuntime
        return SubagentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
