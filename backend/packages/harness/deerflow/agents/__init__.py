from typing import TYPE_CHECKING, Any

from .features import Next, Prev, RuntimeFeatures

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

__all__ = [
    "create_deerflow_agent",
    "RuntimeFeatures",
    "Next",
    "Prev",
    "make_lead_agent",
    "SandboxState",
    "DeltaThreadState",
    "ThreadState",
]


def make_lead_agent(config: "RunnableConfig") -> Any:
    """Build the lead graph while keeping package-root imports lightweight.

    LangGraph Server resolves configured graph factories directly from a
    module's ``__dict__``, so this entrypoint must be a concrete module-level
    function rather than a value supplied only through ``__getattr__``.
    """
    from .lead_agent import make_lead_agent as factory
    from .lead_agent.prompt import prime_enabled_skills_cache

    prime_enabled_skills_cache()
    return factory(config)


def __getattr__(name: str):
    if name == "create_deerflow_agent":
        from .factory import create_deerflow_agent

        globals()[name] = create_deerflow_agent
        return create_deerflow_agent
    if name in {"DeltaThreadState", "SandboxState", "ThreadState"}:
        from .thread_state import DeltaThreadState, SandboxState, ThreadState

        exports = {
            "DeltaThreadState": DeltaThreadState,
            "SandboxState": SandboxState,
            "ThreadState": ThreadState,
        }
        globals().update(exports)
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
