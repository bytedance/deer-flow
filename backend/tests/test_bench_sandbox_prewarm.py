"""Offline real-graph checks; Events control model/startup overlap, not sleeps."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from scripts.benchmark.sandbox import bench_prewarm as bench


class EventProvider(SandboxProvider):
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.active = {}
        self.released = []
        self.executed = []
        self._lock = threading.Lock()
        self._warm_pool = {}

    def acquire(self, thread_id=None, *, user_id=None):
        raise AssertionError("async tool path must not fall back to sync acquire")

    async def acquire_async(self, thread_id=None, *, user_id=None):
        self.started.set()
        # The real provider drains non-cancellable startup on cancellation.
        task = asyncio.create_task(self.finish.wait())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        sid = f"{user_id}:{thread_id}"
        self.active[sid] = FakeSandbox(sid, self.executed)
        return sid

    def get(self, sid):
        return self.active.get(sid)

    def get_scoped(self, sid, *, thread_id, user_id):
        return self.get(sid) if sid == f"{user_id}:{thread_id}" else None

    def release(self, sid):
        self.released.append(sid)
        resource = self.active.pop(sid, None)
        if resource:
            self._warm_pool[sid] = (resource, 0)

    def _active_count_locked(self):
        return len(self.active)

    def destroy(self, sid):
        self._warm_pool.pop(sid, None)
        return True


class FakeSandbox:
    def __init__(self, sid, executed):
        self.id = sid
        self.executed = executed

    def execute_command(self, command, **kwargs):
        self.executed.append(command)
        return bench.COMMAND_MARKER

    def release_command_scope(self, owner_id):
        pass


@pytest.fixture
def setup(monkeypatch, tmp_path):
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider"))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(str(tmp_path)))
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.sandbox.tools.get_app_config", lambda: config)
    provider = EventProvider()
    set_sandbox_provider(provider)
    yield provider, config
    reset_sandbox_provider()


@pytest.fixture
def observed(setup):
    provider, _ = setup
    with bench.observe_provider(provider):
        yield setup


async def run_after_prewarm_ready(provider, config, *, case, thread_id):
    """Release the scripted first response only after the speculative lease exists."""
    trace, gate = bench.Trace(), asyncio.Event()
    task = asyncio.create_task(bench.run_case(provider, config, case=case, prewarm=True, model_delay=0, thread_id=thread_id, user_id="alice", trace=trace, model_gate=gate))
    try:
        await asyncio.wait_for(trace.model_started.wait(), 2)
        await asyncio.wait_for(trace.acquire_ready.wait(), 2)
        gate.set()
        return await asyncio.wait_for(task, 3)
    finally:
        provider.finish.set()
        gate.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_real_graph_prewarm_starts_during_model_and_is_claimed_once(observed):
    provider, config = observed
    model_gate = asyncio.Event()
    trace = bench.Trace()
    task = asyncio.create_task(bench.run_case(provider, config, case="tool", prewarm=True, model_delay=0, thread_id="overlap", user_id="alice", trace=trace, model_gate=model_gate))
    try:
        await asyncio.wait_for(trace.model_started.wait(), 2)
        await asyncio.wait_for(provider.started.wait(), 2)
        assert not provider.executed
        assert not trace.tool_requested.is_set()
        provider.finish.set()
        await asyncio.wait_for(trace.acquire_ready.wait(), 2)
        model_gate.set()
        row = await asyncio.wait_for(task, 3)
    finally:
        provider.finish.set()
        model_gate.set()
        await asyncio.gather(task, return_exceptions=True)
    assert row["success"], json.dumps(row)
    assert row["acquire_calls"] == 1
    assert row["prewarm_reused"] is True
    assert row["tool_output_valid"] is True
    assert provider.executed and provider.released == ["alice:overlap"]
    assert not provider.active


@pytest.mark.anyio
async def test_prewarm_reused_survives_a_coarse_clock_tie(observed, monkeypatch):
    """Pin #7044: a same-tick acquire/tool timestamp must not unclassify a reused lease.

    Coarse monotonic clocks (Windows, ~15.6 ms granularity) can quantize the
    prewarm acquire and the tool request into the same tick; the former strict
    `<` classification then dropped the genuine prewarm from the speculative
    set. Event-state capture must keep it classified as speculative.
    """
    provider, config = observed
    coarse_s = 0.015
    real_monotonic = time.monotonic

    def coarse_monotonic():
        return math.floor(real_monotonic() / coarse_s) * coarse_s

    monkeypatch.setattr(bench.time, "monotonic", coarse_monotonic)
    # Spin until a fresh quantized bucket starts, so the whole overlap scenario
    # lands inside the same tick deterministically.
    current_bucket = coarse_monotonic()
    while coarse_monotonic() == current_bucket:
        await asyncio.sleep(0.001)

    model_gate = asyncio.Event()
    trace = bench.Trace()
    task = asyncio.create_task(bench.run_case(provider, config, case="tool", prewarm=True, model_delay=0, thread_id="coarse-tick", user_id="alice", trace=trace, model_gate=model_gate))
    try:
        await asyncio.wait_for(trace.model_started.wait(), 2)
        await asyncio.wait_for(provider.started.wait(), 2)
        provider.finish.set()
        await asyncio.wait_for(trace.acquire_ready.wait(), 2)
        model_gate.set()
        row = await asyncio.wait_for(task, 3)
    finally:
        provider.finish.set()
        model_gate.set()
        await asyncio.gather(task, return_exceptions=True)
    assert trace.acquisitions[0]["started"] == trace.timestamps["tool_requested"], "precondition: the acquire and the tool request must share one quantized tick"
    assert row["success"], json.dumps(row)
    assert row["acquire_calls"] == 1
    assert row["prewarm_reused"] is True


@pytest.mark.anyio
async def test_real_graph_baseline_waits_until_tool_to_start(observed):
    provider, config = observed
    model_gate = asyncio.Event()
    trace = bench.Trace()
    task = asyncio.create_task(bench.run_case(provider, config, case="tool", prewarm=False, model_delay=0, thread_id="lazy", user_id="alice", trace=trace, model_gate=model_gate))
    try:
        await asyncio.wait_for(trace.model_started.wait(), 2)
        assert not provider.started.is_set()
        model_gate.set()
        await asyncio.wait_for(provider.started.wait(), 2)
        assert trace.tool_requested.is_set()
        provider.finish.set()
        row = await asyncio.wait_for(task, 3)
    finally:
        model_gate.set()
        provider.finish.set()
        await asyncio.gather(task, return_exceptions=True)
    assert row["success"] and row["acquire_calls"] == 1, json.dumps(row)
    assert row["prewarm_reused"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("case,expected_acquires", [("plain", 0), ("fenced_no_tool", 1), ("model_error", 1)])
async def test_no_tool_and_failure_close_actual_graph_ownership(observed, case, expected_acquires):
    provider, config = observed
    provider.finish.set()
    if expected_acquires:
        row = await run_after_prewarm_ready(provider, config, case=case, thread_id=case)
    else:
        row = await bench.run_case(provider, config, case=case, prewarm=True, model_delay=0, thread_id=case, user_id="alice")
    assert row["success"], json.dumps(row)
    assert row["acquire_calls"] == expected_acquires
    assert row["unused_prewarm"] is bool(expected_acquires)
    assert not provider.active and not provider.executed
    assert row["lease_remaining"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("prewarm", [False, True])
async def test_cancelled_graph_drains_started_acquire_before_reporting_cleanup(observed, prewarm):
    provider, config = observed
    trace = bench.Trace()
    task = asyncio.create_task(bench.run_case(provider, config, case="cancel", prewarm=prewarm, model_delay=0, thread_id="cancel", user_id="alice", trace=trace))
    try:
        await asyncio.wait_for(trace.cancel_requested.wait(), 2)
        assert not task.done()
        provider.finish.set()
        row = await asyncio.wait_for(task, 3)
    finally:
        provider.finish.set()
        await asyncio.gather(task, return_exceptions=True)
    assert row["success"] and row["outcome"] == "cancelled", json.dumps(row)
    assert row["lease_remaining"] is False
    assert not provider.active


@pytest.mark.anyio
async def test_tool_semantic_failure_is_not_a_successful_latency_row(observed, monkeypatch):
    provider, config = observed
    provider.finish.set()
    monkeypatch.setattr(FakeSandbox, "execute_command", lambda self, command, **kwargs: "Error: injected command failure")
    row = await bench.run_case(provider, config, case="tool", prewarm=False, model_delay=0, thread_id="bad-tool", user_id="alice")
    assert row["success"] is False
    assert row["tool_output_valid"] is False
    assert row["lease_remaining"] is False


@pytest.mark.anyio
async def test_two_users_keep_trace_and_execution_ownership_separate(observed):
    provider, config = observed
    provider.finish.set()
    rows = await asyncio.gather(*[bench.run_case(provider, config, case="tool", prewarm=True, model_delay=0, thread_id="same-thread", user_id=user) for user in ("alice", "bob")])
    assert all(row["success"] for row in rows), rows
    assert [row["sandbox_ids"] for row in rows] == [["alice:same-thread"], ["bob:same-thread"]]
    assert all(row["acquire_calls"] == 1 and row["release_calls"] == 1 for row in rows)
    assert not provider.active


@pytest.mark.anyio
async def test_matrix_retains_each_variant_and_cleans_exact_batch_resources(setup, tmp_path):
    provider, config = setup
    provider.finish.set()
    args = SimpleNamespace(seed=5002, cases=["tool"], model_delays=[0], iterations=1, concurrency=2, users=2, run_id="matrix")
    path = tmp_path / "rows.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        assert await bench.run_matrix(provider, config, args, stream)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    rows = [row for row in records if row["record_type"] == "prewarm_case"]
    assert len(rows) == 4
    assert all(row["acquire_calls"] == 1 and row["release_calls"] == 1 for row in rows)
    assert {row["prewarm"] for row in rows} == {False, True}
    assert len({row["thread_id"] for row in rows}) == 4
    assert all(row["started_monotonic_s"] < row["finished_monotonic_s"] for row in rows)
    assert not provider.active and not provider._warm_pool
    resets = [row for row in records if row["record_type"] == "batch_cleanup"]
    assert len(resets) == 2 and all(row["success"] for row in resets)


@pytest.mark.parametrize("interval", ["0", "nan", "-1"])
def test_invalid_resource_interval_rejected_before_provider_creation(monkeypatch, tmp_path, interval):
    monkeypatch.setattr(bench, "_make_aio_provider", lambda config: pytest.fail("invalid arguments must not provision containers"))
    with pytest.raises(SystemExit) as exc:
        bench.main(["--output", str(tmp_path / "rows.jsonl"), "--resource-interval", interval])
    assert exc.value.code == 2


@pytest.mark.anyio
async def test_expected_model_failure_cannot_mask_cleanup_failure(observed, monkeypatch):
    provider, config = observed
    provider.finish.set()

    def fail_release(sid):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(provider, "release", fail_release)
    row = await run_after_prewarm_ready(provider, config, case="model_error", thread_id="cleanup-error")
    assert row["success"] is False
    assert row["cleanup_error_type"] == "OSError"


@pytest.mark.anyio
async def test_failed_acquire_records_its_own_finish_time(setup, monkeypatch):
    provider, _ = setup

    async def fail(*args, **kwargs):
        raise RuntimeError("injected acquire failure")

    monkeypatch.setattr(provider, "acquire_async", fail)
    trace = bench.Trace()
    token = bench._TRACE.set(trace)
    try:
        with bench.observe_provider(provider):
            with pytest.raises(RuntimeError, match="injected acquire failure"):
                await provider.acquire_async("thread", user_id="alice")
        entry = trace.acquisitions[0]
        assert entry["finished"] >= entry["started"]
        assert "ready" not in entry
    finally:
        bench._TRACE.reset(token)


@pytest.mark.anyio
async def test_failed_batch_destroy_is_recorded_and_stops_matrix(setup, monkeypatch, tmp_path):
    provider, config = setup
    provider.finish.set()

    def fail_destroy(*args):
        raise OSError("injected destroy failure")

    monkeypatch.setattr(bench, "_evict_from_warm", fail_destroy)
    args = SimpleNamespace(seed=5002, cases=["tool"], model_delays=[0], iterations=1, concurrency=1, users=1, run_id="bad-reset")
    path = tmp_path / "rows.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        assert not await bench.run_matrix(provider, config, args, stream)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["record_type"] == "prewarm_case" and rows[0]["success"]
    assert rows[1]["record_type"] == "batch_cleanup" and not rows[1]["success"]
    assert rows[1]["errors"] == [{"sandbox_id": rows[0]["sandbox_ids"][0], "error_type": "OSError"}]


def test_non_aio_config_rejected_before_provisioning(monkeypatch, tmp_path):
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    monkeypatch.setattr(bench, "get_app_config", lambda: config)
    monkeypatch.setattr(bench, "_make_aio_provider", lambda config: pytest.fail("must not provision for a mismatched treatment"))
    with pytest.raises(SystemExit) as exc:
        bench.main(["--output", str(tmp_path / "rows.jsonl")])
    assert exc.value.code == 2


def test_shutdown_failure_still_stops_sampler_and_propagates(monkeypatch, tmp_path):
    events = []
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider"))
    monkeypatch.setattr(bench, "get_app_config", lambda: config)
    monkeypatch.setattr(bench, "_make_aio_provider", lambda config: (object(), {"image": "offline"}))
    monkeypatch.setattr(bench, "set_sandbox_provider", lambda provider: None)
    monkeypatch.setattr(bench.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="revision" if kwargs.get("text") else b""))

    class Sampler:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            events.append("start")

        def wait_for_first_sample(self, **kwargs):
            return True

        def stop(self):
            events.append("stop")

    async def run(*args):
        return True

    def failed_shutdown():
        events.append("shutdown")
        raise OSError("injected shutdown failure")

    monkeypatch.setattr(bench, "DockerResourceSampler", Sampler)
    monkeypatch.setattr(bench, "run_matrix", run)
    monkeypatch.setattr(bench, "shutdown_sandbox_provider", failed_shutdown)
    with pytest.raises(OSError, match="injected shutdown failure"):
        bench.main(["--output", str(tmp_path / "results.jsonl")])
    assert events == ["start", "shutdown", "stop"]
