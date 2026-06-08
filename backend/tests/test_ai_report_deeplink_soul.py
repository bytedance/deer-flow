"""Contract tests for ai-report deep-link direct-execution guidance."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SOUL_PATHS = [
    REPO_ROOT / "agents" / "builtin" / "ai-report--daily" / "SOUL.md",
    REPO_ROOT / "agents" / "builtin" / "ai-report--weekly" / "SOUL.md",
    REPO_ROOT / "agents" / "builtin" / "ai-report--monthly" / "SOUL.md",
]


@pytest.mark.parametrize("soul_path", SOUL_PATHS, ids=[path.parent.name for path in SOUL_PATHS])
def test_deeplink_uses_direct_execute_tool(soul_path: Path):
    """Test that SOUL.md instructs to use report_direct_execute tool."""
    soul_text = soul_path.read_text(encoding="utf-8")

    # Should reference the direct execute tool
    assert "report_direct_execute" in soul_text
    # Should have a "Deep-Link 直达" section
    assert "Deep-Link 直达" in soul_text
    # Should mention parameter齐全 and 缺失 scenarios
    assert "参数齐全" in soul_text
    assert "参数缺失" in soul_text


@pytest.mark.parametrize("soul_path", SOUL_PATHS, ids=[path.parent.name for path in SOUL_PATHS])
def test_deeplink_lists_optional_parameters(soul_path: Path):
    """Test that SOUL.md lists optional parameters for direct execution."""
    soul_text = soul_path.read_text(encoding="utf-8")

    # Should list optional parameters
    assert "equipment_type" in soul_text
    assert "compare_with" in soul_text
    assert "equipment_ids" in soul_text
    assert "kpi_keys" in soul_text


@pytest.mark.parametrize("soul_path", SOUL_PATHS, ids=[path.parent.name for path in SOUL_PATHS])
def test_deeplink_no_dsl_state_machine_constraints(soul_path: Path):
    """Test that SOUL.md no longer contains DSL state machine constraints."""
    soul_text = soul_path.read_text(encoding="utf-8")

    # Should NOT contain DSL state machine step constraints
    assert 'report_template_render_step(..., step_id="kpis")' not in soul_text
    assert 'report_template_render_step(..., step_id="equipment")' not in soul_text
    # Should NOT contain the 8-step DSL execution sequence
    assert "report_template_submit_step(report_run_id=..., step_id=" not in soul_text
