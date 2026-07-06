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


def test_run_phase_1_force_continue_skips_lint_checkpoint(tmp_path):
    """With skip_lint_checkpoint=True, the 1.5 checkpoint is bypassed.

    Use a markdown whose lint produces errors but which still parses cleanly
    (a `<thead>` row with a cell that has `data-unit` but no `data-idx`,
    triggering CHATBI-DATAIDX-MISSING).
    """
    from sqlbot_client import MockSQLBotClient

    bad_idx = tmp_path / "bad_idx.md"
    bad_idx.write_text(
        "# Title\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "<table><thead><tr>"
        "<th>label</th>"
        "<th data-unit=\"万元\">no-data-idx-cell</th>"
        "</tr></thead>"
        "<tbody><tr><td>2025-12-31</td><td>x</td></tr></tbody>"
        "</table>\n",
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(md_path=bad_idx, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    # Without force_continue: lint error -> 1.5 checkpoint
    blocked = orch.run_phase_1()
    assert isinstance(blocked, p.CheckpointSignal)
    assert blocked.step == "1.5"
    # With force_continue: 1.5 skipped. Result is Phase1Result, or 3.5 if query
    # has no usable idx.
    result = orch.run_phase_1(force_continue=p.ForceContinue(skip_lint_checkpoint=True))
    if isinstance(result, p.CheckpointSignal):
        assert result.step != "1.5"
    else:
        assert isinstance(result, p.Phase1Result)


def test_run_phase_2_validate_marks_sentinel_for_bad_source(tmp_path):
    """Phase 2 step 8a marks wide cells with ⚠️COMPUTE_FAILED for invalid sources."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # Provide description files matching input.md's prompts to bypass 8d.5.
    desc_dir = tmp_path / "desc"
    desc_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1.description_prompts):
        (desc_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"desc {i}", encoding="utf-8"
        )

    # Bad source: function name mismatch → validate_signature fails
    bad_src = tmp_path / "bad.py"
    bad_src.write_text("def wrong_name(df):\n    return 0\n", encoding="utf-8")

    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={"good_col": str(bad_src)},  # name mismatch is the failure
        descriptions_dir=str(desc_dir),
        stem=stem,
    )
    # Continue to RunResult (compute failures don't abort Phase 2)
    assert isinstance(final, p.RunResult)
    status = json.loads(final.status_json.read_text(encoding="utf-8"))
    # status.json schema is spec-pinned: only 8 flat metrics keys exist (assemble_status:54-63).
    # Detailed per-step metrics live in the sidecar orchestrator-metrics.json.
    assert status["metrics"]["computed_count"] == 1
    assert status["metrics"]["compute_validation_failures"] == 1
    sidecar = json.loads((tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8"))
    assert sidecar["8a_validate"]["total"] == 1
    assert sidecar["8a_validate"]["ok"] == 0


def test_run_phase_2_evaluate_and_apply(tmp_path):
    """Phase 2 evaluates compute source and applies results to wide."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # Provide description files matching input.md's prompts to bypass 8d.5.
    desc_dir = tmp_path / "desc"
    desc_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1.description_prompts):
        (desc_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"desc {i}", encoding="utf-8"
        )

    # Source: takes a DataFrame and returns a Series-like dict.
    # We don't bind it to an actual wide column (the IR may not produce a matching
    # column); the test only asserts the apply step runs without aborting.
    src = tmp_path / "noop.py"
    src.write_text(
        "def noop(df):\n    return {}\n",
        encoding="utf-8",
    )
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={"noop": str(src)},
        descriptions_dir=str(desc_dir),
        stem=stem,
    )
    assert isinstance(final, p.RunResult)
    sidecar = json.loads((tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8"))
    assert "8b_evaluate" in sidecar
    assert "8c_apply" in sidecar


def test_run_phase_2_attach_descriptions_and_8d5_checkpoint(tmp_path):
    """Phase 2 reads description files; 8d.5 checkpoint triggers on missing files."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # No description files → 8d.5 should trigger because we have at least 1
    # description_prompt in input.md and no files exist under descriptions_dir.
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={},
        descriptions_dir=str(tmp_path / "desc"),  # empty dir → 8d.5 triggers
        stem=INPUT_MD.stem,
    )
    if p1.description_prompts:
        assert isinstance(final, p.CheckpointSignal)
        assert final.step == "8d.5"
    else:
        # input.md has no description_prompt → 8d.5 skipped, RunResult
        assert isinstance(final, p.RunResult)
