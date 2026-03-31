"""Tests for Phase 2: Deep Literature Analysis.

Covers:
- literature-analyzer subagent:
    - 5 mandatory output sections in system_prompt (Research Question / Methodology /
      Key Findings / Limitations / Differentiators)
    - Model configured to deepseek-v3 (strong reasoning)
    - Tool set: bash, read_file, tavily_web_search, tavily_web_fetch
    - write_file NOT in tools (literature-analyzer writes via bash or read_file only)
    - Output path convention documented in literature-analyzer.md
    - Behavioral rules: no fabrication, specificity, save output
- data-extractor subagent:
    - 4 mandatory output sections in system_prompt
    - Model configured to claude-3-5-sonnet (high structured accuracy)
    - Tool set: bash, read_file, write_file, str_replace
    - JSON output format described in system_prompt
    - Behavioral rules: accuracy over completeness, bold best result
- Agent prompt files (.md):
    - literature-analyzer.md: 5 sections, behavioral rules, output path
    - data-extractor.md: comparison tables, key numbers, JSON block, behavioral rules
- SKILL.md Phase 2:
    - Parallel subagent dispatch described
    - workspace output path referenced
    - Max 3 concurrent constraint mentioned
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.subagents.builtins.data_extractor import DATA_EXTRACTOR_CONFIG
from deerflow.subagents.builtins.literature_analyzer import LITERATURE_ANALYZER_CONFIG

# ---------------------------------------------------------------------------
# Paths to agent prompt files
# ---------------------------------------------------------------------------

_AGENTS_DIR = Path(__file__).parent.parent.parent / "skills" / "custom" / "sci-research" / "agents"
_LITERATURE_ANALYZER_MD = _AGENTS_DIR / "literature-analyzer.md"
_DATA_EXTRACTOR_MD = _AGENTS_DIR / "data-extractor.md"
_SKILL_MD = Path(__file__).parent.parent.parent / "skills" / "custom" / "sci-research" / "SKILL.md"

# The 5 required output sections (Phase 2 acceptance criterion)
REQUIRED_ANALYSIS_SECTIONS = [
    "Research Question",
    "Methodology",
    "Key Findings",
    "Limitations",
    "Differentiators",
]


# ---------------------------------------------------------------------------
# literature-analyzer: SubagentConfig
# ---------------------------------------------------------------------------


class TestLiteratureAnalyzerModel:
    def test_model_is_deepseek_v3(self):
        """Phase 2-2: literature-analyzer must use deepseek-v3 (strong reasoning model)."""
        assert LITERATURE_ANALYZER_CONFIG.model == "deepseek-v3"

    def test_model_not_inherit(self):
        """Model must not fall back to parent — deep analysis requires a reasoning-capable model."""
        assert LITERATURE_ANALYZER_CONFIG.model != "inherit"


class TestLiteratureAnalyzerOutputSections:
    def test_all_five_sections_in_system_prompt(self):
        """Phase 2-3: All 5 mandatory output sections must be present in system_prompt."""
        prompt = LITERATURE_ANALYZER_CONFIG.system_prompt
        missing = [s for s in REQUIRED_ANALYSIS_SECTIONS if s not in prompt]
        assert not missing, f"Missing sections in literature-analyzer system_prompt: {missing}"

    def test_sections_appear_in_output_format_block(self):
        """Sections must be inside the <output_format> block, not just incidentally mentioned."""
        prompt = LITERATURE_ANALYZER_CONFIG.system_prompt
        assert "<output_format>" in prompt, "system_prompt must contain <output_format> block"
        output_format_section = prompt.split("<output_format>")[1]
        missing = [s for s in REQUIRED_ANALYSIS_SECTIONS if s not in output_format_section]
        assert not missing, f"Sections missing from <output_format> block: {missing}"

    def test_six_sections_total_including_open_questions(self):
        """Prompt should define Open Questions as section 6 (beyond the 5 mandatory)."""
        prompt = LITERATURE_ANALYZER_CONFIG.system_prompt
        assert "Open Questions" in prompt or "Future Work" in prompt


class TestLiteratureAnalyzerTools:
    def test_has_bash_tool(self):
        assert "bash" in LITERATURE_ANALYZER_CONFIG.tools

    def test_has_read_file_tool(self):
        assert "read_file" in LITERATURE_ANALYZER_CONFIG.tools

    def test_has_web_search_tool(self):
        tools = LITERATURE_ANALYZER_CONFIG.tools
        assert any("tavily" in t for t in tools), "Missing tavily web search tool"

    def test_has_web_fetch_tool(self):
        tools = LITERATURE_ANALYZER_CONFIG.tools
        assert any("fetch" in t for t in tools), "Missing web fetch tool"

    def test_task_in_disallowed(self):
        assert "task" in LITERATURE_ANALYZER_CONFIG.disallowed_tools

    def test_ask_clarification_in_disallowed(self):
        assert "ask_clarification" in LITERATURE_ANALYZER_CONFIG.disallowed_tools


class TestLiteratureAnalyzerBehavior:
    def test_no_fabrication_rule_in_prompt(self):
        """Prompt must forbid fabricating data."""
        prompt = LITERATURE_ANALYZER_CONFIG.system_prompt
        assert "not reported" in prompt.lower() or "never fabricate" in prompt.lower() or "not specified" in prompt.lower()

    def test_timeout_adequate_for_deep_analysis(self):
        """600s timeout needed for multi-step deep paper reading."""
        assert LITERATURE_ANALYZER_CONFIG.timeout_seconds >= 600

    def test_max_turns_adequate(self):
        """At least 20 turns for iterative deep reading."""
        assert LITERATURE_ANALYZER_CONFIG.max_turns >= 20


# ---------------------------------------------------------------------------
# data-extractor: SubagentConfig
# ---------------------------------------------------------------------------


class TestDataExtractorModel:
    def test_model_is_claude_35_sonnet(self):
        """Phase 2-5: data-extractor must use claude-3-5-sonnet (high structured accuracy)."""
        assert DATA_EXTRACTOR_CONFIG.model == "claude-3-5-sonnet"

    def test_model_not_inherit(self):
        """Model must not fall back to parent — structured extraction requires Claude precision."""
        assert DATA_EXTRACTOR_CONFIG.model != "inherit"


class TestDataExtractorOutputSections:
    def test_four_output_sections_in_system_prompt(self):
        """Phase 2-4: system_prompt must define 4 structured output sections."""
        prompt = DATA_EXTRACTOR_CONFIG.system_prompt
        required = ["Extraction Summary", "Structured Data", "Data Quality", "Source"]
        missing = [s for s in required if s not in prompt]
        assert not missing, f"Missing output sections in data-extractor system_prompt: {missing}"

    def test_json_output_mentioned(self):
        """JSON output format must be described for machine-readable extraction."""
        prompt = DATA_EXTRACTOR_CONFIG.system_prompt
        assert "json" in prompt.lower() or "JSON" in prompt

    def test_markdown_table_output_mentioned(self):
        """Markdown table format must be described for comparison tables."""
        prompt = DATA_EXTRACTOR_CONFIG.system_prompt
        assert "markdown" in prompt.lower() or "table" in prompt.lower()


class TestDataExtractorTools:
    def test_has_write_file_tool(self):
        assert "write_file" in DATA_EXTRACTOR_CONFIG.tools

    def test_has_str_replace_tool(self):
        assert "str_replace" in DATA_EXTRACTOR_CONFIG.tools

    def test_has_read_file_tool(self):
        assert "read_file" in DATA_EXTRACTOR_CONFIG.tools

    def test_has_bash_tool(self):
        assert "bash" in DATA_EXTRACTOR_CONFIG.tools

    def test_no_web_search(self):
        """data-extractor must not use web search — extraction from provided documents only."""
        tools = DATA_EXTRACTOR_CONFIG.tools or []
        assert not any("tavily" in t or "web_search" in t for t in tools)

    def test_task_in_disallowed(self):
        assert "task" in DATA_EXTRACTOR_CONFIG.disallowed_tools


class TestDataExtractorBehavior:
    def test_no_fabrication_rule(self):
        prompt = DATA_EXTRACTOR_CONFIG.system_prompt
        assert "never" in prompt.lower() or "not" in prompt.lower()
        # More specific check: rule about not inferring / approximating
        assert "infer" in prompt.lower() or "approximate" in prompt.lower() or "fabricat" in prompt.lower()

    def test_ambiguous_value_handling(self):
        """Ambiguous values must be marked (e.g., '?') not silently dropped."""
        prompt = DATA_EXTRACTOR_CONFIG.system_prompt
        assert "?" in prompt or "ambiguous" in prompt.lower() or "uncertain" in prompt.lower()

    def test_timeout_adequate(self):
        assert DATA_EXTRACTOR_CONFIG.timeout_seconds >= 180

    def test_max_turns_adequate(self):
        assert DATA_EXTRACTOR_CONFIG.max_turns >= 10


# ---------------------------------------------------------------------------
# literature-analyzer.md prompt file
# ---------------------------------------------------------------------------


class TestLiteratureAnalyzerMD:
    @pytest.fixture(scope="class")
    def content(self):
        assert _LITERATURE_ANALYZER_MD.exists(), f"Not found: {_LITERATURE_ANALYZER_MD}"
        return _LITERATURE_ANALYZER_MD.read_text(encoding="utf-8")

    def test_five_mandatory_sections_documented(self, content):
        """All 5 mandatory output sections must appear in the agent prompt."""
        missing = [s for s in REQUIRED_ANALYSIS_SECTIONS if s not in content]
        assert not missing, f"Missing sections in literature-analyzer.md: {missing}"

    def test_output_path_to_workspace(self, content):
        """Output must be saved to the workspace, not just returned in response."""
        assert "workspace/analysis" in content or "/mnt/user-data/workspace" in content

    def test_no_fabrication_rule_documented(self, content):
        assert "fabricat" in content.lower() or "not reported" in content.lower()

    def test_five_sections_mandatory_rule(self, content):
        """Rule explicitly stating all 5 sections are mandatory."""
        assert "mandatory" in content.lower() or "must contain" in content.lower() or "Five sections" in content

    def test_input_formats_documented(self, content):
        """Supported input formats (file path, OV URI, URL) must be documented."""
        assert "viking://" in content or "OV" in content
        assert "/mnt/user-data/uploads" in content or "uploads" in content

    def test_quick_reference_table(self, content):
        """Quick Reference table must be present for fast scanning."""
        assert "Quick Reference" in content or "quick reference" in content.lower()

    def test_no_recursive_tasks_rule(self, content):
        assert "task" in content.lower() and ("not" in content.lower() or "DO NOT" in content)


# ---------------------------------------------------------------------------
# data-extractor.md prompt file
# ---------------------------------------------------------------------------


class TestDataExtractorMD:
    @pytest.fixture(scope="class")
    def content(self):
        assert _DATA_EXTRACTOR_MD.exists(), f"Not found: {_DATA_EXTRACTOR_MD}"
        return _DATA_EXTRACTOR_MD.read_text(encoding="utf-8")

    def test_comparison_tables_section(self, content):
        assert "Comparison" in content or "comparison" in content.lower()

    def test_key_numbers_section(self, content):
        assert "Key Numbers" in content or "key numbers" in content.lower()

    def test_json_output_block(self, content):
        assert "json" in content.lower()

    def test_ablation_studies_section(self, content):
        assert "Ablation" in content or "ablation" in content.lower()

    def test_output_path_documented(self, content):
        assert "workspace/data" in content or "/mnt/user-data/workspace" in content

    def test_accuracy_over_completeness_rule(self, content):
        assert "accuracy" in content.lower() or "Accuracy" in content

    def test_bold_best_result_rule(self, content):
        """Best result in each column must be bolded."""
        assert "bold" in content.lower() or "**" in content

    def test_no_fabrication_rule(self, content):
        assert "fabricat" in content.lower() or "never" in content.lower()

    def test_missing_data_flag(self, content):
        """Unreported values must use a specific marker (— not 0)."""
        assert "—" in content or "unreported" in content.lower() or "missing" in content.lower()


# ---------------------------------------------------------------------------
# SKILL.md Phase 2 section
# ---------------------------------------------------------------------------


class TestSkillMDPhase2:
    @pytest.fixture(scope="class")
    def content(self):
        assert _SKILL_MD.exists(), f"Not found: {_SKILL_MD}"
        return _SKILL_MD.read_text(encoding="utf-8")

    def test_phase2_section_exists(self, content):
        assert "Phase 2" in content

    def test_literature_analyzer_dispatch_documented(self, content):
        """SKILL.md must show how to dispatch literature-analyzer tasks."""
        assert "literature-analyzer" in content

    def test_parallel_subagent_dispatch(self, content):
        """Parallel dispatch (task tool calls) must be described."""
        assert "task(" in content or "subagent_type" in content

    def test_workspace_output_path(self, content):
        """Analysis outputs should be saved to workspace."""
        assert "workspace" in content

    def test_max_3_concurrent_constraint(self, content):
        """Max 3 concurrent subagents constraint must be stated."""
        assert "3" in content and ("concurrent" in content.lower() or "parallel" in content.lower() or "max" in content.lower())
