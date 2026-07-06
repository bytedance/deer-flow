"""Unit tests for scripts/pipeline.py (Orchestrator + dataclasses)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import pipeline as p


FIXTURE = Path(__file__).parents[2] / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = Path(__file__).parents[2] / "example" / "input.md"


def test_dataclasses_construct_with_minimal_args():
    """All 5 dataclasses can be constructed with their typed fields."""
    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=Path("/tmp/x"))
    assert cfg.md_path == INPUT_MD
    assert cfg.out_dir == Path("/tmp/x")
    assert cfg.mock_fixture is None
    assert cfg.skip_docx is False
    assert cfg.style_path is None

    fc = p.ForceContinue()
    assert fc.skip_lint_checkpoint is False
    assert fc.skip_query_checkpoint is False

    sig = p.CheckpointSignal(
        step="1.5",
        metrics={"n_err": 1, "n_warn": 0},
        artifacts={"parsed": Path("/tmp/x/input.parsed.json")},
        message="lint found 1 error",
    )
    assert sig.step == "1.5"
    assert sig.metrics["n_err"] == 1
    assert sig.message == "lint found 1 error"

    pr = p.Phase1Result(
        parsed={"sections": []},
        wide={"rows": [], "cols": []},
        ir=[],
        description_prompts=[],
        metrics={},
        runlog=[],
        artifacts={},
    )
    assert pr.ir == []

    rr = p.RunResult(
        report_md=Path("/tmp/x/report.md"),
        report_docx=Path("/tmp/x/report.docx"),
        status_json=Path("/tmp/x/status.json"),
        metrics={},
    )
    assert rr.report_md == Path("/tmp/x/report.md")


def test_orchestrator_constructor_stores_cfg_and_sqlbot():
    """Constructor accepts either MockSQLBotClient or RealSQLBotClient."""
    from sqlbot_client import MockSQLBotClient, RealSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=Path("/tmp/x"))

    mock_client = MockSQLBotClient(str(FIXTURE))
    orch_mock = p.Orchestrator(cfg, mock_client)
    assert orch_mock._cfg is cfg
    assert orch_mock._sqlbot is mock_client

    real_client = RealSQLBotClient(base_url="http://sqlbot.lan:9070")
    orch_real = p.Orchestrator(cfg, real_client)
    assert orch_real._sqlbot is real_client


def test_run_phase_1_lint_and_parse_writes_parsed_json(tmp_path):
    """Phase 1 step 1 (lint) + step 2 (parse) writes out_dir/{stem}.parsed.json."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.parsed.json").exists()
    parsed = json.loads((tmp_path / "input.parsed.json").read_text(encoding="utf-8"))
    assert "sections" in parsed
    assert parsed["title"]  # non-empty title from input.md
    # metrics for steps 1 and 2 are present
    assert "1_lint" in result.metrics
    assert "2_parse" in result.metrics
    assert result.metrics["2_parse"]["n_sec"] >= 1
    assert result.metrics["2_parse"]["n_rep"] >= 1


def test_run_phase_1_query_writes_query_json(tmp_path):
    """Phase 1 step 3 (query) writes out_dir/{stem}.query.json with mock SQLBot."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.query.json").exists()
    query = json.loads((tmp_path / "input.query.json").read_text(encoding="utf-8"))
    assert "results" in query
    assert len(query["results"]) >= 1
    assert "3_query" in result.metrics
    assert result.metrics["3_query"]["ok"] >= 1
    assert result.metrics["3_query"]["total"] >= 1


def test_run_phase_1_lint_checkpoint_on_broken_md(tmp_path):
    """Phase 1 returns CheckpointSignal(step='1.5') when lint has errors."""
    from sqlbot_client import MockSQLBotClient

    broken = tmp_path / "broken.md"
    broken.write_text(
        "# Title\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "| missing-data-idx attr | header |\n"
        "| --- | --- |\n"
        "| cell1 | cell2 |\n",
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(md_path=broken, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.CheckpointSignal)
    assert result.step == "1.5"
    assert result.metrics["1_lint"]["n_err"] >= 1


def test_run_phase_1_query_checkpoint_when_all_fail(tmp_path):
    """Phase 1 returns CheckpointSignal(step='3.5') when query has any failure.

    Per 2026-06-27 policy reversal: always trigger 3.5, even when ok == 0.
    """
    from sqlbot_client import MockSQLBotClient

    fail_fixture = tmp_path / "fail.json"
    fail_fixture.write_text(
        json.dumps({"BAS_0263": {"success": False, "data": []}}),
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(
        md_path=INPUT_MD, out_dir=tmp_path, mock_fixture=fail_fixture,
    )
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(fail_fixture)))
    result = orch.run_phase_1()
    assert isinstance(result, p.CheckpointSignal)
    assert result.step == "3.5"
    assert result.metrics["3_query"]["ok"] < result.metrics["3_query"]["total"]
    assert (tmp_path / "input.query.json").exists()  # written before checkpoint


def test_run_phase_1_assemble_and_extract_ir(tmp_path):
    """Phase 1 steps 4+6 produce wide.json + ir.json; Phase1Result fully populated."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.wide.json").exists()
    assert (tmp_path / "input.ir.json").exists()
    assert "4_assemble" in result.metrics
    assert "6_ir" in result.metrics
    assert isinstance(result.wide, list)  # flat list[dict], section_idx/report_idx per row
    assert all({"section_idx", "report_idx"} <= set(r.keys()) for r in result.wide)
    assert isinstance(result.ir, list)
    # description_prompts collected per-report (input.md may have none)
    assert isinstance(result.description_prompts, list)
