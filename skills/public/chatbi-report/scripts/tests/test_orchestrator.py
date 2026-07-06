"""Unit tests for scripts/pipeline.py (Orchestrator + dataclasses)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import pipeline as p


FIXTURE = Path(__file__).parents[1] / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = Path(__file__).parents[1] / "example" / "input.md"


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
