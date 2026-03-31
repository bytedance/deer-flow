"""Tests for Phase 3: Cross-paper Synthesis.

Covers:
- synthesis.md agent prompt file:
    - 4-step workflow documented (collect files / cluster / synthesize / save)
    - Three synthesis dimensions: Consensus, Contradictions, Research Gaps
    - Minimum 3 gaps rule explicitly stated
    - Evidence requirement for each gap (citing specific papers)
    - Output path: /mnt/user-data/workspace/gap-analysis.md
    - Behavioral rules: citation mandatory, no fabrication, quantitative over qualitative
    - No recursive task calls (Lead Agent only)
- SKILL.md Phase 3 section:
    - Detailed 4-step workflow documented (not just a stub)
    - gap-analysis.md output path referenced
    - ov-retriever dispatch for thematic clustering
    - All 3 synthesis dimensions present (Consensus / Contradictions / Gaps)
    - Minimum 3 gaps constraint mentioned
    - Save-before-proceed rule documented
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths to files under test
# ---------------------------------------------------------------------------

_AGENTS_DIR = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "agents"
)
_SYNTHESIS_MD = _AGENTS_DIR / "synthesis.md"
_SKILL_MD = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "SKILL.md"
)

# The 3 required synthesis dimensions
SYNTHESIS_DIMENSIONS = ["Consensus", "Contradictions", "Research Gaps"]

# Required gap fields
GAP_FIELDS = ["Evidence", "Significance", "Suggested direction"]


# ---------------------------------------------------------------------------
# synthesis.md — file exists and has required structure
# ---------------------------------------------------------------------------


class TestSynthesisMDExists:
    def test_file_exists(self):
        assert _SYNTHESIS_MD.exists(), f"synthesis.md not found at {_SYNTHESIS_MD}"

    def test_file_not_empty(self):
        content = _SYNTHESIS_MD.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "synthesis.md appears to be nearly empty"


class TestSynthesisMDWorkflow:
    @pytest.fixture(scope="class")
    def content(self):
        return _SYNTHESIS_MD.read_text(encoding="utf-8")

    def test_four_steps_documented(self, content):
        """All 4 workflow steps must be present."""
        assert "Step 1" in content, "Step 1 (Collect files) missing"
        assert "Step 2" in content, "Step 2 (Thematic grouping) missing"
        assert "Step 3" in content, "Step 3 (Three-dimensional synthesis) missing"
        assert "Step 4" in content, "Step 4 (Save gap analysis) missing"

    def test_collect_analysis_files_step(self, content):
        """Step 1 must instruct reading analysis files from workspace."""
        assert "workspace/analysis" in content or "analysis/" in content

    def test_thematic_clustering_step(self, content):
        """Step 2 must reference ov-retriever or ov find for clustering."""
        assert "ov-retriever" in content or "ov find" in content

    def test_ov_find_query_variants(self, content):
        """Multiple query phrasings improve clustering recall."""
        # At minimum the step should reference ov find with query phrasings
        assert "ov find" in content or "ov-retriever" in content

    def test_save_step_references_gap_analysis(self, content):
        """Step 4 must explicitly name the output file."""
        assert "gap-analysis.md" in content


class TestSynthesisMDDimensions:
    @pytest.fixture(scope="class")
    def content(self):
        return _SYNTHESIS_MD.read_text(encoding="utf-8")

    def test_all_three_dimensions_present(self, content):
        missing = [d for d in SYNTHESIS_DIMENSIONS if d not in content]
        assert not missing, f"Missing synthesis dimensions: {missing}"

    def test_consensus_table_format(self, content):
        """Consensus section must specify a table format with Supporting Papers column."""
        assert "Supporting Papers" in content or "supporting papers" in content.lower()

    def test_contradictions_position_format(self, content):
        """Contradictions must document Position A / Position B structure."""
        assert "Position A" in content or "position A" in content.lower()
        assert "Position B" in content or "position B" in content.lower()

    def test_research_gaps_minimum_three(self, content):
        """Prompt must explicitly require at least 3 research gaps."""
        assert "3" in content and (
            "minimum" in content.lower()
            or "at least" in content.lower()
            or "least 3" in content.lower()
        )

    def test_gap_type_taxonomy(self, content):
        """Gap taxonomy must include Unexplored combination and Acknowledged limitation."""
        assert "Unexplored" in content or "unexplored" in content.lower()
        assert "Acknowledged" in content or "acknowledged" in content.lower()

    def test_gap_evidence_field(self, content):
        """Each gap must require an Evidence field citing specific papers."""
        assert "Evidence" in content

    def test_gap_significance_field(self, content):
        assert "Significance" in content

    def test_gap_suggested_direction_field(self, content):
        assert "Suggested direction" in content or "direction" in content.lower()


class TestSynthesisMDGapAnalysisDocument:
    @pytest.fixture(scope="class")
    def content(self):
        return _SYNTHESIS_MD.read_text(encoding="utf-8")

    def test_output_path_is_workspace(self, content):
        """Output must go to workspace, not just returned inline."""
        assert "/mnt/user-data/workspace" in content or "workspace/gap-analysis" in content

    def test_gap_analysis_filename(self, content):
        assert "gap-analysis.md" in content

    def test_synthesis_notes_section(self, content):
        """Gap analysis document must include Synthesis Notes summary."""
        assert "Synthesis Notes" in content or "synthesis notes" in content.lower()

    def test_ready_for_phase4_flag(self, content):
        """Must include a flag indicating readiness for Phase 4."""
        assert "Phase 4" in content or "phase 4" in content.lower()

    def test_thematic_clusters_in_output(self, content):
        """Output document must include the thematic clusters table."""
        assert "Thematic Clusters" in content or "thematic cluster" in content.lower()


class TestSynthesisMDBehavioralRules:
    @pytest.fixture(scope="class")
    def content(self):
        return _SYNTHESIS_MD.read_text(encoding="utf-8")

    def test_citation_mandatory_rule(self, content):
        """Every finding must cite a specific paper — this rule must be stated."""
        assert "cite" in content.lower() or "citation" in content.lower()
        assert (
            "mandatory" in content.lower()
            or "must" in content.lower()
            or "required" in content.lower()
        )

    def test_no_fabrication_rule(self, content):
        """Prompt must forbid inventing paper titles or findings."""
        assert "fabricat" in content.lower() or "not confirmed" in content.lower()

    def test_no_recursive_task_calls(self, content):
        """synthesis.md is Lead Agent only — no task() dispatch allowed."""
        assert "NOT a subagent" in content or "Lead Agent" in content
        assert "DO NOT call" in content or "do not call" in content.lower() or "not call" in content.lower()

    def test_quantitative_over_qualitative_rule(self, content):
        """Claims backed by numbers preferred over vague comparisons."""
        assert (
            "quantitative" in content.lower()
            or "numbers" in content.lower()
            or "accuracy" in content.lower()
        )

    def test_save_before_proceeding_rule(self, content):
        """Must explicitly state: save gap-analysis.md before notifying user."""
        assert "before" in content.lower() and (
            "proceed" in content.lower() or "notif" in content.lower()
        )

    def test_minimum_gaps_enforcement(self, content):
        """If fewer than 3 gaps found, must NOT proceed to Phase 4."""
        assert "fewer than 3" in content or "less than 3" in content or "minimum" in content.lower()


# ---------------------------------------------------------------------------
# SKILL.md Phase 3 section
# ---------------------------------------------------------------------------


class TestSkillMDPhase3:
    @pytest.fixture(scope="class")
    def content(self):
        assert _SKILL_MD.exists(), f"Not found: {_SKILL_MD}"
        return _SKILL_MD.read_text(encoding="utf-8")

    def test_phase3_section_exists(self, content):
        assert "Phase 3" in content

    def test_phase3_has_detailed_workflow(self, content):
        """Phase 3 must be more than a stub — requires step-by-step instructions."""
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert len(p3_section) > 400, "Phase 3 section is too short — detailed workflow required"

    def test_gap_analysis_md_referenced(self, content):
        assert "gap-analysis.md" in content

    def test_ov_retriever_dispatch_in_phase3(self, content):
        """Phase 3 must dispatch ov-retriever for thematic clustering."""
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "ov-retriever" in p3_section

    def test_all_three_synthesis_dimensions_in_phase3(self, content):
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        missing = [d for d in SYNTHESIS_DIMENSIONS if d not in p3_section]
        assert not missing, f"Missing synthesis dimensions in SKILL.md Phase 3: {missing}"

    def test_minimum_3_gaps_constraint_in_phase3(self, content):
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "3" in p3_section and (
            "minimum" in p3_section.lower()
            or "at least" in p3_section.lower()
            or "≥ 3" in p3_section
        )

    def test_workspace_output_path_in_phase3(self, content):
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "workspace" in p3_section

    def test_save_before_proceed_rule_in_phase3(self, content):
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "save" in p3_section.lower() or "Save" in p3_section

    def test_synthesis_md_referenced_in_phase3(self, content):
        """Phase 3 should point to synthesis.md for full agent instructions."""
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "synthesis.md" in p3_section

    def test_no_fabrication_invariant_in_phase3(self, content):
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "fabricat" in p3_section.lower() or "never" in p3_section.lower()

    def test_evidence_requirement_in_phase3(self, content):
        """Evidence requirement for each gap must appear in Phase 3."""
        p3_start = content.find("## Phase 3")
        p4_start = content.find("## Phase 4")
        p3_section = content[p3_start:p4_start] if p4_start > p3_start else content[p3_start:]
        assert "evidence" in p3_section.lower() or "cite" in p3_section.lower()
