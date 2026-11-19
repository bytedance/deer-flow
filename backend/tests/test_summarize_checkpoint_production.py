"""Tests for the production benchmark summarizer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/checkpoint/summarize_production.py"
    spec = importlib.util.spec_from_file_location("summarize_production", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summ = _load_module()


def _row(mode, rep, *, freq=None, turns=100, payload=128, run_p50=100.0, write_p50=10.0, write_p99=20.0, state_cold=50.0, state_warm=5.0, success=True):
    return {
        "mode": mode,
        "repetition": rep,
        "snapshot_frequency": freq,
        "turns": turns,
        "payload_bytes": payload,
        "success": success,
        "profiled": False,
        "run_turn_p50_ms": run_p50,
        "checkpoint_write_p50_ms": write_p50,
        "checkpoint_write_p99_ms": write_p99,
        "state_cold_ms": state_cold,
        "state_warm_p50_ms": state_warm,
    }


def test_pairs_full_row_against_every_delta_frequency(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [
        _row("full", 0),
        _row("delta", 0, freq=10, run_p50=80.0),
        _row("delta", 0, freq=100, run_p50=90.0),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summaries = summ._summarize(summ._load_jsonl([path]), metrics=["run_turn_p50_ms"])
    assert len(summaries) == 2
    by_freq = {s["snapshot_frequency"]: s for s in summaries}
    assert by_freq[10]["ratio_run_turn_p50_ms"] == 0.8
    assert by_freq[100]["ratio_run_turn_p50_ms"] == 0.9


def test_decision_metrics_emitted(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [_row("full", 0), _row("delta", 0, freq=10, write_p50=10.0, write_p99=50.0)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summaries = summ._summarize(summ._load_jsonl([path]), metrics=["run_turn_p50_ms"])
    assert summaries[0]["delta_snapshot_write_spike"] == 5.0
    assert summaries[0]["delta_cache_effect_ms"] == 45.0
    assert summaries[0]["full_cache_effect_ms"] == 45.0


def test_failed_rows_counted_per_group(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [
        _row("full", 0),
        _row("delta", 0, freq=10),
        _row("delta", 0, freq=100),
        _row("delta", 1, freq=10, success=False),
        _row("delta", 2, freq=10, success=False),
        _row("delta", 1, freq=100, success=False),
        # Different turns: matches no group below.
        _row("delta", 0, freq=10, turns=200, success=False),
        # A failed full row counts toward every group at the same (turns, payload_bytes).
        _row("full", 1, success=False),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summaries = summ._summarize(summ._load_jsonl([path]), metrics=["run_turn_p50_ms"])
    by_freq = {s["snapshot_frequency"]: s for s in summaries}
    assert by_freq[10]["failed_rows"] == 3
    assert by_freq[100]["failed_rows"] == 2


def test_history_limit_metrics_auto_discovered(tmp_path, capsys) -> None:
    path = tmp_path / "rows.jsonl"
    full = _row("full", 0)
    delta = _row("delta", 0, freq=10)
    for row, cold, warm in ((full, 30.0, 12.0), (delta, 60.0, 24.0)):
        row["history_limit_64_cold_ms"] = cold
        row["history_limit_64_warm_p50_ms"] = warm
    path.write_text("\n".join(json.dumps(r) for r in (full, delta)) + "\n")
    assert summ.main([str(path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["ratio_history_limit_64_cold_ms"] == 2.0
    assert out[0]["delta_history_limit_64_warm_p50_ms"] == 24.0


def test_explicit_metrics_override_skips_discovery(tmp_path, capsys) -> None:
    path = tmp_path / "rows.jsonl"
    full = _row("full", 0)
    delta = _row("delta", 0, freq=10)
    for row in (full, delta):
        row["history_limit_64_cold_ms"] = 30.0
    path.write_text("\n".join(json.dumps(r) for r in (full, delta)) + "\n")
    assert summ.main([str(path), "--json", "--metrics", "run_turn_p50_ms"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "delta_history_limit_64_cold_ms" not in out[0]


def test_checkpoint_write_share_emitted_and_zero_guarded(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [
        _row("full", 0, run_p50=100.0, write_p50=10.0),
        _row("delta", 0, freq=10, run_p50=80.0, write_p50=20.0),
        _row("full", 0, turns=200, run_p50=0.0, write_p50=10.0),
        _row("delta", 0, freq=10, turns=200, run_p50=0.0, write_p50=20.0),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summaries = summ._summarize(summ._load_jsonl([path]), metrics=["run_turn_p50_ms"])
    by_turns = {s["turns"]: s for s in summaries}
    assert by_turns[100]["full_checkpoint_write_share"] == 0.1
    assert by_turns[100]["delta_checkpoint_write_share"] == 0.25
    assert "full_checkpoint_write_share" not in by_turns[200]
    assert "delta_checkpoint_write_share" not in by_turns[200]
