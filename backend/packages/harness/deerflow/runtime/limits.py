"""Runtime recursion and execution budget defaults."""

DEFAULT_RECURSION_LIMIT = 100
DEFAULT_DEEP_AGENT_RECURSION_LIMIT = 1000


def default_recursion_limit(*, subagent_enabled: bool = False) -> int:
    """Return the default LangGraph recursion limit for a run."""
    if subagent_enabled:
        return DEFAULT_DEEP_AGENT_RECURSION_LIMIT
    return DEFAULT_RECURSION_LIMIT
