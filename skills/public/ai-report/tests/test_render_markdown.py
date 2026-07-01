"""Unit tests for render_markdown (新写, 借鉴 chatbi-report 渲染契约)."""

from __future__ import annotations

from render_markdown import render_markdown


def test_render_minimal_one_section_one_table():
    payload = {
        "title": "Test Report",
        "sections": [{
            "title": "一、章",
            "reports": [{
                "title": "表1",
                "description": None,
                "headers": [["机构", {"text": "存款", "data_unit": "万元", "idx_id": "BAS_001", "period": "202603"}]],
                "rows": [{"branch_num": "1", "BAS_001@202603": 12345.0}],
                "sentinels": [],
                "computed_sentinels": {},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "# Test Report" in out
    assert "## 一、章" in out
    assert "### 表1" in out
    assert "存款" in out
    assert "12345" in out
    assert "(万元)" in out


def test_render_query_failed_sentinel_in_header():
    payload = {
        "title": "t",
        "sections": [{
            "title": "s",
            "reports": [{
                "title": "r",
                "description": None,
                "headers": [[{"text": "A", "data_unit": "元", "idx_id": "A", "period": "202603"}]],
                "rows": [{"branch_num": "1", "A@202603": "⚠️QUERY_FAILED"}],
                "sentinels": ["A@202603"],
                "computed_sentinels": {},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "⚠️QUERY_FAILED" in out


def test_render_computed_column_with_sentinel():
    payload = {
        "title": "t",
        "sections": [{
            "title": "s",
            "reports": [{
                "title": "r",
                "description": None,
                "headers": [[
                    {"text": "branch_num"},
                    {"text": "利润率", "data_unit": "%", "is_computed": True},
                ]],
                "rows": [{"branch_num": "1", "利润率": "⚠️COMPUTE_FAILED"}],
                "sentinels": [],
                "computed_sentinels": {"利润率": "⚠️COMPUTE_FAILED"},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "⚠️COMPUTE_FAILED" in out