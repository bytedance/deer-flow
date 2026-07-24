from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/bench_checkpoint_channels.py"
    spec = importlib.util.spec_from_file_location("bench_checkpoint_channels", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module()


def test_parse_positive_int_csv_deduplicates_in_input_order(capsys: pytest.CaptureFixture[str]) -> None:
    assert bench._parse_positive_int_csv("100,10,100,500", option="--updates") == [100, 10, 500]
    assert "ignored duplicate value(s): 100" in capsys.readouterr().err


def test_parse_choice_csv_reports_duplicate_values(capsys: pytest.CaptureFixture[str]) -> None:
    assert bench._parse_choice_csv("full,full,delta", option="--modes", choices=("full", "delta")) == ["full", "delta"]
    assert "ignored duplicate value(s): full" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "0", "-1", "one", "1,,2"])
def test_parse_positive_int_csv_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="--updates"):
        bench._parse_positive_int_csv(value, option="--updates")


def test_deterministic_message_has_exact_payload_bytes_and_stable_identity() -> None:
    first = bench._message_for_update(3, 128)
    second = bench._message_for_update(3, 128)

    assert first == second
    assert first.id == "bench-message-00000003"
    assert first.type == "ai"
    assert len(first.content.encode("utf-8")) == 128


def test_expand_cases_alternates_modes_without_cross_product_reordering() -> None:
    cases = bench._expand_cases(
        modes=["full", "delta"],
        backends=["sqlite"],
        update_counts=[10, 100],
        payload_bytes=[128],
        repetitions=2,
        seed=7,
    )

    assert [(case.repetition, case.update_count, case.mode) for case in cases] == [
        (0, 10, "full"),
        (0, 10, "delta"),
        (0, 100, "delta"),
        (0, 100, "full"),
        (1, 10, "delta"),
        (1, 10, "full"),
        (1, 100, "full"),
        (1, 100, "delta"),
    ]


def test_oversized_filter_skips_full_and_delta_as_a_comparable_pair() -> None:
    cases = bench._expand_cases(
        modes=["full", "delta"],
        backends=["memory"],
        update_counts=[10, 100],
        payload_bytes=[128],
        repetitions=1,
        seed=1,
    )

    kept, skipped = bench._filter_oversized_pairs(cases, max_bytes=100_000)

    assert {(case.update_count, case.mode) for case in kept} == {(10, "full"), (10, "delta")}
    assert {(case.update_count, case.mode) for case in skipped} == {(100, "full"), (100, "delta")}


def test_oversized_filter_does_not_suppress_a_delta_only_diagnostic() -> None:
    case = bench.BenchmarkCase(
        mode="delta",
        backend="memory",
        update_count=2000,
        payload_bytes=4096,
        repetition=0,
        seed=1,
    )

    kept, skipped = bench._filter_oversized_pairs([case], max_bytes=1)

    assert kept == [case]
    assert skipped == []


def test_help_explains_delta_only_runs_bypass_full_payload_cap() -> None:
    assert "delta-only" in bench._build_parser().format_help()


def test_cross_mode_validation_rejects_materialized_state_mismatch() -> None:
    rows = [
        {
            "success": True,
            "mode": "full",
            "backend": "sqlite",
            "scenario": "append",
            "snapshot_frequency": 1000,
            "update_count": 10,
            "payload_bytes": 128,
            "repetition": 0,
            "actual_message_count": 10,
            "content_sha256": "full-digest",
        },
        {
            "success": True,
            "mode": "delta",
            "backend": "sqlite",
            "scenario": "append",
            "snapshot_frequency": 1000,
            "update_count": 10,
            "payload_bytes": 128,
            "repetition": 0,
            "actual_message_count": 10,
            "content_sha256": "delta-digest",
        },
    ]

    bench._validate_cross_mode_rows(rows)

    assert all(row["success"] is False for row in rows)
    assert all("cross-mode" in row["error"] for row in rows)


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_memory_smoke_case_materializes_expected_state(mode: str, tmp_path: Path) -> None:
    case = bench.BenchmarkCase(
        mode=mode,
        backend="memory",
        update_count=4,
        payload_bytes=64,
        repetition=0,
        seed=1,
    )

    row = bench._run_case(case, work_dir=tmp_path)

    assert row["success"] is True
    assert row["expected_message_count"] == 4
    assert row["actual_message_count"] == 4
    assert row["warm_read_ms"] >= 0
    assert row["cold_read_ms"] >= 0
    assert row["saver_reopen_ms"] == 0
    assert len(row["content_sha256"]) == 64
    assert row["db_bytes"] is None
    assert row["logical_checkpoint_bytes"] is not None


def test_memory_case_keeps_timings_when_private_storage_stats_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = bench.BenchmarkCase(
        mode="delta",
        backend="memory",
        update_count=2,
        payload_bytes=32,
        repetition=0,
        seed=1,
    )

    def fail_storage_stats(*_args, **_kwargs):
        raise AttributeError("private saver layout changed")

    monkeypatch.setattr(bench, "_memory_storage_stats", fail_storage_stats)

    row = bench._run_case(case, work_dir=tmp_path)

    assert row["success"] is True
    assert row["write_total_ms"] >= 0
    assert row["logical_checkpoint_bytes"] is None
    assert row["logical_write_bytes"] is None
    assert row["checkpoint_rows"] is None
    assert row["write_rows"] is None
    assert "private saver layout changed" in row["storage_stats_error"]


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_sqlite_smoke_case_reports_durable_and_logical_storage(mode: str, tmp_path: Path) -> None:
    case = bench.BenchmarkCase(
        mode=mode,
        backend="sqlite",
        update_count=3,
        payload_bytes=64,
        repetition=0,
        seed=2,
    )

    row = bench._run_case(case, work_dir=tmp_path)

    assert row["success"] is True
    assert row["db_bytes"] > 0
    assert row["durable_db_bytes"] > 0
    assert row["logical_checkpoint_bytes"] > 0
    assert row["logical_write_bytes"] > 0
    assert row["checkpoint_rows"] > 0
    assert row["write_rows"] > 0


def test_controller_writes_versioned_jsonl_without_sensitive_case_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "result.jsonl"
    child_git_shas = []

    def fake_run_child(case, *, timeout_seconds, git_sha, profile_dir=None):
        child_git_shas.append(git_sha)
        return {
            "schema_version": 1,
            "benchmark_version": 1,
            "success": True,
            "error": None,
            "mode": case.mode,
            "backend": case.backend,
            "scenario": case.scenario,
            "snapshot_frequency": case.snapshot_frequency,
            "update_count": case.update_count,
            "payload_bytes": case.payload_bytes,
            "repetition": case.repetition,
            "actual_message_count": case.update_count,
            "content_sha256": "same",
        }

    monkeypatch.setattr(bench, "_run_child_case", fake_run_child)
    monkeypatch.setattr(bench, "_resolve_git_sha", lambda: "controller-sha")

    rc = bench.main(
        [
            "--modes",
            "full,delta",
            "--backends",
            "memory",
            "--updates",
            "2",
            "--payload-bytes",
            "32",
            "--repetitions",
            "1",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["mode"] for row in rows] == ["full", "delta"]
    assert all(row["schema_version"] == 1 for row in rows)
    assert all("work_dir" not in row and "database_path" not in row for row in rows)
    assert child_git_shas == ["controller-sha", "controller-sha"]


def test_profiled_case_writes_loadable_stats(tmp_path: Path) -> None:
    case = bench.BenchmarkCase(
        mode="delta",
        backend="memory",
        update_count=2,
        payload_bytes=32,
        repetition=0,
        seed=3,
    )
    profile_path = tmp_path / bench._profile_filename(case)

    row = bench._run_profiled_case(case, work_dir=tmp_path / "work", profile_path=profile_path)

    assert row["success"] is True
    assert row["profiled"] is True
    assert profile_path.is_file()
    assert profile_path.stat().st_size > 0
