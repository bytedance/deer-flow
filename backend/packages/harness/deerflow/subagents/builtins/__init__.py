"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .data_extractor import DATA_EXTRACTOR_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .literature_analyzer import LITERATURE_ANALYZER_CONFIG
from .ov_retriever import OV_RETRIEVER_CONFIG
from .report_writer import REPORT_WRITER_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "LITERATURE_ANALYZER_CONFIG",
    "DATA_EXTRACTOR_CONFIG",
    "REPORT_WRITER_CONFIG",
    "OV_RETRIEVER_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "literature-analyzer": LITERATURE_ANALYZER_CONFIG,
    "data-extractor": DATA_EXTRACTOR_CONFIG,
    "report-writer": REPORT_WRITER_CONFIG,
    "ov-retriever": OV_RETRIEVER_CONFIG,
}
