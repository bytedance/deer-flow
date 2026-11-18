from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module(name: str, relative: str):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module("bench_provider", "scripts/benchmark/sandbox/bench_provider.py")
summarize = _load_module("summarize", "scripts/benchmark/sandbox/summarize.py")


class _FakeProvider:
    def __init__(self, sandbox: Any | None = None) -> None:
        self._lock = bench.threading.Lock()
        self._warm_pool: dict[str, tuple[Any, float]] = {}
        self._sandbox = sandbox or _FakeSandbox("ok")
        self.released: list[str] = []
        self.shutdown_called = False

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return "sandbox-id"

    def get(self, sandbox_id: str):
        return self._sandbox

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FakeWarmReclaimProvider(_FakeProvider):
    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        reclaimed = self._reclaim_warm_pool("sandbox-id")
        assert reclaimed is not None
        return reclaimed

    def _reclaim_warm_pool(self, sandbox_id: str) -> str | None:
        return sandbox_id


class _FakeSandbox:
    def __init__(self, output: str | Exception) -> None:
        self.output = output

    def execute_command(self, command: str, timeout: float | None = None) -> str:
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def test_aio_provider_default_leaves_image_unset(monkeypatch, tmp_path):
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        captured_config.update(config)
        return _FakeProvider(), {"replicas": config["replicas"], "idle_timeout": config["idle_timeout"], "image": config.get("image")}

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", _factory)

    rc = bench.main(
        [
            "--provider",
            "aio-docker",
            "--iterations",
            "0",
            "--warmup-iterations",
            "0",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert rc == 0
    assert captured_config["image"] is None


def test_explicit_aio_provider_image_is_forwarded(monkeypatch, tmp_path):
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        captured_config.update(config)
        return _FakeProvider(), {"replicas": config["replicas"], "idle_timeout": config["idle_timeout"], "image": config.get("image")}

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", _factory)

    rc = bench.main(
        [
            "--provider",
            "aio-docker",
            "--image",
            "custom/aio:latest",
            "--iterations",
            "0",
            "--warmup-iterations",
            "0",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert rc == 0
    assert captured_config["image"] == "custom/aio:latest"


def test_failed_turn_releases_acquired_sandbox() -> None:
    provider = _FakeProvider(_FakeSandbox(RuntimeError("boom")))

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is False
    assert provider.released == ["sandbox-id"]


def test_error_string_output_records_failed_turn() -> None:
    provider = _FakeProvider(_FakeSandbox("Error: vsock disconnected"))

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is False
    assert result.error == "Error: vsock disconnected"
    assert provider.released == ["sandbox-id"]


def test_warm_hit_uses_reclaim_instrumentation_not_pre_acquire_sample() -> None:
    provider = _FakeWarmReclaimProvider(_FakeSandbox("ok"))
    bench._install_warm_hit_tracking(provider)

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is True
    assert result.warm_hit is True


def test_summary_preserves_all_failure_group() -> None:
    rows = [
        {
            "provider": "boxlite",
            "scenario": "warm_same_thread",
            "workload": "noop",
            "concurrency": 1,
            "success": False,
            "error": "RuntimeError('boom')",
            "acquire_ms": 0,
            "total_ms": 12.3,
        }
    ]

    summary = summarize._summarize(rows, ["provider", "scenario", "workload", "concurrency"])

    assert summary == [
        {
            "provider": "boxlite",
            "scenario": "warm_same_thread",
            "workload": "noop",
            "concurrency": 1,
            "count": 1,
            "ok": 0,
            "errors": 1,
            "warm_hit_rate": 0,
            "acquire_p50": 0.0,
            "acquire_p95": 0.0,
            "acquire_p99": 0.0,
            "acquire_mean": 0.0,
            "run_p50": 0.0,
            "run_p95": 0.0,
            "release_p50": 0.0,
            "total_p50": 0.0,
            "total_p95": 0.0,
            "total_p99": 0.0,
            "total_mean": 0.0,
        }
    ]


def test_health_check_skip_seconds_is_forwarded_and_serialized(monkeypatch, tmp_path):
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        captured_config.update(config)
        return _FakeProvider(), {
            "replicas": config["replicas"],
            "idle_timeout": config["idle_timeout"],
            "image": config.get("image"),
            "health_check_skip_seconds": config.get("health_check_skip_seconds"),
        }

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "boxlite", _factory)
    output_path = tmp_path / "out.jsonl"

    rc = bench.main(
        [
            "--provider",
            "boxlite",
            "--iterations",
            "1",
            "--warmup-iterations",
            "0",
            "--health-check-skip-seconds",
            "7.5",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert captured_config["health_check_skip_seconds"] == 7.5
    row = __import__("json").loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["health_check_skip_seconds"] == 7.5


def test_boxlite_factory_restores_module_state(monkeypatch):
    import deerflow.community.boxlite.provider as provider_mod

    original_get_app_config = provider_mod.get_app_config

    class _FactoryProvider:
        _create_box = object()

        def __init__(self) -> None:
            self.created = True

    original_create_box = _FactoryProvider._create_box
    monkeypatch.setattr(provider_mod, "BoxliteProvider", _FactoryProvider)

    provider, _ = bench._make_boxlite_provider({})

    assert isinstance(provider, _FactoryProvider)
    assert provider_mod.get_app_config is original_get_app_config
    assert _FactoryProvider._create_box is original_create_box


@pytest.mark.skipif(
    os.name == "nt",
    reason="asserts POSIX exec-bit semantics (os.chmod cannot toggle execute bits on Windows); boxlite sandboxes are Linux-only",
)
def test_boxlite_shim_workaround_retries_after_fixing_permissions(monkeypatch, tmp_path):
    boxes_dir = tmp_path / "boxes"
    shim = boxes_dir / "deadbeef" / "bin" / "boxlite-shim"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o644)

    calls = 0

    def _create_box(_sandbox_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("shim not executable")
        return "ok"

    monkeypatch.setattr(bench, "_boxlite_version", lambda: "0.9.7")

    result = bench._create_box_with_097_shim_workaround(
        _create_box,
        "sandbox-id",
        boxes_dir=str(boxes_dir),
    )

    assert result == "ok"
    assert calls == 2
    assert shim.stat().st_mode & 0o111


def test_boxlite_shim_workaround_loud_fails_for_other_versions(monkeypatch, tmp_path):
    boxes_dir = tmp_path / "boxes"
    monkeypatch.setattr(bench, "_boxlite_version", lambda: "0.9.8")

    def _create_box(_sandbox_id: str):
        raise RuntimeError("shim not executable")

    with __import__("pytest").raises(RuntimeError, match="only supports boxlite 0.9.7"):
        bench._create_box_with_097_shim_workaround(
            _create_box,
            "sandbox-id",
            boxes_dir=str(boxes_dir),
        )


class _FakeAioProvider(_FakeProvider):
    """AIO warm entries are metadata, not the closable execution client."""

    def __init__(self):
        super().__init__()
        self._sandboxes = {}
        self.destroyed = []
        self.crashed = []
        self.alive = set()
        self._backend = bench.types.SimpleNamespace(destroy=self._crash, is_alive=lambda info: info.sandbox_id in self.alive)

    def _crash(self, info):
        self.crashed.append(info.sandbox_id)
        self.alive.discard(info.sandbox_id)

    def acquire(self, thread_id=None, *, user_id=None):
        sid = f"actual-24-char-id:{user_id}:{thread_id}"
        with self._lock:
            self._warm_pool.pop(sid, None)
            self._sandboxes[sid] = self._sandbox
            self.alive.add(sid)
        return sid

    def release(self, sid):
        with self._lock:
            self._sandboxes.pop(sid)
            self._warm_pool[sid] = (bench.types.SimpleNamespace(sandbox_id=sid), 0)

    def destroy(self, sid):
        with self._lock:
            self.destroyed.append(sid)
            self._warm_pool.pop(sid, None)
            self.alive.discard(sid)
        return True

    def _active_count_locked(self):
        return len(self._sandboxes)


def test_aio_no_warmpool_destroys_container_not_metadata():
    provider = _FakeAioProvider()
    result = bench._run_one_turn(provider, "aio-docker", "cold_unique_thread", "noop", "true", 0, 1, "user", "thread", True)

    assert result.success
    assert provider.destroyed == ["actual-24-char-id:user:thread"]
    assert provider.alive == set()
    assert provider._warm_pool == {}


def test_deferred_destroy_is_failed_measurement():
    provider = _FakeAioProvider()
    provider.destroy = lambda sid: False
    result = bench._run_one_turn(provider, "aio-docker", "cold_unique_thread", "noop", "true", 0, 1, "user", "thread", True)
    assert not result.success
    assert "destroy" in result.error.lower()
    assert provider.alive
    assert provider._warm_pool  # retain metadata so final shutdown can still clean it


@pytest.mark.parametrize("command_raises", [False, True])
@pytest.mark.parametrize("destroy_raises", [False, True])
def test_failed_turn_separates_execution_release_and_cleanup_times(monkeypatch, command_raises, destroy_raises):
    clock = [0.0]
    monkeypatch.setattr(bench.time, "perf_counter", lambda: clock[0])
    provider = _FakeAioProvider()
    original_acquire = provider.acquire
    original_release = provider.release
    original_destroy = provider.destroy

    def acquire(*args, **kwargs):
        clock[0] += 0.010
        return original_acquire(*args, **kwargs)

    def execute(command, timeout=None):
        clock[0] += 0.020
        if command_raises:
            raise RuntimeError("command failed")
        return "Error: command failed"

    def release(sid):
        clock[0] += 0.030
        return original_release(sid)

    def destroy(sid):
        clock[0] += 0.040
        if destroy_raises:
            raise RuntimeError("destroy failed")
        return original_destroy(sid)

    monkeypatch.setattr(provider, "acquire", acquire)
    monkeypatch.setattr(provider._sandbox, "execute_command", execute)
    monkeypatch.setattr(provider, "release", release)
    monkeypatch.setattr(provider, "destroy", destroy)

    result = bench._run_one_turn(provider, "aio-docker", "cold_unique_thread", "noop", "true", 0, 1, "user", "thread", True)

    assert not result.success
    assert "command failed" in result.error
    assert ("destroy failed" in result.error) is destroy_raises
    assert result.acquire_ms == pytest.approx(10)
    assert result.run_ms == pytest.approx(20)
    assert result.release_ms == pytest.approx(30)
    assert result.cleanup_ms == pytest.approx(40)
    assert result.total_ms == pytest.approx(100)


def test_failed_acquire_records_elapsed_time_without_fabricating_later_stages(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(bench.time, "perf_counter", lambda: clock[0])
    provider = _FakeAioProvider()

    def acquire(*args, **kwargs):
        clock[0] += 0.125
        raise RuntimeError("acquire failed")

    monkeypatch.setattr(provider, "acquire", acquire)
    result = bench._run_one_turn(provider, "aio-docker", "cold_unique_thread", "noop", "true", 0, 1, "user", "thread", True)
    assert not result.success
    assert result.acquire_ms == pytest.approx(125)
    assert result.total_ms == pytest.approx(125)
    assert result.run_ms == result.release_ms == result.cleanup_ms == 0
    assert provider.destroyed == []


def test_fault_injection_uses_returned_aio_identity(tmp_path):
    provider = _FakeAioProvider()
    rows = bench._run_scenario(provider, "aio-docker", "warm_same_thread", "noop", 1, 1, tmp_path / "out.jsonl", False, {}, fault_inject_after=0)
    assert rows[0].success
    assert provider.crashed == [rows[0].sandbox_id]
    assert rows[0].sandbox_id in provider._warm_pool  # recovery must discover the dead entry
    assert not provider.alive


def test_replica_pressure_holds_concurrent_aio_clients_and_records_users(monkeypatch, tmp_path):
    provider = _FakeAioProvider()
    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", lambda config: (provider, config))
    output = tmp_path / "out.jsonl"
    rc = bench.main(["--provider", "aio-docker", "--scenario", "replica_pressure", "--iterations", "4", "--concurrency", "2", "--users", "2", "--replicas", "1", "--warmup-iterations", "0", "--output", str(output)])

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rc == 0
    assert len(rows) == 4
    assert len({r["user_id"] for r in rows}) == 2
    assert all(r["active_at_acquire"] == 2 for r in rows)
    assert all(r["concurrency"] == 2 for r in rows)
    assert provider.shutdown_called


def test_failed_workload_cli_exits_nonzero_and_keeps_rows(monkeypatch, tmp_path):
    provider = _FakeProvider(_FakeSandbox("Error: command failed"))
    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", lambda config: (provider, config))
    output = tmp_path / "out.jsonl"
    rc = bench.main(["--provider", "aio-docker", "--iterations", "1", "--warmup-iterations", "0", "--output", str(output)])
    assert rc == 1
    assert json.loads(output.read_text())["success"] is False
    assert provider.shutdown_called


def test_failed_warmup_stops_benchmark(monkeypatch, tmp_path):
    provider = _FakeProvider(_FakeSandbox("Error: not ready"))
    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", lambda config: (provider, config))
    rc = bench.main(["--provider", "aio-docker", "--iterations", "1", "--output", str(tmp_path / "out.jsonl")])
    assert rc == 1
    assert provider.shutdown_called


def test_default_summary_does_not_merge_cold_baseline_with_warm_pool(tmp_path, capsys):
    row = {"provider": "aio-docker", "scenario": "warm_same_thread", "workload": "noop", "concurrency": 1, "success": True, "acquire_ms": 1, "total_ms": 2}
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps({**row, "no_warmpool": disabled}) for disabled in (True, False)))
    assert summarize.main([str(path), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    assert {r["no_warmpool"] for r in rows} == {True, False}


def test_summary_failed_data_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps({"provider": "aio-docker", "success": False}))
    assert summarize.main([str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)[0]["errors"] == 1


@pytest.mark.parametrize("success", [True, False])
def test_summary_ignores_non_provider_records(tmp_path, capsys, success):
    records = [
        {"record_type": "configuration", "prewarm": True},
        {"record_type": "prewarm_case", "success": True},
        {"record_type": "batch_cleanup", "success": False},
        {"provider": "aio-docker", "success": success, "acquire_ms": 1, "total_ms": 2},
    ]
    path = tmp_path / "mixed.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")

    assert summarize.main([str(path), "--json"]) == int(not success)

    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert len(summary) == 1
    assert summary[0]["count"] == 1
    assert summary[0]["errors"] == int(not success)
    assert "non-provider" in output.err


@pytest.mark.parametrize(
    "records",
    [
        [{"record_type": "configuration"}],
        [{"record_type": "prewarm_case", "success": True}],
        [{"record_type": "configuration"}, {"record_type": "prewarm_case", "success": True}, {"record_type": "batch_cleanup", "success": True}],
    ],
    ids=["configuration-only", "prewarm-case-only", "prewarm-run"],
)
def test_summary_rejects_prewarm_only_input_without_traceback(tmp_path, capsys, records):
    path = tmp_path / "prewarm.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")

    assert summarize.main([str(path), "--json"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "bench_provider.py" in output.err


@pytest.mark.parametrize("missing", ["acquire_ms", "total_ms"])
def test_summary_reports_incomplete_provider_timings(tmp_path, capsys, missing):
    row = {"provider": "aio-docker", "success": True, "acquire_ms": 1, "total_ms": 2}
    row.pop(missing)
    path = tmp_path / "incomplete.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")

    assert summarize.main([str(path), "--json"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert missing in output.err


@pytest.mark.parametrize(
    "output",
    [
        "traceback\nExit Code: 1",
        "Command exited with code 1",
        "Command was terminated because its shell session ended.",
        "Command produced no output change for 30 seconds; it may still be running. Command outcome is unknown and was not retried.",
    ],
)
def test_provider_failure_text_cannot_be_a_successful_measurement(output):
    provider = _FakeProvider(_FakeSandbox(output))
    result = bench._run_one_turn(provider, "aio-docker", "warm_same_thread", "noop", "true", 0, 1, "user", "thread", False)
    assert not result.success
    assert provider.released == ["sandbox-id"]


def test_failed_pressure_acquire_releases_peers_without_barrier_timeout(tmp_path):
    provider = _FakeAioProvider()
    acquire = provider.acquire

    def failing_acquire(thread_id, *, user_id):
        if thread_id.endswith("pressure-1"):
            raise RuntimeError("injected create failure")
        return acquire(thread_id, user_id=user_id)

    provider.acquire = failing_acquire
    rows = bench._run_scenario(provider, "aio-docker", "replica_pressure", "noop", 2, 2, tmp_path / "out.jsonl", False, {"replicas": 1})
    assert all(not row.success for row in rows)
    assert not provider._sandboxes


def test_partial_pressure_batch_preserves_actual_active_count(tmp_path):
    rows = bench._run_scenario(_FakeAioProvider(), "aio-docker", "replica_pressure", "noop", 3, 2, tmp_path / "out.jsonl", False, {"replicas": 1})
    assert all(row.success for row in rows)
    assert [row.active_at_acquire for row in rows] == [2, 2, 1]


def test_new_invocation_cannot_reuse_previous_thread_identity(tmp_path):
    provider = _FakeAioProvider()
    args = (provider, "aio-docker", "cold_unique_thread", "noop", 1, 1, tmp_path / "out.jsonl", False, {})
    first = bench._run_scenario(*args)[0]
    second = bench._run_scenario(*args)[0]
    assert first.thread_id != second.thread_id
    assert first.sandbox_id != second.sandbox_id


def test_aio_factory_uses_current_config_contract_and_reports_effective_image(monkeypatch):
    import deerflow.community.aio_sandbox.aio_sandbox_provider as provider_module

    real_provider = provider_module.AioSandboxProvider
    original_get_config = provider_module.get_app_config

    class ConfigOnlyProvider:
        _positive_float = staticmethod(real_provider._positive_float)

        def __init__(self):
            self._config = real_provider._load_config(self)

    monkeypatch.setattr(provider_module, "AioSandboxProvider", ConfigOnlyProvider)
    provider, config = bench._make_aio_provider({"container_prefix": "deerflow-bench-test"})
    assert provider._config["network"]["mode"] == "open"
    assert config["image"] == provider._config["image"]
    assert config["image"]
    assert provider_module.get_app_config is original_get_config


def test_console_percentiles_match_json_summary_for_two_samples(capsys):
    results = [
        bench.BenchResult(
            provider="aio-docker",
            scenario="warm_same_thread",
            workload="noop",
            iteration=i,
            concurrency=1,
            thread_id="thread",
            user_id="user",
            acquire_ms=acquire_ms,
            run_ms=4,
            release_ms=1,
            total_ms=acquire_ms + 5,
        )
        for i, acquire_ms in enumerate((3435, 25))
    ]
    bench._print_summary(results, bench.types.SimpleNamespace(output="results.jsonl"))
    console = capsys.readouterr().err
    report = summarize._summarize([bench.asdict(result) for result in results], ["provider"])[0]

    assert report["acquire_p50"] == 1730.0
    for metric in ("acquire", "total"):
        percentiles = " ".join(f"p{pct}={report[f'{metric}_p{pct}']:.1f}ms" for pct in (50, 95, 99))
        assert percentiles in console
