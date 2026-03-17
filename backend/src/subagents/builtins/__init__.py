"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .blot_auditor_agent import BLOT_AUDITOR_CONFIG
from .code_reviewer_agent import CODE_REVIEWER_CONFIG
from .data_scientist_agent import DATA_SCIENTIST_CONFIG
from .experiment_designer_agent import EXPERIMENT_DESIGNER_CONFIG
from .facs_auditor_agent import FACS_AUDITOR_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .literature_agent import LITERATURE_REVIEWER_CONFIG
from .spectrum_auditor_agent import SPECTRUM_AUDITOR_CONFIG
from .stats_agent import STATISTICAL_ANALYST_CONFIG
from .tsne_auditor_agent import TSNE_AUDITOR_CONFIG
from .writer_agent import WRITER_AGENT_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "LITERATURE_REVIEWER_CONFIG",
    "STATISTICAL_ANALYST_CONFIG",
    "CODE_REVIEWER_CONFIG",
    "DATA_SCIENTIST_CONFIG",
    "EXPERIMENT_DESIGNER_CONFIG",
    "FACS_AUDITOR_CONFIG",
    "BLOT_AUDITOR_CONFIG",
    "TSNE_AUDITOR_CONFIG",
    "SPECTRUM_AUDITOR_CONFIG",
    "WRITER_AGENT_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "literature-reviewer": LITERATURE_REVIEWER_CONFIG,
    "statistical-analyst": STATISTICAL_ANALYST_CONFIG,
    "code-reviewer": CODE_REVIEWER_CONFIG,
    "data-scientist": DATA_SCIENTIST_CONFIG,
    "experiment-designer": EXPERIMENT_DESIGNER_CONFIG,
    "facs-auditor": FACS_AUDITOR_CONFIG,
    "blot-auditor": BLOT_AUDITOR_CONFIG,
    "tsne-auditor": TSNE_AUDITOR_CONFIG,
    "spectrum-auditor": SPECTRUM_AUDITOR_CONFIG,
    "writer-agent": WRITER_AGENT_CONFIG,
}
