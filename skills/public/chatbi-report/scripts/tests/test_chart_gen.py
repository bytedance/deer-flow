"""Unit tests for scripts/chart_gen.py resolver logic."""
from decimal import Decimal

import pytest

import chart_gen as cg


def _report_dict() -> dict:
    return {
        "title": "R",
        "org_contexts": [
            {"branch_num": "27020199", "branch_short_name": "王益联社"},
            {"branch_num": "27020100", "branch_short_name": "印台联社"},
        ],
        "time_info": ["2023", "2024", "2025"],
        "headers": [
            [
                {"text": "行社", "is_indicator": False, "is_computed": False, "rowspan": 2},
                {"text": "利润总额", "is_indicator": False, "is_computed": False, "colspan": 3, "data_unit": "万元"},
                {"text": "同比增速", "is_indicator": False, "is_computed": False, "colspan": 1, "data_unit": "%"},
            ],
            [
                {"text": "2023年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2023", "data_unit": "万元"},
                {"text": "2024年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2024", "data_unit": "万元"},
                {"text": "2025年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2025", "data_unit": "万元"},
                {"text": "{{2024利润同比}}", "is_indicator": False, "is_computed": True, "data_unit": "%"},
            ],
        ],
        "data_rows": [],
        "computed_specs": [],
    }


def test_build_header_leaves_inherits_parent_unit():
    report = _report_dict()
    leaves = cg.build_header_leaves(report["headers"])
    assert len(leaves) == 4
    for leaf in leaves[:3]:
        assert leaf.unit == "万元"
        assert leaf.value_key.startswith("BAS_0263@")
    # C1 fix: computed leaf uses stripped name as value_key and label
    computed_leaf = leaves[3]
    assert computed_leaf.value_key == "2024利润同比"
    assert "2024利润同比" in computed_leaf.labels


def test_resolve_y_parent_header_expands_to_leaves():
    report = _report_dict()
    leaves = cg.build_header_leaves(report["headers"])
    matched = cg.resolve_y_axis("利润总额", leaves)
    assert len(matched) == 3
    assert {m.period for m in matched} == {"2023", "2024", "2025"}


def test_resolve_y_computed_column_matches_stripped_name():
    """C1 fix: `y轴: 2024利润同比` resolves to the computed leaf."""
    report = _report_dict()
    leaves = cg.build_header_leaves(report["headers"])
    matched = cg.resolve_y_axis("2024利润同比", leaves)
    assert len(matched) == 1
    assert matched[0].value_key == "2024利润同比"


def test_resolve_x_period_maps_to_time_info():
    report = _report_dict()
    wide = [
        {"branch_num": "27020199", "BAS_0263@2023": "1000", "BAS_0263@2024": "1200", "BAS_0263@2025": "1500"},
        {"branch_num": "27020100", "BAS_0263@2023": "900", "BAS_0263@2024": "1100", "BAS_0263@2025": "1300"},
    ]
    leaves = cg.build_header_leaves(report["headers"])
    x = cg.resolve_x_axis("时期", report, leaves, wide)
    assert x == ["2023", "2024", "2025"]


def test_extract_series_by_org_returns_resolved_chart():
    """C6 fix: extract_series returns ResolvedChart with bar_count=0 for single-axis."""
    report = _report_dict()
    wide = [
        {"branch_num": "27020199", "BAS_0263@2023": "1000", "BAS_0263@2024": "1200", "BAS_0263@2025": "1500"},
        {"branch_num": "27020100", "BAS_0263@2023": "900", "BAS_0263@2024": "1100", "BAS_0263@2025": "1300"},
    ]
    spec = {"title": "T", "type": "line", "x": "时期", "y": "利润总额", "series": "行社"}
    resolved = cg.extract_series(spec, report, wide)
    assert isinstance(resolved, cg.ResolvedChart)
    assert resolved.bar_count == 0
    assert len(resolved.series_list) == 2
    names = {s.name for s in resolved.series_list}
    assert names == {"王益联社", "印台联社"}


def test_extract_series_single_no_series_aggregates_multi_org():
    """C5 fix: single-series mode with multiple orgs aggregates via mean."""
    report = _report_dict()
    wide = [
        {"branch_num": "27020199", "BAS_0263@2023": "1000", "BAS_0263@2024": "1200", "BAS_0263@2025": "1500"},
        {"branch_num": "27020100", "BAS_0263@2023": "900", "BAS_0263@2024": "1100", "BAS_0263@2025": "1300"},
    ]
    spec = {"title": "T", "type": "bar", "x": "时期", "y": "利润总额"}
    resolved = cg.extract_series(spec, report, wide)
    assert len(resolved.series_list) == 1
    s = resolved.series_list[0]
    assert s.name == "利润总额"
    assert len(s.y) == 3
    assert s.y == [Decimal("950"), Decimal("1150"), Decimal("1400")]


def test_extract_series_by_metric_period_aggregates_orgs():
    """C4 fix: 系列=指标 with x=时期 aggregates orgs per period via mean."""
    report = _report_dict()
    wide = [
        {"branch_num": "27020199", "BAS_0263@2023": "1000", "BAS_0263@2024": "1200", "BAS_0263@2025": "1500"},
        {"branch_num": "27020100", "BAS_0263@2023": "900", "BAS_0263@2024": "1100", "BAS_0263@2025": "1300"},
    ]
    spec = {"title": "T", "type": "line", "x": "时期", "y": "利润总额", "series": "指标"}
    resolved = cg.extract_series(spec, report, wide)
    assert len(resolved.series_list) == 1
    s = resolved.series_list[0]
    assert s.name == "利润总额"
    assert len(s.x) == 3
    assert len(s.y) == 3
    assert s.y == [Decimal("950"), Decimal("1150"), Decimal("1400")]


def test_extract_bar_line_returns_resolved_chart_with_bar_count():
    """C6 fix: bar_line returns ResolvedChart with explicit bar_count."""
    report = {
        "title": "R",
        "org_contexts": [
            {"branch_num": "A", "branch_short_name": "王益"},
            {"branch_num": "B", "branch_short_name": "印台"},
        ],
        "time_info": ["2025"],
        "headers": [[
            {"text": "行社", "is_indicator": False, "is_computed": False},
            {"text": "贷款余额", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0128", "period": "2025", "data_unit": "万元"},
            {"text": "存款日均净增", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0130", "period": "2025", "data_unit": "万元"},
            {"text": "不良率", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0129", "period": "2025", "data_unit": "%"},
        ]],
        "data_rows": [], "computed_specs": [],
    }
    wide = [
        {"branch_num": "A", "BAS_0128@2025": "1500", "BAS_0130@2025": "800", "BAS_0129@2025": "2.5"},
        {"branch_num": "B", "BAS_0128@2025": "1300", "BAS_0130@2025": "900", "BAS_0129@2025": "1.8"},
    ]
    spec = {
        "title": "T", "type": "bar_line", "x": "行社",
        "y_left": ["贷款余额", "存款日均净增"], "y_right": ["不良率"],
        "series": "指标",
    }
    resolved = cg.extract_series(spec, report, wide)
    assert isinstance(resolved, cg.ResolvedChart)
    assert resolved.bar_count == 2
    assert len(resolved.series_list) == 3
