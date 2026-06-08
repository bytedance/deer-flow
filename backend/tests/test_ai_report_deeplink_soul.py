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
def test_deeplink_kpis_must_submit_without_rendering(soul_path: Path):
    soul_text = soul_path.read_text(encoding="utf-8")

    assert 'step_id="kpis"' in soul_text
    assert 'payload={"kpi_keys": [...]}' in soul_text
    assert "report_template_submit_step" in soul_text
    assert "report_template_render_step(..., step_id=\"kpis\")" in soul_text
    assert "禁止" in soul_text


@pytest.mark.parametrize("soul_path", SOUL_PATHS, ids=[path.parent.name for path in SOUL_PATHS])
def test_deeplink_equipment_must_submit_without_rendering(soul_path: Path):
    soul_text = soul_path.read_text(encoding="utf-8")

    assert 'step_id="equipment"' in soul_text
    assert 'payload={"equipment_ids": [...], "equipment_labels": [...]}' in soul_text
    assert "report_template_submit_step" in soul_text
    assert "report_template_render_step(..., step_id=\"equipment\")" in soul_text


@pytest.mark.parametrize("soul_path", SOUL_PATHS, ids=[path.parent.name for path in SOUL_PATHS])
def test_deeplink_kpis_forbids_list_equipment_lookup(soul_path: Path):
    soul_text = soul_path.read_text(encoding="utf-8")

    assert "kpi_keys" in soul_text
    assert "list_equipment.py" in soul_text
    assert "kpis.before_step" in soul_text
    assert "Organize API" in soul_text
