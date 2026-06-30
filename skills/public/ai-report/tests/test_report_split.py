"""Unit tests for report_split.split_report (新写, 借鉴 chatbi-report _split_sections/_split_reports 思路)."""

from __future__ import annotations

import pytest

from report_split import SectionBlock, split_report


def test_split_5_section_report():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    sections = split_report(md)
    assert len(sections) == 5
    assert sections[0].section_order == 0
    assert sections[0].section_title == "一、存款业务"
    assert "存款规模" in sections[0].source_md
    assert "贷款规模" in sections[1].source_md


def test_split_no_h2_returns_empty():
    md = "# Title\n\nno sections here"
    assert split_report(md) == []


def test_split_single_h2_no_h3():
    md = "## A\n\nplain text"
    sections = split_report(md)
    assert len(sections) == 1
    assert sections[0].section_title == "A"


def test_split_section_order_starts_at_zero():
    md = "## A\n\n## B\n\n"
    sections = split_report(md)
    assert [s.section_order for s in sections] == [0, 1]