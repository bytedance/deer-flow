from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/summarize_checkpoint_channels.py"
    spec = importlib.util.spec_from_file_location("summarize_checkpoint_channels", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summarize = _load_module()


def _row(mode: str, repetition: int, write_ms: float, checkpoint_bytes: int, *, success: bool = True) -> dict:
    return {
        "success": success,
        "mode": mode,
        "backend": "sqlite",
        "scenario": "append",
        "snapshot_frequency": 1000,
        "update_count": 100,
        "payload_bytes": 128,
        "repetition": repetition,
        "write_total_ms": write_ms,
        "logical_checkpoint_bytes": checkpoint_bytes,
    }


def test_summarize_uses_only_successful_paired_repetitions() -> None:
    rows = [
        _row("full", 0, 10, 1000),
        _row("delta", 0, 5, 200),
        _row("full", 1, 30, 3000),
        _row("delta", 1, 15, 600),
        _row("full", 2, 999, 9999),
        _row("delta", 2, 1, 1, success=False),
    ]

    result = summarize._summarize(rows, metrics=["write_total_ms", "logical_checkpoint_bytes"])

    assert result == [
        {
            "backend": "sqlite",
            "scenario": "append",
            "snapshot_frequency": 1000,
            "update_count": 100,
            "payload_bytes": 128,
            "paired_repetitions": 2,
            "failed_rows": 1,
            "full_write_total_ms": 20.0,
            "delta_write_total_ms": 10.0,
            "ratio_write_total_ms": 0.5,
            "full_logical_checkpoint_bytes": 2000.0,
            "delta_logical_checkpoint_bytes": 400.0,
            "ratio_logical_checkpoint_bytes": 0.2,
        }
    ]


def test_summarize_omits_group_without_a_successful_pair() -> None:
    assert summarize._summarize([_row("full", 0, 10, 1000)], metrics=["write_total_ms"]) == []


def test_summarize_excludes_profiled_pairs_from_baseline_medians() -> None:
    rows = [
        _row("full", 0, 10, 1000),
        _row("delta", 0, 5, 200),
        {**_row("full", 1, 1000, 1000), "profiled": True},
        {**_row("delta", 1, 1000, 200), "profiled": True},
    ]

    result = summarize._summarize(rows, metrics=["write_total_ms"])

    assert result[0]["paired_repetitions"] == 1
    assert result[0]["full_write_total_ms"] == 10.0
    assert result[0]["delta_write_total_ms"] == 5.0


def test_summarize_sorts_numeric_update_counts_numerically() -> None:
    rows = []
    for update_count in (10, 2):
        full = _row("full", 0, 10, 1000)
        delta = _row("delta", 0, 5, 200)
        full["update_count"] = update_count
        delta["update_count"] = update_count
        rows.extend([full, delta])

    result = summarize._summarize(rows, metrics=["write_total_ms"])

    assert [row["update_count"] for row in result] == [2, 10]


def test_load_jsonl_reports_file_and_line_for_malformed_input(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text('{"success": true}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"results\.jsonl:2"):
        summarize._load_jsonl([path])


def test_multiple_inputs_keep_same_numbered_repetitions_separate(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text(
        "".join(json.dumps(row) + "\n" for row in [_row("full", 0, 10, 1000), _row("delta", 0, 5, 200)]),
        encoding="utf-8",
    )
    second.write_text(
        "".join(json.dumps(row) + "\n" for row in [_row("full", 0, 30, 3000), _row("delta", 0, 15, 600)]),
        encoding="utf-8",
    )

    result = summarize._summarize(summarize._load_jsonl([first, second]), metrics=["write_total_ms"])

    assert result[0]["paired_repetitions"] == 2
    assert result[0]["full_write_total_ms"] == 20.0
    assert result[0]["delta_write_total_ms"] == 10.0


def test_multiple_inputs_do_not_cross_pair_single_mode_results(tmp_path: Path) -> None:
    full_only = tmp_path / "full.jsonl"
    delta_only = tmp_path / "delta.jsonl"
    full_only.write_text(json.dumps(_row("full", 0, 10, 1000)) + "\n", encoding="utf-8")
    delta_only.write_text(json.dumps(_row("delta", 0, 5, 200)) + "\n", encoding="utf-8")

    rows = summarize._load_jsonl([full_only, delta_only])

    assert summarize._summarize(rows, metrics=["write_total_ms"]) == []


def test_main_writes_json_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "results.jsonl"
    rows = [_row("full", 0, 10, 1000), _row("delta", 0, 5, 200)]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    rc = summarize.main([str(path), "--metrics", "write_total_ms", "--json"])

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["ratio_write_total_ms"] == 0.5


def test_main_warns_when_profiled_rows_are_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "results.jsonl"
    rows = [
        _row("full", 0, 10, 1000),
        _row("delta", 0, 5, 200),
        {**_row("full", 1, 1000, 1000), "profiled": True},
        {**_row("delta", 1, 1000, 200), "profiled": True},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    rc = summarize.main([str(path), "--metrics", "write_total_ms", "--json"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Skipping 2 profiled row(s)" in captured.err
