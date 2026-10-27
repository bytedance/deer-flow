"""Tests for parent-side receipt citation verification (RFC #4651 PR2)."""

from deerflow.agents.middlewares.receipt_verification import (
    render_citation_verdict,
    validate_receipt_verdict,
    verify_receipt_citations,
)
from deerflow.agents.middlewares.tool_receipt import parse_citations


def _receipt(rid: str, tool: str = "write_file", status: str = "success") -> dict:
    return {
        "id": rid,
        "tool_call_id": f"tc-{rid}",
        "tool_name": tool,
        "status": status,
        "args_sha256": "a" * 16,
        "output_sha256": "b" * 16,
        "output_bytes": 10,
        "created_at": "2026-08-24T00:00:00+00:00",
    }


LEDGER = [_receipt("r1", "web_search"), _receipt("r2", "write_file"), _receipt("r3", "bash", status="error")]


class TestCitationExtraction:
    def test_bare_and_anchored_citations(self):
        verdict = verify_receipt_citations("wrote file [r2 write_file], searched [r1]", LEDGER)
        assert verdict["cited"] == ["r2", "r1"]
        assert verdict["resolved"] == ["r2", "r1"]
        assert verdict["citation_resolved"] is True

    def test_duplicate_citations_deduped_first_seen(self):
        verdict = verify_receipt_citations("[r1] then [r2] then [r1] again", LEDGER)
        assert verdict["cited"] == ["r1", "r2"]

    def test_same_receipt_with_different_anchors_checks_every_pair(self):
        verdict = verify_receipt_citations("[r2 write_file] then [r2 bash]", LEDGER)

        assert verdict["cited"] == ["r2", "r2"]
        assert verdict["resolved"] == ["r2"]
        assert verdict["failed"] == [
            {
                "id": "r2",
                "reason": "anchor mismatch: cited as bash, receipt r2 is write_file",
            }
        ]
        assert verdict["citation_resolved"] is False

    def test_non_citation_brackets_ignored(self):
        verdict = verify_receipt_citations("see [1] and [rX] and [note]", LEDGER)
        assert verdict["cited"] == []

    def test_parse_accepts_dotted_tool_names(self):
        assert parse_citations("[r4 mcp.server-tool]") == [("r4", "mcp.server-tool")]


class TestClassification:
    def test_error_status_receipt_is_failed(self):
        verdict = verify_receipt_citations("tests passed [r3]", LEDGER)
        assert verdict["resolved"] == []
        assert verdict["failed"] == [{"id": "r3", "reason": "receipt status=error"}]
        assert verdict["citation_resolved"] is False

    def test_anchor_mismatch_is_failed(self):
        verdict = verify_receipt_citations("saved the report [r1 write_file]", LEDGER)
        assert verdict["failed"] == [{"id": "r1", "reason": "anchor mismatch: cited as write_file, receipt r1 is web_search"}]
        assert verdict["citation_resolved"] is False

    def test_anchor_match_resolves(self):
        verdict = verify_receipt_citations("saved the report [r2 write_file]", LEDGER)
        assert verdict["resolved"] == ["r2"]
        assert verdict["citation_resolved"] is True

    def test_unknown_id(self):
        verdict = verify_receipt_citations("uploaded results [r9]", LEDGER)
        assert verdict["unknown"] == ["r9"]
        assert verdict["citation_resolved"] is False


class TestZeroCitationHeuristic:
    def test_action_verb_without_citation_flagged(self):
        verdict = verify_receipt_citations("I wrote the analysis and ran the tests.", LEDGER)
        assert verdict["cited"] == []
        assert verdict["no_citation_claims"] is True
        assert verdict["citation_resolved"] is False

    def test_file_path_without_citation_flagged(self):
        verdict = verify_receipt_citations("Done, see /outputs/report.md for details", LEDGER)
        assert verdict["no_citation_claims"] is True

    def test_benign_report_is_vacuous_pass(self):
        verdict = verify_receipt_citations("The answer is 42.", LEDGER)
        assert verdict["no_citation_claims"] is False
        assert verdict["citation_resolved"] is True

    def test_common_completion_verbs_flagged(self):
        """The original list missed the most common completion phrasings."""
        for text in ["I fixed the bug and added tests.", "I tested the change successfully."]:
            verdict = verify_receipt_citations(text, LEDGER)
            assert verdict["no_citation_claims"] is True, text
            assert verdict["citation_resolved"] is False, text

    def test_chinese_action_claims_flagged(self):
        """CJK reports have no word boundaries; common action verbs must match."""
        verdict = verify_receipt_citations("我已经创建了文件并运行了测试。", LEDGER)
        assert verdict["no_citation_claims"] is True
        assert verdict["citation_resolved"] is False

    def test_nontrivial_uncited_report_with_receipts_flagged(self):
        """Safety net in any language: the run demonstrably executed tools
        (receipts harvested), yet a paragraph-length report cites none of them."""
        report = "The analysis is complete. " * 12  # 300 chars, no verbs, no paths
        verdict = verify_receipt_citations(report, LEDGER)
        assert verdict["cited"] == []
        assert verdict["no_citation_claims"] is True

    def test_short_claim_free_report_with_receipts_stays_vacuous_pass(self):
        verdict = verify_receipt_citations("The answer is 42.", LEDGER)
        assert verdict["no_citation_claims"] is False
        assert verdict["citation_resolved"] is True

    def test_claim_free_report_without_receipts_stays_vacuous_pass(self):
        """No tools were stamped: nothing exists to cite against."""
        report = "The analysis is complete. " * 12
        verdict = verify_receipt_citations(report, [])
        assert verdict["no_citation_claims"] is False
        assert verdict["citation_resolved"] is True

    def test_verdict_shape_vocabulary(self):
        verdict = verify_receipt_citations("x [r1]", LEDGER)
        assert verdict["source"] == "receipt_citations"
        assert verdict["requirement"] == "cited_ids_in_execution_record"
        assert "satisfied" not in verdict


class TestRender:
    def test_render_counts_with_limitation_line(self):
        verdict = verify_receipt_citations("[r1] [r3] [r9]", LEDGER)
        rendered = render_citation_verdict(verdict)
        assert rendered == ("citations: 1 resolved, 1 failed, 1 unknown — execution evidence only, does not validate claim correctness")

    def test_render_unverified_for_no_citation_claims(self):
        verdict = verify_receipt_citations("I wrote the file.", LEDGER)
        assert render_citation_verdict(verdict) == ("citations: UNVERIFIED — action claims without receipt citations")

    def test_render_empty_for_vacuous_pass(self):
        verdict = verify_receipt_citations("The answer is 42.", LEDGER)
        assert render_citation_verdict(verdict) == ""


class TestValidate:
    def test_round_trip(self):
        verdict = verify_receipt_citations("[r1] [r9]", LEDGER)
        assert validate_receipt_verdict(dict(verdict)) == verdict

    def test_rejects_malformed(self):
        assert validate_receipt_verdict(None) is None
        assert validate_receipt_verdict({"source": 1}) is None
        assert validate_receipt_verdict({"citation_resolved": "yes"}) is None
        bad = dict(verify_receipt_citations("[r3]", LEDGER))
        bad["failed"] = [{"id": "r3"}]  # missing reason
        assert validate_receipt_verdict(bad) is None
