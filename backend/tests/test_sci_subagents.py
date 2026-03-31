"""Tests for sci-research subagent registrations.

Covers:
- All 4 sci subagents (literature-analyzer, data-extractor, report-writer, ov-retriever)
  are correctly defined and registered in BUILTIN_SUBAGENTS
- Each config has required fields and correct types
- task_tool Literal type includes all 4 new subagent types
- Tool allowlists / disallowed lists are sane (no recursive subagent nesting)
- Timeout and max_turns are within expected bounds
"""

import inspect
import typing

import pytest

from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.builtins.data_extractor import DATA_EXTRACTOR_CONFIG
from deerflow.subagents.builtins.literature_analyzer import LITERATURE_ANALYZER_CONFIG
from deerflow.subagents.builtins.ov_retriever import OV_RETRIEVER_CONFIG
from deerflow.subagents.builtins.report_writer import REPORT_WRITER_CONFIG
from deerflow.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCI_CONFIGS = [
    ("literature-analyzer", LITERATURE_ANALYZER_CONFIG),
    ("data-extractor", DATA_EXTRACTOR_CONFIG),
    ("report-writer", REPORT_WRITER_CONFIG),
    ("ov-retriever", OV_RETRIEVER_CONFIG),
]


# ---------------------------------------------------------------------------
# BUILTIN_SUBAGENTS registry
# ---------------------------------------------------------------------------


class TestBuiltinRegistry:
    def test_all_sci_subagents_registered(self):
        for name, _ in SCI_CONFIGS:
            assert name in BUILTIN_SUBAGENTS, f"'{name}' not found in BUILTIN_SUBAGENTS"

    def test_registry_returns_correct_config_objects(self):
        assert BUILTIN_SUBAGENTS["literature-analyzer"] is LITERATURE_ANALYZER_CONFIG
        assert BUILTIN_SUBAGENTS["data-extractor"] is DATA_EXTRACTOR_CONFIG
        assert BUILTIN_SUBAGENTS["report-writer"] is REPORT_WRITER_CONFIG
        assert BUILTIN_SUBAGENTS["ov-retriever"] is OV_RETRIEVER_CONFIG

    def test_all_registered_values_are_subagent_config(self):
        for name, config in BUILTIN_SUBAGENTS.items():
            assert isinstance(config, SubagentConfig), f"'{name}' value is not a SubagentConfig"


# ---------------------------------------------------------------------------
# Per-config field validation
# ---------------------------------------------------------------------------


class TestSciSubagentFields:
    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_name_matches_key(self, name, config):
        assert config.name == name

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_description_nonempty(self, name, config):
        assert config.description and len(config.description.strip()) > 20

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_system_prompt_nonempty(self, name, config):
        assert config.system_prompt and len(config.system_prompt.strip()) > 50

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_task_not_in_allowed_tools(self, name, config):
        """Subagents must not be able to spawn further subagents (no recursive nesting)."""
        if config.tools is not None:
            assert "task" not in config.tools, f"'{name}' allows 'task' tool — recursive nesting not permitted"

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_task_in_disallowed_tools(self, name, config):
        """Explicitly disallow 'task' to enforce no-nesting invariant."""
        assert config.disallowed_tools is not None
        assert "task" in config.disallowed_tools, f"'{name}' should disallow 'task' tool"

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_timeout_positive(self, name, config):
        assert config.timeout_seconds > 0

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_max_turns_positive(self, name, config):
        assert config.max_turns > 0

    @pytest.mark.parametrize("name,config", SCI_CONFIGS)
    def test_model_field_is_string(self, name, config):
        assert isinstance(config.model, str)


# ---------------------------------------------------------------------------
# Per-agent specific expectations from RESEARCH_PLAN.md
# ---------------------------------------------------------------------------


class TestLiteratureAnalyzerConfig:
    def test_timeout_600s(self):
        assert LITERATURE_ANALYZER_CONFIG.timeout_seconds == 600

    def test_max_turns_30(self):
        assert LITERATURE_ANALYZER_CONFIG.max_turns == 30

    def test_has_web_search_tool(self):
        assert LITERATURE_ANALYZER_CONFIG.tools is not None
        assert any("tavily" in t or "web_search" in t for t in LITERATURE_ANALYZER_CONFIG.tools)

    def test_has_read_file_tool(self):
        assert LITERATURE_ANALYZER_CONFIG.tools is not None
        assert "read_file" in LITERATURE_ANALYZER_CONFIG.tools

    def test_output_format_has_five_sections(self):
        """Structured output must include all 5 required analysis fields."""
        prompt = LITERATURE_ANALYZER_CONFIG.system_prompt
        for section in ["Research Question", "Methodology", "Key Findings", "Limitations", "Differentiators"]:
            assert section in prompt, f"Missing section '{section}' in literature-analyzer prompt"


class TestDataExtractorConfig:
    def test_timeout_300s(self):
        assert DATA_EXTRACTOR_CONFIG.timeout_seconds == 300

    def test_max_turns_20(self):
        assert DATA_EXTRACTOR_CONFIG.max_turns == 20

    def test_has_write_file_tool(self):
        assert DATA_EXTRACTOR_CONFIG.tools is not None
        assert "write_file" in DATA_EXTRACTOR_CONFIG.tools

    def test_has_str_replace_tool(self):
        assert DATA_EXTRACTOR_CONFIG.tools is not None
        assert "str_replace" in DATA_EXTRACTOR_CONFIG.tools


class TestReportWriterConfig:
    def test_timeout_900s(self):
        assert REPORT_WRITER_CONFIG.timeout_seconds == 900

    def test_max_turns_40(self):
        assert REPORT_WRITER_CONFIG.max_turns == 40

    def test_has_write_file_tool(self):
        assert REPORT_WRITER_CONFIG.tools is not None
        assert "write_file" in REPORT_WRITER_CONFIG.tools

    def test_supports_citation_formats(self):
        """Prompt must document at least APA and IEEE citation formats."""
        prompt = REPORT_WRITER_CONFIG.system_prompt
        for fmt in ["APA", "IEEE"]:
            assert fmt in prompt, f"Missing citation format '{fmt}' in report-writer prompt"


class TestOvRetrieverConfig:
    def test_timeout_180s(self):
        assert OV_RETRIEVER_CONFIG.timeout_seconds == 180

    def test_max_turns_15(self):
        assert OV_RETRIEVER_CONFIG.max_turns == 15

    def test_uses_bash_only(self):
        """ov-retriever uses bash for all OV operations."""
        assert OV_RETRIEVER_CONFIG.tools == ["bash"]

    def test_prompt_documents_ov_commands(self):
        """Prompt must document ov find, ov read, ov ls commands."""
        prompt = OV_RETRIEVER_CONFIG.system_prompt
        for cmd in ["ov find", "ov read", "ov ls"]:
            assert cmd in prompt, f"Missing OV command '{cmd}' in ov-retriever prompt"


# ---------------------------------------------------------------------------
# task_tool Literal type includes all sci subagent types
# ---------------------------------------------------------------------------


class TestTaskToolLiteral:
    def _get_subagent_type_args(self):
        """Extract the allowed values from task_tool's subagent_type parameter."""
        from deerflow.tools.builtins.task_tool import task_tool

        # The tool wraps a function; get the underlying function signature
        func = task_tool.func if hasattr(task_tool, "func") else task_tool
        sig = inspect.signature(func)
        param = sig.parameters.get("subagent_type")
        assert param is not None, "task_tool has no 'subagent_type' parameter"

        # Unwrap Annotated if present
        annotation = param.annotation
        if typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]

        # Must be a Literal type
        origin = typing.get_origin(annotation)
        assert origin is typing.Literal, f"subagent_type annotation is not Literal, got {annotation}"
        return typing.get_args(annotation)

    def test_literature_analyzer_in_literal(self):
        assert "literature-analyzer" in self._get_subagent_type_args()

    def test_data_extractor_in_literal(self):
        assert "data-extractor" in self._get_subagent_type_args()

    def test_report_writer_in_literal(self):
        assert "report-writer" in self._get_subagent_type_args()

    def test_ov_retriever_in_literal(self):
        assert "ov-retriever" in self._get_subagent_type_args()

    def test_original_agents_still_present(self):
        args = self._get_subagent_type_args()
        assert "general-purpose" in args
        assert "bash" in args
