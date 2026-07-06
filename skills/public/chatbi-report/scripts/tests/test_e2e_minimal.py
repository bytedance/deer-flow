"""E2E anchor for chatbi-report rewrite — completion gating per ai-report-archived-lesson.

Runs the full happy path with MockSQLBotClient + stub compute sources + stub
description files. Asserts every Phase 1/2 artifact exists and status.json
does not record USER_ABORTED. If this test fails the rewrite is not shippable.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlbot_client import MockSQLBotClient

import pipeline as p


FIXTURE = Path(__file__).parents[2] / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = Path(__file__).parents[2] / "example" / "input.md"


def test_e2e_minimal(tmp_path):
    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))

    # Phase 1
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result), f"expected Phase1Result, got {type(p1).__name__}"
    stem = INPUT_MD.stem
    assert (tmp_path / f"{stem}.parsed.json").exists()
    assert (tmp_path / f"{stem}.query.json").exists()
    assert (tmp_path / f"{stem}.wide.json").exists()
    assert (tmp_path / f"{stem}.ir.json").exists()

    # Simulate agent writing stub compute + description files between phases
    compute_sources: dict[str, str] = {}
    for ir_item in p1.ir:
        src = tmp_path / f"{ir_item['name']}.py"
        src.write_text(
            f"def {ir_item['name']}(df):\n    return {{}}\n",
            encoding="utf-8",
        )
        compute_sources[ir_item["name"]] = str(src)

    descriptions_dir = tmp_path / "desc"
    descriptions_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1.description_prompts):
        (descriptions_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"description text for report {i}", encoding="utf-8"
        )

    # Phase 2
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources=compute_sources,
        descriptions_dir=str(descriptions_dir),
        stem=stem,
    )
    assert isinstance(final, p.RunResult), f"expected RunResult, got {type(final).__name__}"

    # All artifacts
    assert final.report_md.exists()
    assert final.report_md.read_text(encoding="utf-8")  # non-empty
    assert final.report_docx is not None
    assert final.report_docx.exists()
    assert final.status_json.exists()

    # status.json: spec-pinned schema (8 flat metrics keys, see assemble_status:54-63).
    status = json.loads(final.status_json.read_text(encoding="utf-8"))
    assert status.get("error_class") != "USER_ABORTED", status
    assert status.get("exit_step") == 9
    assert status["metrics"]["queried_count"] >= 1
    assert status["metrics"]["query_failures"] == 0  # mock fixture all succeed

    # orchestrator-metrics.json: detailed per-step metrics sidecar.
    sidecar = json.loads(
        (tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8")
    )
    assert "8a_validate" in sidecar
    assert "8b_evaluate" in sidecar
