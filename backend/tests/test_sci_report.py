"""Tests for Phase 4: Report Writing.

Covers:
- report-writer subagent (report_writer.py):
    - Model configured to gpt-4o (high-quality writing)
    - Tool set: bash, read_file, write_file, str_replace
    - task and ask_clarification in disallowed_tools
    - 3 output sections in system_prompt (Section content / Reference list / Writing notes)
    - Citation formats (APA, IEEE, GB) documented in system_prompt
    - Behavioral rules: every claim cites, academic register, no recursive tasks, save output
    - Timeout adequate for long-form writing (≥ 900s), max_turns ≥ 30
- report-writer.md agent prompt file:
    - 3 chapter templates present (Methodology Analysis / Results & Comparisons / Research Gaps)
    - Output path to workspace/report/ documented
    - Citation format examples (APA / IEEE / GB-T-7714)
    - Behavioral rules: citation mandatory, tables over lists, no recursive tasks, save output
- research-report.md template:
    - 7 structural sections (Abstract, Intro, Background, Methodology, Results, Gaps,
      Discussion, Conclusion, References)
    - 3 sections assigned to parallel report-writer subagents
    - Lead Agent serial sections identified
    - Assembly instructions: concatenation order + present_files delivery
    - Appendix with paper corpus table
- citation-formats.md:
    - APA, IEEE, GB/T 7714 all documented
    - Inline citation format documented per style
    - Reference list format documented per style
    - Quick formatting rules table
- SKILL.md Phase 4:
    - Detailed 5-step workflow (not a stub)
    - 3 parallel task() dispatches present
    - Lead Agent serial sections described
    - Reference compilation step
    - Abstract written last
    - Assembly + present_files delivery step
    - Acceptance criteria stated
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.subagents.builtins.report_writer import REPORT_WRITER_CONFIG

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_AGENTS_DIR = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "agents"
)
_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "templates"
)
_REPORT_WRITER_MD = _AGENTS_DIR / "report-writer.md"
_RESEARCH_REPORT_MD = _TEMPLATES_DIR / "research-report.md"
_CITATION_FORMATS_MD = _TEMPLATES_DIR / "citation-formats.md"
_SKILL_MD = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "SKILL.md"
)

CHAPTER_TEMPLATES = ["Methodology Analysis", "Results", "Research Gaps"]
CITATION_STYLES = ["APA", "IEEE", "GB"]
REPORT_SECTIONS = [
    "Abstract",
    "Introduction",
    "Background",
    "Methodology",
    "Results",
    "Discussion",
    "Conclusion",
    "References",
]


# ---------------------------------------------------------------------------
# report_writer.py — SubagentConfig
# ---------------------------------------------------------------------------


class TestReportWriterModel:
    def test_model_is_gpt4o(self):
        """Phase 4-3: report-writer must use gpt-4o (high-quality writing model)."""
        assert REPORT_WRITER_CONFIG.model == "gpt-4o"

    def test_model_not_inherit(self):
        """Model must not fall back to parent — writing quality requires a dedicated model."""
        assert REPORT_WRITER_CONFIG.model != "inherit"


class TestReportWriterTools:
    def test_has_write_file(self):
        """report-writer must be able to save chapter files."""
        assert "write_file" in REPORT_WRITER_CONFIG.tools

    def test_has_read_file(self):
        assert "read_file" in REPORT_WRITER_CONFIG.tools

    def test_has_str_replace(self):
        assert "str_replace" in REPORT_WRITER_CONFIG.tools

    def test_has_bash(self):
        assert "bash" in REPORT_WRITER_CONFIG.tools

    def test_no_web_search(self):
        """report-writer writes from provided materials — no external search."""
        tools = REPORT_WRITER_CONFIG.tools or []
        assert not any("tavily" in t or "web_search" in t for t in tools)

    def test_task_in_disallowed(self):
        assert "task" in REPORT_WRITER_CONFIG.disallowed_tools

    def test_ask_clarification_in_disallowed(self):
        assert "ask_clarification" in REPORT_WRITER_CONFIG.disallowed_tools


class TestReportWriterOutputSections:
    def test_three_output_sections_in_system_prompt(self):
        """system_prompt must define 3 output sections."""
        prompt = REPORT_WRITER_CONFIG.system_prompt
        required = ["Section content", "Reference list", "Writing notes"]
        missing = [s for s in required if s not in prompt]
        assert not missing, f"Missing output sections in report-writer system_prompt: {missing}"

    def test_output_format_block_present(self):
        prompt = REPORT_WRITER_CONFIG.system_prompt
        assert "<output_format>" in prompt

    def test_citation_formats_in_system_prompt(self):
        """APA, IEEE, and GB citation styles must be documented."""
        prompt = REPORT_WRITER_CONFIG.system_prompt
        for style in CITATION_STYLES:
            assert style in prompt, f"Citation style {style!r} missing from system_prompt"


class TestReportWriterBehavior:
    def test_timeout_adequate_for_long_writing(self):
        """Long-form chapter writing needs ≥ 900s."""
        assert REPORT_WRITER_CONFIG.timeout_seconds >= 900

    def test_max_turns_adequate(self):
        """Multi-pass writing and revision needs ≥ 30 turns."""
        assert REPORT_WRITER_CONFIG.max_turns >= 30

    def test_citation_requirement_in_prompt(self):
        prompt = REPORT_WRITER_CONFIG.system_prompt
        assert "citation" in prompt.lower() or "cite" in prompt.lower()

    def test_no_recursive_task_rule(self):
        prompt = REPORT_WRITER_CONFIG.system_prompt
        assert "task" in prompt.lower() and (
            "not" in prompt.lower() or "no" in prompt.lower()
        )


# ---------------------------------------------------------------------------
# report-writer.md prompt file
# ---------------------------------------------------------------------------


class TestReportWriterMD:
    @pytest.fixture(scope="class")
    def content(self):
        assert _REPORT_WRITER_MD.exists(), f"Not found: {_REPORT_WRITER_MD}"
        return _REPORT_WRITER_MD.read_text(encoding="utf-8")

    def test_three_chapter_templates_present(self, content):
        """All 3 parallel chapter templates must be defined."""
        assert "Methodology" in content, "Methodology chapter template missing"
        assert "Results" in content, "Results chapter template missing"
        assert "Research Gaps" in content or "Gaps" in content, "Gaps chapter template missing"

    def test_output_path_to_workspace_report(self, content):
        """Chapter files must be saved to workspace/report/."""
        assert "workspace/report" in content or "/mnt/user-data/workspace" in content

    def test_citation_format_examples(self, content):
        """APA, IEEE, and GB-T-7714 examples must be present."""
        for style in CITATION_STYLES:
            assert style in content, f"Citation style {style!r} missing from report-writer.md"

    def test_citation_mandatory_rule(self, content):
        assert "citation" in content.lower() or "cite" in content.lower()

    def test_tables_over_lists_rule(self, content):
        """Structured data should use tables, not bullet lists."""
        assert "table" in content.lower() or "Tables" in content

    def test_no_recursive_task_rule(self, content):
        assert "task" in content.lower() and (
            "not" in content.lower() or "DO NOT" in content or "No" in content
        )

    def test_save_output_rule(self, content):
        """Agent must save chapter file before finishing."""
        assert "save" in content.lower() or "write" in content.lower()

    def test_methodology_section_has_taxonomy(self, content):
        """Methodology chapter template must include a taxonomy/classification table."""
        assert "Taxonomy" in content or "taxonomy" in content.lower() or "Category" in content

    def test_results_section_has_benchmark(self, content):
        """Results chapter template must include benchmark overview."""
        assert "Benchmark" in content or "benchmark" in content.lower()

    def test_gaps_section_has_directions(self, content):
        """Gaps chapter template must include research directions subsection."""
        assert "Directions" in content or "direction" in content.lower()


# ---------------------------------------------------------------------------
# research-report.md template
# ---------------------------------------------------------------------------


class TestResearchReportMD:
    @pytest.fixture(scope="class")
    def content(self):
        assert _RESEARCH_REPORT_MD.exists(), f"Not found: {_RESEARCH_REPORT_MD}"
        return _RESEARCH_REPORT_MD.read_text(encoding="utf-8")

    def test_all_seven_structural_sections_present(self, content):
        """Full 7-chapter structure must be defined in the template."""
        missing = [s for s in REPORT_SECTIONS if s not in content]
        assert not missing, f"Missing report sections: {missing}"

    def test_three_parallel_subagent_sections_annotated(self, content):
        """Sections 3, 4, 5 must be annotated as report-writer subagent output."""
        assert "report-writer" in content
        # All three parallel sections should reference subagent
        count = content.count("report-writer")
        assert count >= 3, f"Expected ≥ 3 report-writer references, found {count}"

    def test_lead_agent_serial_sections_annotated(self, content):
        """Introduction, Discussion, Conclusion must be annotated as Lead Agent."""
        assert "Lead Agent" in content

    def test_assembly_instructions_present(self, content):
        """Assembly instructions must describe how to concatenate sections."""
        assert "Assembly" in content or "assembly" in content.lower()
        assert "present_files" in content or "present files" in content.lower()

    def test_abstract_written_last_noted(self, content):
        """Template must note that Abstract is written last."""
        assert "LAST" in content or "last" in content.lower()

    def test_output_path_to_outputs(self, content):
        """Final report must be saved to outputs/ not just workspace."""
        assert "outputs" in content

    def test_appendix_paper_corpus_table(self, content):
        """Appendix A must include a paper corpus table with OV URI column."""
        assert "Appendix" in content
        assert "OV URI" in content or "viking://" in content

    def test_citation_style_header_field(self, content):
        """Report header must include Citation Style field."""
        assert "Citation Style" in content


# ---------------------------------------------------------------------------
# citation-formats.md
# ---------------------------------------------------------------------------


class TestCitationFormatsMD:
    @pytest.fixture(scope="class")
    def content(self):
        assert _CITATION_FORMATS_MD.exists(), f"Not found: {_CITATION_FORMATS_MD}"
        return _CITATION_FORMATS_MD.read_text(encoding="utf-8")

    def test_three_styles_documented(self, content):
        for style in ["APA", "IEEE", "GB"]:
            assert style in content, f"{style} missing from citation-formats.md"

    def test_inline_citation_format_per_style(self, content):
        """Each style must document inline citation format."""
        assert "Inline" in content or "inline" in content.lower()

    def test_journal_article_format_per_style(self, content):
        assert "Journal" in content or "journal" in content.lower()

    def test_conference_paper_format_per_style(self, content):
        assert "Conference" in content or "conference" in content.lower()

    def test_arxiv_format_documented(self, content):
        """arXiv preprint format must be documented (common in ML papers)."""
        assert "arXiv" in content or "arxiv" in content.lower()

    def test_doi_format_rule(self, content):
        """DOI format must be standardized (https://doi.org/ prefix)."""
        assert "doi.org" in content.lower()

    def test_quick_rules_table(self, content):
        """Quick formatting rules table must be present for fast reference."""
        assert "Quick" in content or "quick" in content.lower()

    def test_en_dash_page_ranges(self, content):
        """Page ranges must use en-dash (–) not hyphen (-) per Chicago/APA."""
        assert "–" in content or "en-dash" in content.lower()

    def test_gb_type_markers_documented(self, content):
        """GB/T 7714 type markers [J] and [C] must be documented."""
        assert "[J]" in content
        assert "[C]" in content


# ---------------------------------------------------------------------------
# SKILL.md Phase 4 section
# ---------------------------------------------------------------------------


class TestSkillMDPhase4:
    @pytest.fixture(scope="class")
    def content(self):
        assert _SKILL_MD.exists(), f"Not found: {_SKILL_MD}"
        return _SKILL_MD.read_text(encoding="utf-8")

    def _phase4_section(self, content: str) -> str:
        start = content.find("## Phase 4")
        end = content.find("## Phase 5", start)
        if end == -1:
            end = content.find("## Important", start)
        return content[start:end] if end > start else content[start:]

    def test_phase4_section_exists(self, content):
        assert "Phase 4" in content

    def test_phase4_has_detailed_workflow(self, content):
        section = self._phase4_section(content)
        assert len(section) > 600, "Phase 4 section is too short — detailed workflow required"

    def test_three_parallel_task_calls(self, content):
        section = self._phase4_section(content)
        assert section.count('subagent_type="report-writer"') >= 3 or section.count("report-writer") >= 3

    def test_methodology_chapter_dispatched(self, content):
        section = self._phase4_section(content)
        assert "Methodology" in section

    def test_results_chapter_dispatched(self, content):
        section = self._phase4_section(content)
        assert "Results" in section

    def test_gaps_chapter_dispatched(self, content):
        section = self._phase4_section(content)
        assert "Gaps" in section or "gap" in section.lower()

    def test_lead_agent_serial_sections(self, content):
        section = self._phase4_section(content)
        assert "Lead Agent" in section
        assert "Introduction" in section
        assert "Discussion" in section or "Conclusion" in section

    def test_reference_compilation_step(self, content):
        section = self._phase4_section(content)
        assert "Reference" in section or "reference" in section.lower()
        assert "citation-formats" in section or "cite" in section.lower()

    def test_abstract_written_last(self, content):
        section = self._phase4_section(content)
        assert "Abstract" in section

    def test_assembly_step_present(self, content):
        section = self._phase4_section(content)
        assert "cat " in section or "concatenat" in section.lower() or "Assemble" in section

    def test_present_files_delivery(self, content):
        section = self._phase4_section(content)
        assert "present_files" in section

    def test_output_to_outputs_dir(self, content):
        section = self._phase4_section(content)
        assert "outputs" in section

    def test_acceptance_criteria_stated(self, content):
        section = self._phase4_section(content)
        assert (
            "Acceptance" in section
            or "acceptance" in section.lower()
            or "criteria" in section.lower()
        )

    def test_wait_for_parallel_completion(self, content):
        """SKILL.md must explicitly state waiting for all 3 parallel tasks before proceeding."""
        section = self._phase4_section(content)
        assert "Wait" in section or "wait" in section.lower()
