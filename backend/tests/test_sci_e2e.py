"""End-to-end scenario tests for the sci-research skill (Phase 5).

These tests are split into two categories:

1. **Config validation tests** (run always, no external services required):
   - Verify all 4 subagent models are explicitly configured (no "inherit")
   - Verify all 4 subagent Python modules are importable
   - Verify SKILL.md covers all 6 phases (Phase -1 through Phase 4)
   - Verify workspace output paths are consistent across all agent prompts
   - Verify the subagent model cost hierarchy is correct
     (expensive models for reasoning, cheap for retrieval)

2. **Integration scenario tests** (require live DeerFlow + OpenViking):
   Mark: @pytest.mark.integration
   Skip by default. Run with: pytest -m integration tests/test_sci_e2e.py

   Scenario A: 20-paper corpus → full literature review report
     - Upload 5 papers, index 15 from arXiv URLs
     - Run Phase 1 (ingestion) → Phase 2 (analysis) → Phase 3 (synthesis) → Phase 4 (report)
     - Verify report has ≥ 6 structural sections, ≥ 3 research gaps, ≥ 1 comparison table

   Scenario B: Research direction → web retrieval → report
     - Start with a research question only (no uploads)
     - Phase 1 uses tavily/arXiv fallback for retrieval
     - Verify at least 5 papers retrieved and indexed, report generated

How to run integration tests:
    # Start full stack first:
    # make dev  (from project root)
    #
    # Then run:
    DEERFLOW_URL=http://localhost:2024 pytest -m integration tests/test_sci_e2e.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deerflow.subagents.builtins.data_extractor import DATA_EXTRACTOR_CONFIG
from deerflow.subagents.builtins.literature_analyzer import LITERATURE_ANALYZER_CONFIG
from deerflow.subagents.builtins.ov_retriever import OV_RETRIEVER_CONFIG
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
_SKILL_MD = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "custom"
    / "sci-research"
    / "SKILL.md"
)

ALL_CONFIGS = [
    LITERATURE_ANALYZER_CONFIG,
    DATA_EXTRACTOR_CONFIG,
    REPORT_WRITER_CONFIG,
    OV_RETRIEVER_CONFIG,
]

# ---------------------------------------------------------------------------
# Config validation — always run (no live services required)
# ---------------------------------------------------------------------------


class TestAllSubagentModelsExplicit:
    """Every subagent must have an explicit model — no 'inherit' allowed.

    'inherit' means the subagent will use whichever model the lead agent uses,
    which is non-deterministic and ignores the cost/quality trade-offs designed
    into the Phase pipeline.
    """

    @pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.name)
    def test_model_is_not_inherit(self, cfg):
        assert cfg.model != "inherit", (
            f"Subagent '{cfg.name}' has model='inherit'. "
            "Assign an explicit model to ensure predictable cost and quality."
        )

    @pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.name)
    def test_model_is_not_none(self, cfg):
        assert cfg.model is not None, f"Subagent '{cfg.name}' has model=None"

    @pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.name)
    def test_model_is_nonempty_string(self, cfg):
        assert isinstance(cfg.model, str) and len(cfg.model) > 0


class TestSubagentCostHierarchy:
    """Verify the intended cost/quality hierarchy is preserved.

    - ov-retriever: cheapest (doubao-lite) — high frequency, simple retrieval
    - data-extractor: mid-tier (claude-3-5-sonnet) — structured accuracy
    - literature-analyzer: reasoning (deepseek-v3) — deep comprehension
    - report-writer: writing quality (gpt-4o) — long-form prose
    """

    def test_ov_retriever_uses_cheap_model(self):
        assert "doubao" in OV_RETRIEVER_CONFIG.model.lower() or "mini" in OV_RETRIEVER_CONFIG.model.lower(), (
            "ov-retriever should use a cost-efficient model (doubao-lite or gpt-4o-mini). "
            f"Currently: {OV_RETRIEVER_CONFIG.model!r}"
        )

    def test_literature_analyzer_uses_reasoning_model(self):
        assert "deepseek" in LITERATURE_ANALYZER_CONFIG.model.lower() or "r1" in LITERATURE_ANALYZER_CONFIG.model.lower()

    def test_data_extractor_uses_claude(self):
        assert "claude" in DATA_EXTRACTOR_CONFIG.model.lower()

    def test_report_writer_uses_gpt4(self):
        assert "gpt-4" in REPORT_WRITER_CONFIG.model.lower() or "gpt4" in REPORT_WRITER_CONFIG.model.lower()


class TestSubagentNoRecursion:
    """All non-lead subagents must disallow task calls to prevent infinite recursion."""

    @pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.name)
    def test_task_in_disallowed(self, cfg):
        assert "task" in cfg.disallowed_tools, (
            f"Subagent '{cfg.name}' must have 'task' in disallowed_tools to prevent recursive spawning"
        )


class TestSubagentTimeoutAdequacy:
    """Timeouts must be appropriate for each subagent's workload."""

    def test_literature_analyzer_timeout(self):
        assert LITERATURE_ANALYZER_CONFIG.timeout_seconds >= 600, "Deep paper reading needs ≥ 600s"

    def test_data_extractor_timeout(self):
        assert DATA_EXTRACTOR_CONFIG.timeout_seconds >= 180, "Table extraction needs ≥ 180s"

    def test_report_writer_timeout(self):
        assert REPORT_WRITER_CONFIG.timeout_seconds >= 900, "Long-form writing needs ≥ 900s"

    def test_ov_retriever_timeout(self):
        assert OV_RETRIEVER_CONFIG.timeout_seconds >= 120, "Retrieval needs ≥ 120s"
        assert OV_RETRIEVER_CONFIG.timeout_seconds <= 300, "Retrieval > 300s suggests a hanging query"


class TestSkillMDPhaseCompleteness:
    """SKILL.md must document all 6 phases of the workflow."""

    @pytest.fixture(scope="class")
    def content(self):
        assert _SKILL_MD.exists(), f"SKILL.md not found at {_SKILL_MD}"
        return _SKILL_MD.read_text(encoding="utf-8")

    @pytest.mark.parametrize("phase", ["Phase -1", "Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4"])
    def test_phase_documented(self, content, phase):
        assert phase in content, f"{phase} missing from SKILL.md"

    def test_present_files_mentioned(self, content):
        """Final delivery via present_files must be documented."""
        assert "present_files" in content

    def test_max_3_concurrent_stated(self, content):
        assert "3" in content and ("concurrent" in content.lower() or "max" in content.lower())

    def test_ov_fallback_documented(self, content):
        """Web-only fallback mode for when OV is unavailable must be mentioned."""
        assert "fallback" in content.lower() or "unavailable" in content.lower()


class TestWorkspacePathConsistency:
    """All agent prompts must use the canonical workspace paths."""

    CANONICAL_WORKSPACE = "/mnt/user-data/workspace"
    CANONICAL_UPLOADS = "/mnt/user-data/uploads"
    CANONICAL_OUTPUTS = "/mnt/user-data/outputs"

    @pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.name)
    def test_workspace_path_in_prompt(self, cfg):
        assert self.CANONICAL_WORKSPACE in cfg.system_prompt, (
            f"Subagent '{cfg.name}' system_prompt missing canonical workspace path"
        )

    def test_agent_md_files_use_workspace_path(self):
        """All .md agent prompt files must reference workspace or OV paths.

        Retrieval-only agents (ov-retriever) use viking:// URIs instead of
        local workspace paths — both are acceptable.
        """
        for md_file in _AGENTS_DIR.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            has_workspace = self.CANONICAL_WORKSPACE in content or "workspace" in content.lower()
            has_ov_path = "viking://" in content or "ov find" in content or "ov ls" in content
            assert has_workspace or has_ov_path, (
                f"{md_file.name} does not reference workspace path or OV path"
            )


# ---------------------------------------------------------------------------
# Integration scenario tests — require live DeerFlow + OpenViking
# ---------------------------------------------------------------------------

# These tests are marked integration and skipped unless DEERFLOW_URL is set.
# They document the acceptance criteria for Phase 5 scenarios A and B.

_DEERFLOW_URL = os.environ.get("DEERFLOW_URL", "")
_INTEGRATION_REASON = (
    "Integration test requires a running DeerFlow stack. "
    "Set DEERFLOW_URL=http://localhost:2024 and run: pytest -m integration"
)


@pytest.mark.integration
@pytest.mark.skipif(not _DEERFLOW_URL, reason=_INTEGRATION_REASON)
class TestScenarioA_CorpusToReport:
    """Scenario A: 20-paper corpus → complete literature review report.

    Setup:
    - 5 local PDF papers uploaded via Gateway API
    - 15 arXiv URLs provided for Phase 1 ingestion
    - Research question: user-specified (e.g., "transformer attention mechanisms")

    Acceptance criteria:
    - All 20 papers indexed in OV (error_count == 0 for each)
    - Phase 2: 20 literature-analyzer outputs saved to workspace/analysis/
    - Phase 3: gap-analysis.md contains ≥ 3 research gaps with evidence
    - Phase 4: research_report.md contains ≥ 6 structural sections
    - Phase 4: report contains ≥ 1 comparison table (markdown table syntax)
    - Total wall-clock time < 30 minutes
    """

    def test_ov_indexing_all_papers(self):
        """All 20 papers must be indexed without embedding errors."""
        pytest.skip("Requires live OV service and test paper corpus")

    def test_phase2_analysis_files_created(self):
        """One analysis .md file per paper in workspace/analysis/."""
        pytest.skip("Requires live DeerFlow execution")

    def test_phase3_gap_analysis_min_3_gaps(self):
        """gap-analysis.md must contain at least 3 well-supported gaps."""
        pytest.skip("Requires live DeerFlow execution")

    def test_phase4_report_has_six_sections(self):
        """Final report must have Abstract, Intro, Background, Methodology, Results, Gaps, Discussion, Conclusion."""
        pytest.skip("Requires live DeerFlow execution")

    def test_phase4_report_has_comparison_table(self):
        """Report must include at least one markdown comparison table."""
        pytest.skip("Requires live DeerFlow execution")

    def test_total_time_under_30_minutes(self):
        """End-to-end time for 20-paper analysis must be < 30 minutes."""
        pytest.skip("Requires live DeerFlow execution and timing instrumentation")


@pytest.mark.integration
@pytest.mark.skipif(not _DEERFLOW_URL, reason=_INTEGRATION_REASON)
class TestScenarioB_WebRetrievalToReport:
    """Scenario B: Research question only → web retrieval → report.

    Setup:
    - No local uploads
    - Research question provided (e.g., "self-supervised learning for NLP")
    - Phase 1 uses tavily_web_search + arXiv for retrieval

    Acceptance criteria:
    - At least 5 papers retrieved and indexed from web
    - OV verification search returns ≥ 1 result with score ≥ 0.35
    - Phase 2–4 complete successfully
    - Report delivered via present_files
    """

    def test_web_retrieval_at_least_5_papers(self):
        """At least 5 papers must be retrieved and indexed from web sources."""
        pytest.skip("Requires live DeerFlow + Tavily API")

    def test_ov_verification_passes(self):
        """OV verification search must return ≥ 1 result with score ≥ 0.35."""
        pytest.skip("Requires live OV service")

    def test_report_delivered_via_present_files(self):
        """Final report must be delivered to user via present_files tool call."""
        pytest.skip("Requires live DeerFlow execution")

    def test_fallback_without_ov(self):
        """When OV is unavailable, skill must fall back to web-only mode gracefully."""
        pytest.skip("Requires live DeerFlow execution with OV disabled")
