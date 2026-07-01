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


def test_parse_indicator_columns_not_marked_computed():
    """Regression: data-idx alone means indicator (lookup idx_id@period),
    NOT computed. Previously parse_md conflated the two and is_computed=True
    broke unit_convert + render_markdown (they'd look up cells by text
    instead of idx_id@period → all cells rendered as "—")."""
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    ths = [th for section in doc.sections for report in section.reports
           for row in report.headers for th in row]
    indicator_ths = [th for th in ths if th.idx_id]
    assert indicator_ths, "fixture should have indicator columns"
    for th in indicator_ths:
        assert th.is_computed is False, (
            f"indicator cell text={th.text!r} idx_id={th.idx_id!r} "
            "should NOT be is_computed"
        )


def test_parse_data_computed_attr_marks_computed():
    """data-computed attribute marks a formula column (e.g. 利润率)."""
    md = """# T
## S
### R
> 机构: org_contexts = [{"org_ecd": "1", "org_name": "x"}]
> 时期: time_info = ["202603"]
<table><thead><tr><th data-idx="BAS_001" data-period="202603">存款</th><th data-computed="true">利润率</th></tr></thead></table>
"""
    doc = parse_markdown(md)
    rep = doc.sections[0].reports[0]
    is_computed_flags = [th.is_computed for row in rep.headers for th in row]
    assert is_computed_flags == [False, True]


def test_parse_template_syntax_marks_computed():
    """{{name}} template syntax also marks a formula column (no data-computed attr needed)."""
    md = """# T
## S
### R
> 机构: org_contexts = [{"org_ecd": "1", "org_name": "x"}]
> 时期: time_info = ["202603"]
<table><thead><tr><th data-idx="BAS_001" data-period="202603">存款</th><th>{{利润率}}</th></tr></thead></table>
"""
    doc = parse_markdown(md)
    rep = doc.sections[0].reports[0]
    is_computed_flags = [th.is_computed for row in rep.headers for th in row]
    assert is_computed_flags == [False, True]


def test_parse_description_block_extracted():
    """`> 描述:` block content is captured as description_prompt."""
    md = """# T
## S
### R
> 机构: org_contexts = [{"org_ecd": "1", "org_name": "x"}]
> 时期: time_info = ["202603"]
> 描述:
>   请基于表格数据生成经营分析描述
>   重点关注利润总额同比变化
<table><thead><tr><th data-idx="BAS_026" data-period="202603" data-unit="万元">利润总额</th></tr></thead></table>
"""
    doc = parse_markdown(md)
    rep = doc.sections[0].reports[0]
    assert rep.description_prompt is not None
    assert "利润总额同比变化" in rep.description_prompt
    assert "经营分析描述" in rep.description_prompt


def test_parse_description_block_absent_returns_none():
    """Reports without `> 描述:` block have description_prompt=None."""
    md = """# T
## S
### R
> 机构: org_contexts = [{"org_ecd": "1", "org_name": "x"}]
> 时期: time_info = ["202603"]
<table><thead><tr><th data-idx="BAS_001" data-period="202603" data-unit="万元">存款</th></tr></thead></table>
"""
    doc = parse_markdown(md)
    rep = doc.sections[0].reports[0]
    assert rep.description_prompt is None


def test_parse_wangyi_example_has_all_6_descriptions():
    """All 6 H3 reports in the wangyi sample carry a `> 描述:` prompt block."""
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    descriptions = [r.description_prompt for s in doc.sections for r in s.reports]
    # 5 H2 sections, 6 H3 blocks (section 三 has 2 H3s: 营业收入 + 利润总额).
    # design_pipeline.run_report takes the first H3 of each section, but the
    # parser correctly resolves all 6 — every one should have its own prompt.
    assert len(descriptions) == 6
    for d in descriptions:
        assert d is not None, "every wangyi H3 should have a 描述: prompt"
        assert "请基于表格数据生成经营分析描述" in d