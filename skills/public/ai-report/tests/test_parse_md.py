"""Unit tests for parse_md (新写, 借鉴 chatbi-report parse_md.py 字段约定)."""

from __future__ import annotations

from parse_md import parse_markdown


def test_parse_5_section_report():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    assert doc.title == "王益联社 2026 年 3 月经营分析报告"
    assert len(doc.sections) == 5
    assert doc.sections[0].title == "一、存款业务"
    assert len(doc.sections[0].reports) == 1
    assert "BAS_001" in doc.all_idx_ids


def test_parse_time_info_extracted():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    first_report = doc.sections[0].reports[0]
    assert first_report.time_info == ["202603"]


def test_parse_data_unit_extracted():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    ths = [th for section in doc.sections for report in section.reports for row in report.headers for th in row]
    units = {th.data_unit for th in ths if th.data_unit}
    assert "万元" in units
    assert "%" in units  # 不良贷款率 (BAS_030)