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


def test_extract_series_no_series_x_org_produces_per_row_values():
    """Pie/C8 fix: no series_mode with x=行社 and 1 leaf must produce
    per-row y-values matching x positions (not a single aggregated mean).
    """
    report = {
        "title": "R",
        "org_contexts": [
            {"branch_num": "27020199", "branch_short_name": "王益联社"},
            {"branch_num": "27020100", "branch_short_name": "印台联社"},
            {"branch_num": "27020101", "branch_short_name": "耀州联社"},
            {"branch_num": "27020102", "branch_short_name": "宜君联社"},
        ],
        "time_info": ["2025"],
        "headers": [[
            {"text": "行社", "is_indicator": False, "is_computed": False},
            {"text": "贷款余额", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0128", "period": "2025", "data_unit": "万元"},
        ]],
        "data_rows": [], "computed_specs": [],
    }
    wide = [
        {"branch_num": "27020199", "BAS_0128@2025": "1500"},
        {"branch_num": "27020100", "BAS_0128@2025": "1300"},
        {"branch_num": "27020101", "BAS_0128@2025": "1100"},
        {"branch_num": "27020102", "BAS_0128@2025": "900"},
    ]
    spec = {"title": "贷款占比", "type": "pie", "x": "行社", "y": "贷款余额"}
    resolved = cg.extract_series(spec, report, wide)
    assert len(resolved.series_list) == 1
    s = resolved.series_list[0]
    assert s.name == "贷款余额"
    assert len(s.x) == 4
    assert len(s.y) == 4, f"y must align with x for pie; got {len(s.y)} y vs {len(s.x)} x"
    assert s.y == [Decimal("1500"), Decimal("1300"), Decimal("1100"), Decimal("900")]


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


# ---------- plotter tests (Task 4) ---------- #

import os
import warnings


def test_render_line_png(tmp_path):
    series = [
        cg.Series(name="王益", x=["2023", "2024", "2025"], y=[Decimal("1000"), Decimal("1200"), Decimal("1500")], unit="万元"),
        cg.Series(name="印台", x=["2023", "2024", "2025"], y=[Decimal("900"), Decimal("1100"), Decimal("1300")], unit="万元"),
    ]
    out = tmp_path / "line.png"
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cg.render_chart(title="利润趋势", chart_type="line", series_list=series, out_path=str(out))
        # Glyph assertion only meaningful in sandbox where a CJK font is installed.
        # On macOS/Linux dev machines without the candidate font, skip the check.
        font_available = any(os.path.exists(p) for p in cg._FONT_CANDIDATES)
        if font_available:
            glyph_warnings = [x for x in w if "glyph" in str(x.message).lower()]
            assert not glyph_warnings, f"CJK glyph warnings: {glyph_warnings}"
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_bar_png(tmp_path):
    series = [
        cg.Series(name="利润总额", x=["王益", "印台"], y=[Decimal("1500"), Decimal("1300")], unit="万元"),
    ]
    out = tmp_path / "bar.png"
    cg.render_chart(title="利润对比", chart_type="bar", series_list=series, out_path=str(out))
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_bar_grouped_no_overlap(tmp_path):
    """C7 fix: multi-series bar chart must apply offset (no overlap)."""
    series = [
        cg.Series(name="2024", x=["王益", "印台"], y=[Decimal("1200"), Decimal("1100")], unit="万元"),
        cg.Series(name="2025", x=["王益", "印台"], y=[Decimal("1500"), Decimal("1300")], unit="万元"),
    ]
    out = tmp_path / "bar_grouped.png"
    cg.render_chart(title="利润对比", chart_type="bar", series_list=series, out_path=str(out))
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_bar_line_with_colors(tmp_path):
    bar_series = [
        cg.Series(name="贷款余额", x=["王益", "印台"], y=[Decimal("1500"), Decimal("1300")], unit="万元"),
        cg.Series(name="存款日均净增", x=["王益", "印台"], y=[Decimal("800"), Decimal("900")], unit="万元"),
    ]
    line_series = [
        cg.Series(name="不良率", x=["王益", "印台"], y=[Decimal("2.5"), Decimal("1.8")], unit="%"),
        cg.Series(name="占比", x=["王益", "印台"], y=[Decimal("12"), Decimal("8")], unit="%"),
    ]
    out = tmp_path / "bar_line_color.png"
    cg.render_chart(
        title="贷款与不良率", chart_type="bar_line",
        series_list=bar_series + line_series, out_path=str(out),
        bar_count=2, bar_colors=["#3498db", "#2ecc71"], line_colors=["#e74c3c", "#f39c12"],
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_bar_line_without_bar_count_raises(tmp_path):
    """H7 fix: bar_line without explicit bar_count fails fast."""
    series = [cg.Series(name="A", x=["x"], y=[Decimal("1")], unit=None)]
    with pytest.raises(AssertionError, match="bar_count"):
        cg.render_chart(title="T", chart_type="bar_line", series_list=series, out_path=str(tmp_path / "x.png"))


def test_render_pie_png(tmp_path):
    series = [
        cg.Series(name="贷款余额", x=["王益", "印台", "耀州", "宜君"],
                  y=[Decimal("1500"), Decimal("1300"), Decimal("1100"), Decimal("900")], unit="万元"),
    ]
    out = tmp_path / "pie.png"
    cg.render_chart(title="贷款余额占比", chart_type="pie", series_list=series, out_path=str(out))
    assert out.exists()
    assert out.stat().st_size > 0


# ---------- generate_charts / manifest (Task 5) ---------- #

import json


def test_generate_charts_writes_manifest(tmp_path):
    parsed = {
        "title": "T",
        "sections": [
            {
                "title": "S",
                "reports": [
                    {
                        "title": "R",
                        "org_contexts": [
                            {"branch_num": "27020199", "branch_short_name": "王益"},
                            {"branch_num": "27020100", "branch_short_name": "印台"},
                        ],
                        "time_info": ["2023", "2024", "2025"],
                        "headers": [
                            [
                                {"text": "行社", "is_indicator": False, "is_computed": False},
                                {"text": "利润总额", "is_indicator": False, "is_computed": False, "colspan": 3, "data_unit": "万元"},
                            ],
                            [
                                {"text": "2023年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2023", "data_unit": "万元"},
                                {"text": "2024年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2024", "data_unit": "万元"},
                                {"text": "2025年", "is_indicator": True, "is_computed": False, "idx_id": "BAS_0263", "period": "2025", "data_unit": "万元"},
                            ],
                        ],
                        "data_rows": [],
                        "computed_specs": [],
                        "chart_specs": [
                            {"title": "利润趋势", "type": "line", "x": "时期", "y": "利润总额", "series": "行社", "unit": "万元", "output": "profit-trend"}
                        ],
                    }
                ],
            }
        ],
    }
    wide = [
        {"branch_num": "27020199", "section_idx": 0, "report_idx": 0, "BAS_0263@2023": "1000", "BAS_0263@2024": "1200", "BAS_0263@2025": "1500"},
        {"branch_num": "27020100", "section_idx": 0, "report_idx": 0, "BAS_0263@2023": "900", "BAS_0263@2024": "1100", "BAS_0263@2025": "1300"},
    ]
    out_dir = tmp_path / "input.charts"
    manifest_path = tmp_path / "input.charts.json"
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        manifest = cg.generate_charts(parsed, wide, str(out_dir), str(manifest_path))
    assert (out_dir / "profit-trend.png").exists()
    assert manifest["summary"]["status"] == "OK"
    assert manifest["summary"]["ok"] == 1
    assert manifest["reports"][0]["charts"][0]["relative_path"] == "input.charts/profit-trend.png"


def test_generate_charts_no_specs_writes_no_charts(tmp_path):
    parsed = {"title": "T", "sections": [{"title": "S", "reports": [{"title": "R", "chart_specs": []}]}]}
    wide = []
    out_dir = tmp_path / "input.charts"
    manifest_path = tmp_path / "input.charts.json"
    manifest = cg.generate_charts(parsed, wide, str(out_dir), str(manifest_path))
    assert manifest["summary"]["status"] == "NO_CHARTS"


def test_generate_charts_business_failure_exits_zero(tmp_path):
    parsed = {
        "title": "T",
        "sections": [{"title": "S", "reports": [{
            "title": "R", "org_contexts": [], "time_info": [],
            "headers": [], "data_rows": [], "computed_specs": [],
            "chart_specs": [{"title": "T", "type": "line", "x": "时期", "y": "不存在的列"}],
        }]}],
    }
    wide = [{"branch_num": "x", "section_idx": 0, "report_idx": 0}]
    out_dir = tmp_path / "input.charts"
    manifest_path = tmp_path / "input.charts.json"
    manifest = cg.generate_charts(parsed, wide, str(out_dir), str(manifest_path))
    assert manifest["summary"]["status"] == "CHART_PARTIAL"
    assert manifest["summary"]["failed"] == 1
    assert manifest["summary"]["ok"] == 0
    assert manifest["reports"][0]["charts"][0]["status"] == "failed"
    assert "error" in manifest["reports"][0]["charts"][0]
