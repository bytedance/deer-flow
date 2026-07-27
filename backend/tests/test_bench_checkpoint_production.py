"""Harness tests for the production-shaped checkpoint benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/checkpoint/bench_production.py"
    spec = importlib.util.spec_from_file_location("bench_production", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module()


def test_expand_cases_sweeps_frequency_for_delta_only() -> None:
    cases = bench.expand_cases(
        modes=["full", "delta"],
        turn_counts=[10],
        payload_bytes=[128],
        snapshot_frequencies=[10, 50],
        repetitions=1,
    )
    delta = [c for c in cases if c.mode == "delta"]
    full = [c for c in cases if c.mode == "full"]
    assert sorted(c.snapshot_frequency for c in delta) == [10, 50]
    assert [c.snapshot_frequency for c in full] == [None]
    assert all(c.history_limits == (10, 50, 200) for c in cases)


def test_expand_cases_alternates_mode_order() -> None:
    cases = bench.expand_cases(
        modes=["full", "delta"],
        turn_counts=[10, 100],
        payload_bytes=[128],
        snapshot_frequencies=[10],
        repetitions=2,
        seed=1,
    )
    grouped_modes: dict[tuple[int, int], list[str]] = {}
    for case in cases:
        grouped_modes.setdefault((case.repetition, case.turns), []).append(case.mode)

    mode_orders = list(grouped_modes.values())
    assert all(set(order) == {"full", "delta"} for order in mode_orders)
    assert all(current == list(reversed(previous)) for previous, current in zip(mode_orders, mode_orders[1:], strict=False))


def test_case_rejects_nonpositive_turns() -> None:
    with pytest.raises(ValueError, match="turns"):
        bench.ProductionCase(
            mode="full",
            turns=0,
            payload_bytes=128,
            snapshot_frequency=None,
            history_limits=(10,),
            read_repetitions=5,
            repetition=0,
            seed=1,
        )


@pytest.mark.parametrize("turns", [1, 2])
def test_case_rejects_turns_consumed_by_warmup(turns: int) -> None:
    with pytest.raises(ValueError, match="warm-up"):
        bench.ProductionCase(
            mode="full",
            turns=turns,
            payload_bytes=128,
            snapshot_frequency=None,
            history_limits=(10,),
            read_repetitions=5,
            repetition=0,
            seed=1,
        )


def test_case_rejects_frequency_on_full_mode() -> None:
    with pytest.raises(ValueError, match="snapshot_frequency"):
        bench.ProductionCase(
            mode="full",
            turns=10,
            payload_bytes=128,
            snapshot_frequency=10,
            history_limits=(10,),
            read_repetitions=5,
            repetition=0,
            seed=1,
        )


def test_cross_mode_digest_gate_fails_both_rows_on_mismatch() -> None:
    base = {"turns": 10, "payload_bytes": 128, "repetition": 0, "success": True, "seed_content_sha256": "a", "state_wire_sha256": "b", "history_wire_sha256": "c"}
    full = {**base, "mode": "full", "snapshot_frequency": None}
    delta = {**base, "mode": "delta", "snapshot_frequency": 10}
    rows = [dict(full), dict(delta)]
    bench.validate_cross_mode_rows(rows)
    assert all(r["success"] for r in rows)

    delta_bad = {**delta, "seed_content_sha256": "DIFFERENT"}
    rows = [dict(full), delta_bad]
    bench.validate_cross_mode_rows(rows)
    assert not any(r["success"] for r in rows)
    assert all(r["error"] == "cross-mode materialized state mismatch" for r in rows)


def test_cross_mode_gate_tolerates_missing_pair() -> None:
    row = {"mode": "full", "snapshot_frequency": None, "turns": 10, "payload_bytes": 128, "repetition": 0, "success": True, "seed_content_sha256": "a", "state_wire_sha256": "b", "history_wire_sha256": "c"}
    rows = [dict(row)]
    bench.validate_cross_mode_rows(rows)
    assert rows[0]["success"] is True


def test_scripted_model_is_deterministic_across_instances() -> None:
    from langchain_core.messages import HumanMessage

    first = bench._ScriptedBenchModel(payload_bytes=16)
    second = bench._ScriptedBenchModel(payload_bytes=16)
    for _ in range(3):
        a = first.invoke([HumanMessage(content="hi", id="h0")])
        b = second.invoke([HumanMessage(content="hi", id="h0")])
        assert a.id == b.id and a.content == b.content and len(a.content) == 16


def test_timing_saver_records_cumulative_ms() -> None:
    import asyncio

    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.memory import InMemorySaver

    timing = bench._TimingSaver(InMemorySaver())
    config = {"configurable": {"thread_id": "t", "checkpoint_ns": "", "checkpoint_id": "c1"}}

    async def go() -> None:
        await timing.aput(config, empty_checkpoint(), {"source": "input", "step": 0, "writes": {}}, {})
        await timing.aput_writes(config, [("ch", "v")], "task")

    asyncio.run(go())
    assert timing.timings_ms["aput"] >= 0
    assert timing.timings_ms["aput_writes"] >= 0
    assert timing._saver is not None


def _reset_checkpoint_freezes(monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow.agents import thread_state
    from deerflow.config.app_config import reset_app_config
    from deerflow.runtime import checkpoint_mode

    reset_app_config()
    monkeypatch.setattr(checkpoint_mode, "_frozen_checkpoint_channel_mode", None)
    monkeypatch.setattr(thread_state, "_frozen_delta_snapshot_frequency", None)


@pytest.mark.parametrize("mode,frequency", [("full", None), ("delta", 10)])
def test_run_case_succeeds_end_to_end_small(tmp_path, monkeypatch, mode, frequency) -> None:
    _reset_checkpoint_freezes(monkeypatch)
    from app.gateway import services as gateway_services
    from deerflow.config.app_config import reset_app_config

    gateway_services._state_accessor_graph_cache.clear()
    case = bench.ProductionCase(
        mode=mode,
        turns=3,
        payload_bytes=32,
        snapshot_frequency=frequency,
        history_limits=(2,),
        read_repetitions=2,
        repetition=0,
        seed=1,
    )
    row = bench._run_case(case, work_dir=tmp_path)
    assert row["success"], row.get("error")
    assert row["message_count"] > 0
    assert row["seed_content_sha256"]
    assert row["state_warm_p50_ms"] >= 0
    # Wire digests must reflect real messages: a duck-typed checkpointer on
    # app.state silently materializes delta channels as empty (Pregel gates
    # replay behind isinstance(checkpointer, BaseCheckpointSaver)), which
    # otherwise passes every assertion above vacuously.
    empty_wire = bench._wire_messages_digest([])
    assert row["state_wire_sha256"] != empty_wire
    assert row["history_wire_sha256"] != bench._combined_digest([empty_wire])
    assert row["wal_bytes"] > 0
    assert row["shm_bytes"] > 0
    # Write cost is merged busy time over concurrent write tasks: it must not
    # exceed the turn wall clock the way a naive latency sum can.
    assert row["checkpoint_write_p50_ms"] <= row["run_turn_p50_ms"]
    gateway_services._state_accessor_graph_cache.clear()
    reset_app_config()


def test_run_case_fails_when_warm_cache_is_not_hit(tmp_path, monkeypatch) -> None:
    """The cold/warm contract is structural: if the accessor cache never holds,
    warm samples silently measure the cold path — the case row must fail."""
    _reset_checkpoint_freezes(monkeypatch)
    from app.gateway import services as gateway_services
    from deerflow.config.app_config import reset_app_config

    gateway_services._state_accessor_graph_cache.clear()
    # Bypass the cache entirely: every accessor resolution rebuilds the graph,
    # so warm reads trip the contract assertion.
    monkeypatch.setattr(
        gateway_services,
        "_state_accessor_graph",
        lambda agent_factory, assistant_id, mode, config: agent_factory(config=config),
    )
    case = bench.ProductionCase(
        mode="full",
        turns=3,
        payload_bytes=32,
        snapshot_frequency=None,
        history_limits=(2,),
        read_repetitions=2,
        repetition=0,
        seed=1,
    )
    row = bench._run_case(case, work_dir=tmp_path)
    assert not row["success"]
    assert "cache was not hit" in row["error"]
    gateway_services._state_accessor_graph_cache.clear()
    reset_app_config()


def test_merged_busy_ms_unions_overlapping_intervals() -> None:
    intervals = [("aput", 0.0, 10.0), ("aput_writes", 5.0, 12.0), ("aput", 20.0, 25.0)]
    assert bench._merged_busy_ms(iter(intervals)) == 17.0
    assert bench._merged_busy_ms(iter([])) == 0.0
