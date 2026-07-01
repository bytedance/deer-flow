"""Unit tests for assemble_status (新写, 中文回执 + status dict)."""

from __future__ import annotations

from assemble_status import build_status, format_zh_receipt


def test_build_status_aggregates_sentinels():
    sections = [
        {"section_title": "存款", "approval_status": "approved", "sentinels": ["⚠️QUERY_FAILED", "⚠️QUERY_FAILED"], "computed_sentinels": {"利润率": "⚠️COMPUTE_FAILED"}},
        {"section_title": "贷款", "approval_status": "draft", "sentinels": [], "computed_sentinels": {}},
    ]
    status = build_status("rid", sections, design_md_path="/mnt/ai-report-data/rid.design.md")
    assert status["total_sections"] == 2
    assert status["approved_sections"] == 1
    assert status["draft_sections"] == 1
    assert status["total_sentinels"] == 3
    assert status["sentinels_by_code"]["⚠️QUERY_FAILED"] == 2
    assert status["sentinels_by_code"]["⚠️COMPUTE_FAILED"] == 1


def test_format_zh_receipt_has_4_items():
    status = {
        "report_id": "rid",
        "total_sections": 5,
        "approved_sections": 5,
        "draft_sections": 0,
        "total_sentinels": 0,
        "sentinels_by_code": {},
        "design_md_path": "/mnt/ai-report-data/rid.design.md",
        "report_md_path": "/mnt/ai-report-data/rid.report.md",
        "report_docx_path": "/mnt/ai-report-data/rid.report.docx",
    }
    out = format_zh_receipt(status)
    assert "章节数" in out
    assert "哨兵数" in out
    assert "未设计章节" in out
    assert "生成路径" in out