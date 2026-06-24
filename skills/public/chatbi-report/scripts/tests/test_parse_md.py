"""Unit tests for scripts/parse_md.py."""
from pathlib import Path

import pytest

import parse_md as pm


def test_parse_happy_md_returns_single_report(fixture_dir):
    """happy.md：1 章节，1 报表，3 个 thead 单元格（1 个占位 + 1 个真实指标 + 1 个计算列）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert doc.title == "王益联社 2025 年度经营报表"
    assert len(doc.sections) == 1
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 1          # 一行 thead
    assert len(rep.headers[0]) == 3       # 该行有三个单元格
    cells = rep.headers[0]
    # 单元格 0：占位（"季度"）
    assert cells[0].is_indicator is False and cells[0].is_computed is False and cells[0].idx_id is None
    # 单元格 1：来自 data-idx 的真实指标
    assert cells[1].is_indicator is True and cells[1].idx_id == "BAS_0263"
    assert cells[1].text == "贷款收单商户数"
    # 单元格 2：计算列（无 data-idx）
    assert cells[2].is_computed is True and cells[2].is_indicator is False
    assert cells[2].text == "{{收单商户同比}}"
    # computed_specs 已存在
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_multi_chapter_two_sections(fixture_dir):
    """multi_chapter.md：2 章节，每章 1 张报表。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert len(doc.sections) == 2
    assert len(doc.sections[0].reports) == 1
    assert len(doc.sections[1].reports) == 1


def test_parse_multi_header_two_row_thead(fixture_dir):
    """multi_header.md：外层 headers 是 2 行；第 0 行有 2 个单元格（其中一个是类目父级）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2          # 两行 thead
    assert len(rep.headers[0]) == 2       # 季度 + 商户与贷款（colspan=2）
    assert len(rep.headers[1]) == 2       # BAS_0263 + BAS_0264（位于 colspan 之下）
    # 类目父级：有 colspan，无 data-idx，无 {{}}
    parent = rep.headers[0][1]
    assert parent.is_indicator is False and parent.is_computed is False
    assert parent.colspan == 2
    # 第 1 行中的子单元格
    c0, c1 = rep.headers[1]
    assert c0.is_indicator is True and c0.idx_id == "BAS_0263"
    assert c1.is_indicator is True and c1.idx_id == "BAS_0264"


def test_parse_multi_header_computed_under_category(fixture_dir):
    """multi_header_computed.md：计算列嵌套于类目父级之下。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header_computed.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2
    # 第 1 行：真实指标 + 计算列
    r1 = rep.headers[1]
    assert r1[0].is_indicator is True and r1[0].idx_id == "BAS_0263"
    assert r1[1].is_computed is True
    # 已解析到计算 spec
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_old_style_placeholder_extracts_idx_id(fixture_dir):
    """`<th data-unit="个">{{BAS_0263}}</th>` -> is_indicator=True，idx_id=BAS_0263，text=BAS_0263。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    rep = doc.sections[0].reports[0]
    cells = rep.headers[0]
    real = [c for c in cells if c.is_indicator]
    assert real[0].idx_id == "BAS_0263"
    # 文本来自占位符本身（MD 中无中文名）
    assert real[0].text == "BAS_0263"


def test_parse_org_and_time_into_report(fixture_dir):
    """`> 机构:` 与 `> 时期:` 解析进 Report 字段。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    rep = doc.sections[0].reports[0]
    assert rep.org_context.branch_num == "27020199"
    assert rep.org_context.branch_short_name == "王益联社"
    assert rep.time_info == ["2025"]


def test_all_idx_ids_collected_at_doc_level(fixture_dir):
    """Doc.all_idx_ids 是全部报表中非计算列 idx_id 的并集。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert doc.all_idx_ids == {"BAS_0263", "BAS_0264", "BAS_0265"}
