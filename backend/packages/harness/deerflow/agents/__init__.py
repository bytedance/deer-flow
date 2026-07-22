from .features import Next, Prev, RuntimeFeatures

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


def __getattr__(name: str):
    if name == "create_deerflow_agent":
        from .factory import create_deerflow_agent

        globals()[name] = create_deerflow_agent
        return create_deerflow_agent
    if name == "make_lead_agent":
        from .lead_agent import make_lead_agent
        from .lead_agent.prompt import prime_enabled_skills_cache

        # LangGraph resolves deerflow.agents:make_lead_agent when registering
        # the graph. Prime at that explicit entrypoint instead of at package
        # import time so lightweight submodules can be imported without pulling
        # in the whole tool/subagent graph.
        prime_enabled_skills_cache()
        globals()[name] = make_lead_agent
        return make_lead_agent
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
