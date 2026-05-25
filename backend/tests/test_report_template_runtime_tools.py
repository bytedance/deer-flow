"""Regression tests for report template runtime tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.report_templates.runtime.state import RuntimeState, read_state, write_state
from deerflow.tools.builtins import report_template_runtime_tools as rt


def test_render_report_tool_does_not_embed_ui_block_markers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``render_report`` must NOT embed ``<!--ui_block:...-->`` markers because
    they would leak into message history and cause blocks from earlier report
    runs to be recovered alongside the current run's blocks."""
    report_run_id = "rr_TESTREPORT0000000001"
    thread_id = "thread-report-1"
    run_dir = tmp_path / "report-runs" / report_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    state = RuntimeState(
        report_run_id=report_run_id,
        thread_id=thread_id,
        template_id="tpl_TESTREPORT0000000001",
        status="payload_ready",
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
    )
    write_state(run_dir, state)
    (run_dir / "report_payload.json").write_text(
        json.dumps({"run": {"id": report_run_id}, "sections": []}),
        encoding="utf-8",
    )

    rendered_block = {
        "schema_version": "1.0",
        "type": "ui_block",
        "action": "create",
        "block_id": "report-block-1",
        "component": "markdown",
        "props": {"content": "hello"},
        "interactive": False,
    }

    monkeypatch.setattr(
        rt,
        "get_config",
        lambda: {"configurable": {"thread_id": thread_id}},
    )
    monkeypatch.setattr(rt, "_run_output_dir", lambda _thread_id, _report_run_id: run_dir)
    monkeypatch.setattr(rt, "render_report_blocks", lambda payload, base_sequence=10: [rendered_block])

    output = rt.report_template_render_report_tool.invoke({"report_run_id": report_run_id})

    assert '"blocks_pushed": 1' in output
    assert '"status": "rendered"' in output
    assert "<!--ui_block:" not in output
    assert read_state(run_dir).status == "rendered"
