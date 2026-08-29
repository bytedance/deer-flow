"""Contract tests for the subagent report contract (RFC #4651 PR3).

The prompt layer is what makes Layer 1 receipt verification non-inert: the
subagent must cite `[rN]`, the lead must expect citations and spot-check
handles, and both sides must agree on the acceptance-criteria wire format.
"""

import importlib

import pytest

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.agents.middlewares.tool_receipt import format_citation, receipt_id
from deerflow.subagents.report_contract import (
    MAX_ACCEPTANCE_CRITERIA,
    MAX_CRITERION_CHARS,
    build_report_contract_section,
    render_acceptance_criteria_section,
)
from deerflow.tools.builtins.task_tool import task_tool

# Module import so tests can patch the exact symbols referenced inside task_tool().
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


class TestReportContractSection:
    def test_receipts_enabled_requires_anchored_citations(self) -> None:
        section = build_report_contract_section(receipts_enabled=True)

        assert section.startswith("<report_contract>")
        assert section.endswith("</report_contract>")
        # The example must derive from the single-owner citation format so the
        # prompt can never drift from the verifier's parser.
        assert format_citation(receipt_id(3), "write_file") in section
        assert format_citation(receipt_id(1)) in section
        # Consequences are stated in the verifier's neutral vocabulary.
        assert "flagged as failed" in section
        assert "flagged as unknown" in section
        assert "flagged UNVERIFIED" in section

    def test_receipts_enabled_requires_verifiable_handles_and_honesty(self) -> None:
        section = build_report_contract_section(receipts_enabled=True)

        assert "absolute file path, URL, record ID, or HTTP status" in section
        assert "never claim an action you did not execute" in section
        # Receipt citations must stay distinct from external web citations.
        assert "[citation:Title](URL)" in section

    def test_receipts_disabled_omits_citation_clauses(self) -> None:
        section = build_report_contract_section(receipts_enabled=False)

        assert "[r3" not in section
        assert "[r1" not in section
        assert "UNVERIFIED" not in section
        # Handles and honesty still apply without receipts.
        assert "absolute file path, URL, record ID, or HTTP status" in section
        assert "never claim an action you did not execute" in section


class TestAcceptanceCriteriaSection:
    def test_none_and_empty_render_nothing(self) -> None:
        assert render_acceptance_criteria_section(None) == ""
        assert render_acceptance_criteria_section([]) == ""
        assert render_acceptance_criteria_section(["", "   "]) == ""

    def test_renders_criteria_as_bullets_with_report_instruction(self) -> None:
        section = render_acceptance_criteria_section(["file:../outputs/report.md non-empty", " tests_passed:make test "])

        assert section.startswith("<acceptance_criteria>")
        assert section.endswith("</acceptance_criteria>")
        assert "- file:../outputs/report.md non-empty" in section
        # Entries are stripped before rendering.
        assert "- tests_passed:make test" in section
        assert "Address each one explicitly in your final report" in section

    def test_drops_non_string_entries(self) -> None:
        section = render_acceptance_criteria_section(["file:a.md exists", 42, None])  # type: ignore[list-item]

        assert "- file:a.md exists" in section
        assert "42" not in section

    def test_caps_count_and_item_length(self) -> None:
        long_criterion = "x" * (MAX_CRITERION_CHARS + 100)
        criteria = [f"criterion {i}" for i in range(MAX_ACCEPTANCE_CRITERIA + 5)] + [long_criterion]

        section = render_acceptance_criteria_section(criteria)

        assert section.count("\n- ") == MAX_ACCEPTANCE_CRITERIA
        assert f"criterion {MAX_ACCEPTANCE_CRITERIA}" not in section

        long_only = render_acceptance_criteria_section([long_criterion])
        assert "x" * (MAX_CRITERION_CHARS + 1) not in long_only
        assert "x" * MAX_CRITERION_CHARS in long_only


class TestTaskToolContract:
    def test_schema_exposes_optional_acceptance_criteria(self) -> None:
        schema = task_tool.tool_call_schema.model_json_schema()

        assert "acceptance_criteria" in schema["properties"]
        assert "acceptance_criteria" not in schema.get("required", [])
        description = schema["properties"]["acceptance_criteria"].get("description") or ""
        assert "file:<path> non-empty" in description
        assert "tests_passed:<command>" in description

    def test_docstring_frames_results_as_self_reports(self) -> None:
        description = task_tool.description

        assert "SELF-REPORTS, not verified facts" in description
        assert "flagged UNVERIFIED" in description
        # Anti-automation-bias: resolved citations are execution evidence only.
        assert "does not validate that the adjacent claim is correct" in description
        assert "spot-check" in description


class TestLeadDelegationWorkflow:
    def _build_section(self, monkeypatch: pytest.MonkeyPatch, max_concurrent: int) -> str:
        monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda: ["general-purpose"])
        return prompt_module._build_subagent_section(max_concurrent)

    def test_single_subagent_workflow_verifies_citations_and_handles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        section = self._build_section(monkeypatch, 1)

        assert "Attach acceptance_criteria for objectively checkable outcomes" in section
        assert "Verify the result before synthesizing" in section
        assert "resolved = the call happened, not that the claim is correct" in section
        assert "spot-check verifiable handles" in section

    def test_parallel_workflow_verifies_citations_and_handles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        section = self._build_section(monkeypatch, 3)

        assert "Attach acceptance_criteria for objectively checkable outcomes" in section
        assert "Verify returned results: ledger citation lines are execution evidence" in section
        assert "resolved = the call happened, not that the claim is correct" in section
        assert "Resolve contradictions against primary evidence" in section
