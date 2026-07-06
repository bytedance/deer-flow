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
