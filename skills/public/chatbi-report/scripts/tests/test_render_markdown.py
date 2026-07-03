"""Unit tests for scripts/render_markdown.py."""
import json
from pathlib import Path

import pytest

import parse_md as pm
import render_markdown as rm


def test_render_markdown_happy_no_idx_id_in_header(fixture_dir):
    """Chatbi 规则：表头为 `中文名 (单位)` —— 不带 (`BAS_0263`) idx 后缀。"""
    md_path = fixture_dir / "sample_md" / "single_org.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420", "收单商户同比": "0.1833"},
        "raw_cells": {"BAS_0263": "1,420", "收单商户同比": "0.1833"},
    }]
    compute_status: dict = {}
    out = rm.render_markdown(doc, [wide], compute_status)
    # 表头行必须包含中文显示名 + 单位
    assert "贷款收单商户数 (个)" in out
    # Chatbi 差异：表头中不含 (`BAS_0263`) idx 后缀
    assert "(`BAS_0263`)" not in out
    # 计算列表头使用中文业务名 + 单位，不追加内部 computed 标记
    assert "收单商户同比 (%)" in out
    assert "(%)" in out


def test_render_markdown_query_failed_in_header(fixture_dir):
    """标为 ⚠️QUERY_FAILED 的单元格在表头自身里渲染。"""
    md_path = fixture_dir / "sample_md" / "single_org.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "⚠️QUERY_FAILED", "收单商户同比": "—"},
        "raw_cells": {"BAS_0263": None, "收单商户同比": None},
    }]
    out = rm.render_markdown(doc, [wide], {})
    assert "贷款收单商户数 (个) ⚠️QUERY_FAILED" in out


def test_render_markdown_compute_failed_in_header(fixture_dir):
    """status='compute_smoke_failed' 的计算列显示 ⚠️COMPUTE_FAILED。"""
    md_path = fixture_dir / "sample_md" / "single_org.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420", "收单商户同比": "⚠️COMPUTE_FAILED"},
        "raw_cells": {"BAS_0263": "1,420", "收单商户同比": None},
    }]
    out = rm.render_markdown(doc, [wide], {"收单商户同比": "compute_smoke_failed"})
    assert "收单商户同比 ⚠️COMPUTE_FAILED (%)" in out


def test_render_markdown_multi_period_includes_all_periods(fixture_dir):
    """multi_org.md (3 期间 × 4 机构) → 表头含 3 个年份 + 3 个计算列。"""
    md_path = fixture_dir / "sample_md" / "multi_org.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2023-2025", "org_ecd": "王益联社",
        "cells": {
            "BAS_0263@2023": "188.01", "BAS_0263@2024": "495.83", "BAS_0263@2025": "322.78",
            "2023利润同比": "-0.688", "2024利润同比": "1.6372", "2025利润同比": "-0.349",
        },
        "raw_cells": {},
    }]
    out = rm.render_markdown(doc, [wide], {})
    # 3 个年份 + 3 个计算列都进入表头
    assert "2023年" in out and "2024年" in out and "2025年" in out
    assert "2023利润同比 (%)" in out
    assert "2024利润同比 (%)" in out
    assert "2025利润同比 (%)" in out


def test_render_markdown_description_before_table(fixture_dir):
    md_path = fixture_dir / "sample_md" / "multi_org.md"
    doc = pm.parse_file(str(md_path))
    doc.sections[0].reports[0].description_text = "这是描述段。"
    wide = [{
        "data_dt": "2023-2025", "org_ecd": "王益联社",
        "cells": {
            "BAS_0263@2023": "188.01", "BAS_0263@2024": "495.83", "BAS_0263@2025": "322.78",
            "2023利润同比": "-0.688", "2024利润同比": "1.6372", "2025利润同比": "-0.349",
        },
        "raw_cells": {},
    }]
    out = rm.render_markdown(doc, [wide], {})
    assert "### 1.1 整体利润分析\n\n这是描述段。\n\n<table>" in out
    assert '<th rowspan="2">行社</th>' in out
    assert '<td>王益联社</td>' in out


# ---------- chart manifest integration (Task 6) ---------- #

def test_render_markdown_inserts_chart_before_table(tmp_path):
    md = tmp_path / "report.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\" data-unit=\"万元\">利润</th>"
        "</tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    doc = pm.parse_file(str(md))
    wide = [{
        "data_dt": "机构A", "org_ecd": "A",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    manifest = {
        "reports": [{
            "section_idx": 0, "report_idx": 0,
            "charts": [{
                "title": "利润趋势", "type": "line", "status": "ok",
                "relative_path": "input.charts/profit-trend.png",
            }],
        }],
    }
    manifest_path = tmp_path / "charts.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    out = rm.render_markdown(doc, [wide], {}, charts_manifest=str(manifest_path))
    assert "![利润趋势](input.charts/profit-trend.png)" in out
    assert out.index("![利润趋势]") < out.index("<table>")


def test_render_markdown_failed_chart_excluded(tmp_path):
    md = tmp_path / "report.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\" data-unit=\"万元\">利润</th>"
        "</tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    doc = pm.parse_file(str(md))
    wide = [{
        "data_dt": "机构A", "org_ecd": "A",
        "cells": {"BAS_0263": "1"},
        "raw_cells": {"BAS_0263": "1"},
    }]
    manifest = {
        "reports": [{
            "section_idx": 0, "report_idx": 0,
            "charts": [
                {"title": "bad", "type": "bar", "status": "failed", "relative_path": "x.png"},
                {"title": "good", "type": "line", "status": "ok", "relative_path": "input.charts/good.png"},
            ],
        }],
    }
    manifest_path = tmp_path / "charts.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    out = rm.render_markdown(doc, [wide], {}, charts_manifest=str(manifest_path))
    assert "![good](input.charts/good.png)" in out
    assert "![bad]" not in out
