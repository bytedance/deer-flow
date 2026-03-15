"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .code_reviewer_agent import CODE_REVIEWER_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .literature_agent import LITERATURE_REVIEWER_CONFIG
from .stats_agent import STATISTICAL_ANALYST_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "LITERATURE_REVIEWER_CONFIG",
    "STATISTICAL_ANALYST_CONFIG",
    "CODE_REVIEWER_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "literature-reviewer": LITERATURE_REVIEWER_CONFIG,
    "statistical-analyst": STATISTICAL_ANALYST_CONFIG,
    "code-reviewer": CODE_REVIEWER_CONFIG,
}
