"""Tests for follow-up optimizations identified in custom e2e handoff.

Two surfaces covered:

1. ``generic_renderer._render_single_card`` — generic-dict fallback so cards
   like ``overall_status: {level, summary}`` and ``data_coverage: {requested_metrics, ...}``
   no longer collapse to ``_(no cards)_``. Tests assert the new key-label
   rendering preserves both author-supplied canonical cards AND the new
   fallback behaviour.

2. ``failure_analysis._flatten_method_block`` — converts the nested
   method_block dict (5why/fishbone/fmea) into a uniform list of rows so a
   single DSL ``component: table`` can render any method.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"


@pytest.fixture(scope="module")
def renderer():
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)
    sys.path.insert(0, str(REPO_ROOT / "backend" / "packages" / "harness"))

    from deerflow.report_templates.generic_renderer import render_markdown_generic  # type: ignore

    return render_markdown_generic


def _payload(*sections):
    return {"schema_version": "1", "title": "Test", "sections": list(sections)}


# ---------------------------------------------------------------------------
# Optimization 1: generic-dict card fallback
# ---------------------------------------------------------------------------


def test_card_overall_status_renders_key_value_bullets(renderer):
    """``overall_status: {level, summary}`` must NOT collapse to ``_(no cards)_``."""
    md = renderer(_payload({
        "id": "ov", "title": "概览", "component": "card",
        "props": {"level": "critical", "summary": "分析 4 个指标，发现 6 项要点。"},
    }))
    assert "_(no cards)_" not in md
    assert "**level**: critical" in md
    assert "**summary**" in md and "分析 4 个指标" in md


def test_card_data_coverage_renders_list_values_as_json(renderer):
    """List/dict values get JSON-stringified into the bullet."""
    md = renderer(_payload({
        "id": "dc", "title": "数据覆盖", "component": "card",
        "props": {
            "requested_metrics": ["runtime_rate", "alarm_count"],
            "missing_metrics": [],
            "time_coverage_pct": 1.0,
        },
    }))
    assert "_(no cards)_" not in md
    assert "requested metrics" in md  # underscore → space conversion in label
    assert "runtime_rate" in md
    assert "missing metrics" in md


def test_card_canonical_form_unchanged(renderer):
    """Regression: ``{title, value}`` cards still render the old way."""
    md = renderer(_payload({
        "id": "k", "title": "运行率", "component": "card",
        "props": {"title": "运行率", "value": "93.0%"},
    }))
    assert "- **运行率**: 93.0%" in md
    # Generic fallback MUST NOT activate when title/value are present.
    assert "**title**" not in md  # never expose the raw "title" key as a bullet


def test_card_meta_keys_excluded_from_fallback(renderer):
    """Banner-meta keys (style/template/icon/color) must NOT appear as bullets
    when an author-supplied dict mixes them with payload."""
    md = renderer(_payload({
        "id": "x", "title": "X", "component": "card",
        "props": {
            "style": "info",  # banner-style → triggers _render_banner_card path
            "template": "info text",
            "extra_field": "should-not-appear-because-banner-wins",
        },
    }))
    # Banner path takes priority — output is a quote block, NOT a bullet list
    assert "> ℹ info text" in md
    assert "- **style**" not in md


def test_card_empty_dict_after_meta_filter_renders_nothing(renderer):
    """A card whose props only contain meta keys (no payload, no banner style)
    must NOT crash — it just produces no bullet lines for this card."""
    md = renderer(_payload({
        "id": "x", "title": "Edge", "component": "card",
        "props": {"icon": "📊", "color": "blue"},  # no style/template/title/value
    }))
    # No bullets emitted; the section heading still appears.
    assert "## Edge" in md
    # The fallback's empty-payload branch is hit; ``_(no cards)_`` is the
    # synthetic placeholder from the outer loop when zero lines were produced.
    assert "_(no cards)_" in md


# ---------------------------------------------------------------------------
# Optimization 3: method_block → method_table flattening
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def failure_analysis_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    # _stub_helpers is a transitive import
    helpers_spec = importlib.util.spec_from_file_location("_stub_helpers", SCRIPTS_DIR / "_stub_helpers.py")
    helpers = importlib.util.module_from_spec(helpers_spec)
    sys.modules["_stub_helpers"] = helpers
    helpers_spec.loader.exec_module(helpers)
    # _data_providers is also needed by failure_analysis import chain in scope
    dp_spec = importlib.util.spec_from_file_location("_data_providers", SCRIPTS_DIR / "_data_providers.py")
    dp = importlib.util.module_from_spec(dp_spec)
    sys.modules["_data_providers"] = dp
    dp_spec.loader.exec_module(dp)

    spec = importlib.util.spec_from_file_location("failure_analysis", SCRIPTS_DIR / "failure_analysis.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["failure_analysis"] = module
    spec.loader.exec_module(module)
    return module


def test_flatten_five_why_block(failure_analysis_module):
    """5Why method_block → 5 rows with ``Level N`` positions."""
    block = {
        "method": "five_why",
        "why_chain": [
            {"level": 1, "why": "Q1", "candidate_cause": "C1", "finding_id": "FA-5W-L1"},
            {"level": 2, "why": "Q2", "candidate_cause": "C2", "finding_id": "FA-5W-L2"},
            {"level": 3, "why": "Q3", "candidate_cause": "C3", "finding_id": "FA-5W-L3"},
        ],
    }
    rows = failure_analysis_module._flatten_method_block(block)
    assert len(rows) == 3
    assert rows[0] == {
        "position": "Level 1",
        "label": "Q1",
        "detail": "C1",
        "evidence_hint": "FA-5W-L1",
    }
    assert rows[2]["position"] == "Level 3"


def test_flatten_fishbone_block(failure_analysis_module):
    """Fishbone method_block → one row per (category, item) pair."""
    block = {
        "method": "fishbone",
        "branches": [
            {"category": "人", "items": [{"label": "a", "weight": "high", "evidence_hint": "h1"}]},
            {"category": "机", "items": [
                {"label": "b", "weight": "medium", "evidence_hint": "h2"},
                {"label": "c", "weight": "low", "evidence_hint": "h3"},
            ]},
            {"category": "料", "items": []},
        ],
    }
    rows = failure_analysis_module._flatten_method_block(block)
    assert len(rows) == 3  # empty categories yield zero rows
    assert rows[0]["position"] == "人"
    assert rows[1]["position"] == "机"
    assert "weight=high" in rows[0]["detail"]
    assert "weight=medium" in rows[1]["detail"]


def test_flatten_fmea_block_preserves_rpn(failure_analysis_module):
    """FMEA method_block → one row per fmea_row with RPN in the detail."""
    block = {
        "method": "fmea",
        "fmea_rows": [
            {"id": "FMEA-001", "mode": "mode-a", "effect": "e-a", "cause": "c-a",
             "severity": 8, "occurrence": 4, "detection": 6, "rpn": 192, "evidence_hint": "INSP-1"},
        ],
    }
    rows = failure_analysis_module._flatten_method_block(block)
    assert len(rows) == 1
    assert rows[0]["position"] == "FMEA-001"
    assert rows[0]["label"] == "mode-a"
    detail = rows[0]["detail"]
    assert "RPN=192" in detail
    assert "S=8" in detail
    assert "O=4" in detail
    assert "D=6" in detail


def test_flatten_unknown_method_returns_empty(failure_analysis_module):
    rows = failure_analysis_module._flatten_method_block({"method": "novel_method"})
    assert rows == []
