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
    "sanitize_subagent_history",
    "extract_resumable_messages",
    "get_resumable_subagent_task",
    "supersede_and_claim_resumable_task",
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
    if name in {
        "sanitize_subagent_history",
        "extract_resumable_messages",
        "get_resumable_subagent_task",
        "supersede_and_claim_resumable_task",
    }:
        from .recovery import (
            extract_resumable_messages,
            get_resumable_subagent_task,
            sanitize_subagent_history,
            supersede_and_claim_resumable_task,
        )

        recovery_exports = {
            "sanitize_subagent_history": sanitize_subagent_history,
            "extract_resumable_messages": extract_resumable_messages,
            "get_resumable_subagent_task": get_resumable_subagent_task,
            "supersede_and_claim_resumable_task": supersede_and_claim_resumable_task,
        }
        globals().update(recovery_exports)
        return recovery_exports[name]
    if name == "SubagentRuntime":
        from .runtime import SubagentRuntime

        globals()[name] = SubagentRuntime
        return SubagentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
