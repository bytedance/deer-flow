"""Unit tests for md_lint (新写, 借鉴 chatbi-report md_lint.py 检查项)."""

from __future__ import annotations

from md_lint import lint_markdown


def test_lint_happy_path_no_errors():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    assert rep.errors == []


def test_lint_missing_time_info():
    md = open("tests/fixtures/sample_report_lint_error.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    codes = [e.code for e in rep.errors]
    assert "missing_time_info" in codes
    assert "missing_thead" in codes
    assert "invalid_data_unit" in codes


def test_lint_per_section_attribution():
    md = open("tests/fixtures/sample_report_lint_error.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    # 第一个 error 应该在 section 0
    missing_time = next(e for e in rep.errors if e.code == "missing_time_info")
    assert missing_time.section_index == 0