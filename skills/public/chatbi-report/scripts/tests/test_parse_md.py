"""Unit tests for scripts/parse_md.py."""
from pathlib import Path

import pytest

import parse_md as pm


def test_parse_single_org_block_extracts_one_context(fixture_dir):
    """single_org.md：1 个机构多行块 → 1 个 OrgContext 字段。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.org_contexts) == 1
    assert rep.org_contexts[0].branch_num == "27020199"
    assert rep.org_contexts[0].branch_short_name == "王益联社"
    assert rep.time_info == ["2025"]


def test_parse_multi_org_block_extracts_all(fixture_dir):
    """multi_org.md：4 个机构多行块 → 4 个 OrgContext，顺序保留。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.org_contexts) == 4
    assert [o.branch_num for o in rep.org_contexts] == [
        "27020199", "27020100", "AVG_TONGCHUAN", "AVG_PROVINCE",
    ]
    assert [o.branch_short_name for o in rep.org_contexts] == [
        "王益联社", "印台联社", "铜川平均值", "全省平均值",
    ]


def test_parse_org_block_to_dict_uses_list(fixture_dir):
    """Report.to_dict() 输出 `org_contexts`（list）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    d = doc.to_dict()
    assert "org_contexts" in d["sections"][0]["reports"][0]
    assert "org_context" not in d["sections"][0]["reports"][0]
    assert isinstance(d["sections"][0]["reports"][0]["org_contexts"], list)
    assert len(d["sections"][0]["reports"][0]["org_contexts"]) == 4


def test_parse_single_period_real_indicator_has_no_period(fixture_dir):
    """single_org.md：未带 data-period 的真指标 → Th.period is None。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    rep = doc.sections[0].reports[0]
    real = [c for row in rep.headers for c in row if c.is_indicator]
    assert len(real) == 1
    assert real[0].idx_id == "BAS_0263"
    assert real[0].period is None


def test_parse_multi_period_real_indicator_captures_period(fixture_dir):
    """multi_org.md：3 个 BAS_0263 各带 data-period → Th.period 全部捕获。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    rep = doc.sections[0].reports[0]
    real = [c for row in rep.headers for c in row if c.is_indicator]
    assert len(real) == 3
    assert [(c.idx_id, c.period) for c in real] == [
        ("BAS_0263", "2023"),
        ("BAS_0263", "2024"),
        ("BAS_0263", "2025"),
    ]


def test_parse_multi_period_computed_column_captures_period(fixture_dir):
    """multi_org.md：3 个 {{name}} 计算列也允许带 data-period。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    rep = doc.sections[0].reports[0]
    computed = [c for row in rep.headers for c in row if c.is_computed]
    assert len(computed) == 3
    assert [(c.text, c.period) for c in computed] == [
        ("{{2023利润同比}}", "2023"),
        ("{{2024利润同比}}", "2024"),
        ("{{2025利润同比}}", "2025"),
    ]


def test_parse_period_field_absent_in_to_dict_when_none(fixture_dir):
    """Th.to_dict() 在 period is None 时不输出 'period' 键（紧凑性）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    rep = doc.sections[0].reports[0]
    for row in rep.headers:
        for c in row:
            d = c.to_dict()
            if c.is_indicator and c.idx_id == "BAS_0263":
                assert "period" not in d


def test_parse_period_field_present_in_to_dict_when_set(fixture_dir):
    """Th.to_dict() 在 period 已设时输出 'period' 键。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    rep = doc.sections[0].reports[0]
    for row in rep.headers:
        for c in row:
            d = c.to_dict()
            if c.is_indicator and c.idx_id == "BAS_0263":
                assert d.get("period") in {"2023", "2024", "2025"}


def test_parse_multi_row_thead_with_colspan_preserves_2d(fixture_dir):
    """multi_org.md：2 行 thead，第 0 行 colspan=3 父级 → headers 仍是 2D。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2
    # 第 0 行：行社 + 利润总额(colspan=3) + 同比增速(colspan=3)
    row0 = rep.headers[0]
    parent = next(c for c in row0 if c.colspan == 3)
    assert parent.is_indicator is False and parent.is_computed is False
    assert parent.text == "利润总额"
    # 第 1 行：3 real + 3 computed
    assert len(rep.headers[1]) == 6


def test_parse_description_block_to_dict(tmp_path):
    md = tmp_path / "with_desc.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 描述:\n"
        ">   请生成经营分析描述。\n"
        ">   重点关注同比变化。\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\" data-unit=\"万元\">利润</th></tr></thead>"
        "<tbody><tr><td>机构A</td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    doc = pm.parse_file(str(md))
    rep = doc.sections[0].reports[0]
    assert rep.description_prompt == "请生成经营分析描述。\n重点关注同比变化。"
    assert doc.to_dict()["sections"][0]["reports"][0]["description_prompt"] == rep.description_prompt
