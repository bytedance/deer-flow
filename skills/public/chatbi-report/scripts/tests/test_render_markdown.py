"""Unit tests for scripts/render_markdown.py."""
from pathlib import Path

import pytest

import parse_md as pm
import render_markdown as rm


def test_render_markdown_happy_no_idx_id_in_header(fixture_dir):
    """Chatbi 规则：表头为 `中文名 (单位)` —— 不带 (`BAS_0263`) idx 后缀。"""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    compute_status: dict = {}
    out = rm.render_markdown(doc, [wide], compute_status)
    # 表头行必须包含中文显示名 + 单位
    assert "贷款收单商户数 (个)" in out
    # Chatbi 差异：表头中不含 (`BAS_0263`) idx 后缀
    assert "(`BAS_0263`)" not in out
    # YoY 列上的计算标记
    assert "{{收单商户同比}}" not in out  # 占位符已解析
    assert "收单商户同比 (computed)" in out
    assert "(%)" in out


def test_render_markdown_query_failed_in_header(fixture_dir):
    """标为 ⚠️QUERY_FAILED 的单元格在表头自身里渲染。"""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "⚠️QUERY_FAILED"},
        "raw_cells": {"BAS_0263": None},
    }]
    out = rm.render_markdown(doc, [wide], {})
    assert "贷款收单商户数 (个) ⚠️QUERY_FAILED" in out


def test_render_markdown_compute_failed_in_header(fixture_dir):
    """status='compute_smoke_failed' 的计算列显示 ⚠️COMPUTE_FAILED。"""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420", "收单商户同比": "⚠️COMPUTE_FAILED"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    out = rm.render_markdown(doc, [wide], {"收单商户同比": "compute_smoke_failed"})
    assert "收单商户同比 (computed) ⚠️COMPUTE_FAILED" in out


def test_render_markdown_multi_chapter_includes_section_headers(fixture_dir):
    """multi_chapter.md → 输出同时含 `## 第一章:` 与 `## 第二章:`。"""
    md_path = fixture_dir / "sample_md" / "multi_chapter.md"
    doc = pm.parse_file(str(md_path))
    wide = [[{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }],
    [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0264": "98,765,432", "BAS_0265": "123,456,789"},
        "raw_cells": {"BAS_0264": "98765432", "BAS_0265": "123456789"},
    }]]
    out = rm.render_markdown(doc, wide, {})
    assert "## 第一章: 经营规模" in out
    assert "## 第二章: 资产负债" in out
    # 两个中文显示名都在
    assert "贷款收单商户数 (个)" in out
    assert "贷款余额 (元)" in out
    assert "存款余额 (元)" in out
