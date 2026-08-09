"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .coding_agents import (
    CODE_ANALYZER_CONFIG,
    CODE_IMPLEMENTER_CONFIG,
    CODE_REVIEWER_CONFIG,
)
from .general_purpose import GENERAL_PURPOSE_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "CODE_ANALYZER_CONFIG",
    "CODE_IMPLEMENTER_CONFIG",
    "CODE_REVIEWER_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "code-analyzer": CODE_ANALYZER_CONFIG,
    "code-implementer": CODE_IMPLEMENTER_CONFIG,
    "code-reviewer": CODE_REVIEWER_CONFIG,
}
