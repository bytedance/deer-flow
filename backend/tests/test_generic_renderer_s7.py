"""Tests for generic_renderer S7 enhancements.

Sprint S7 — covers two new rendering paths:
- Banner-style card (props.style in {warning, danger, info}) renders as
  Markdown quote-block with prefix icon (⚠ / 🛑 / ℹ).
- Confidence badge: card with value in {low, medium, high} renders with a
  color emoji (🔴 / 🟡 / 🟢).
- Banner text fallback order: template → value → title.
- Regular cards (KPI / count) keep their original ``- **title**: value`` output.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def renderer():
    # Stub langgraph for any harness imports the module chain may pull in.
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "harness"))

    from deerflow.report_templates.generic_renderer import render_markdown_generic  # type: ignore

    return render_markdown_generic


def _payload(*sections):
    return {"schema_version": "1", "title": "Test", "sections": list(sections)}


def test_warning_banner_quote_block(renderer):
    md = renderer(_payload({
        "id": "rb", "title": "人工复核提示", "component": "card",
        "props": {"style": "warning", "template": "§13.2 报告需人工复核"},
    }))
    assert "> ⚠ §13.2 报告需人工复核" in md


def test_danger_banner_uses_stop_icon(renderer):
    md = renderer(_payload({
        "id": "rb", "title": "Critical", "component": "card",
        "props": {"style": "danger", "template": "STOP"},
    }))
    assert "> 🛑 STOP" in md


def test_info_banner_uses_info_icon(renderer):
    md = renderer(_payload({
        "id": "rb", "title": "Note", "component": "card",
        "props": {"style": "info", "template": "演示数据"},
    }))
    assert "> ℹ 演示数据" in md


def test_banner_fallback_to_value_when_no_template(renderer):
    md = renderer(_payload({
        "id": "rb", "title": "B", "component": "card",
        "props": {"style": "warning", "value": "Value text"},
    }))
    assert "> ⚠ Value text" in md


def test_banner_fallback_to_title_when_no_template_no_value(renderer):
    md = renderer(_payload({
        "id": "rb", "title": "B", "component": "card",
        "props": {"style": "warning", "title": "Title only"},
    }))
    assert "> ⚠ Title only" in md


def test_confidence_high_green_badge(renderer):
    md = renderer(_payload({
        "id": "c", "title": "Conf", "component": "card",
        "props": {"title": "Confidence", "value": "high"},
    }))
    assert "🟢 High" in md
    assert "**Confidence**: 🟢 High" in md


def test_confidence_medium_yellow_badge(renderer):
    md = renderer(_payload({
        "id": "c", "title": "Conf", "component": "card",
        "props": {"title": "Confidence", "value": "medium"},
    }))
    assert "🟡 Medium" in md


def test_confidence_low_red_badge(renderer):
    md = renderer(_payload({
        "id": "c", "title": "Conf", "component": "card",
        "props": {"title": "Confidence", "value": "low"},
    }))
    assert "🔴 Low" in md


def test_regular_card_no_regression(renderer):
    """Cards without style + non-confidence value keep their old format."""
    md = renderer(_payload({
        "id": "k", "title": "运行率", "component": "card",
        "props": {"title": "运行率", "value": "93.0%"},
    }))
    assert "- **运行率**: 93.0%" in md
    assert "🟢" not in md and "🟡" not in md and "🔴" not in md


def test_card_group_still_works(renderer):
    """card_group with items[] should not be hijacked by banner/confidence logic."""
    md = renderer(_payload({
        "id": "g", "title": "KPIs", "component": "card_group",
        "props": {"items": [
            {"title": "A", "value": "1"},
            {"title": "B", "value": "2"},
        ]},
    }))
    assert "- **A**: 1" in md
    assert "- **B**: 2" in md


def test_confidence_falls_through_when_no_value_string(renderer):
    """When value isn't low/medium/high, fall back to regular card rendering."""
    md = renderer(_payload({
        "id": "k", "title": "X", "component": "card",
        "props": {"title": "Status", "value": "operational"},
    }))
    assert "**Status**: operational" in md
    assert "🟢" not in md and "🟡" not in md and "🔴" not in md
