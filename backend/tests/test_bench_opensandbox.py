"""Exercise the benchmark through the real provider with an offline SDK transport."""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from deerflow.community.opensandbox import provider as provider_module
from deerflow.config.app_config import AppConfig, get_app_config, pop_current_app_config, push_current_app_config
from deerflow.config.sandbox_config import SandboxConfig
from scripts.benchmark.sandbox import bench_provider as bench
from scripts.benchmark.sandbox import summarize


class Remote:
    def __init__(self, number):
        self.id = f"offline-remote-{number}"
        self.destroy_calls = 0
        self.destroy_error = False
        self.command_error = False
        self.commands = SimpleNamespace(run=self.run)
        self.state = ""

    def run(self, command, **kwargs):
        if self.command_error:
            raise RuntimeError("offline command failure")
        if "__DF_OUTPUT_SYNC__" in command:
            output = "\n__DF_OUTPUT_SYNC__:0:0:0"
        elif 'write_text("benchmark-state-42")' in command:
            self.state = "benchmark-state-42"
            output = "written"
        elif 'Path("/tmp/warm_state.txt").read_text()' in command:
            output = self.state
        else:
            output = ""
        return SimpleNamespace(exit_code=0, logs=SimpleNamespace(stdout=[SimpleNamespace(text=output)], stderr=[]), result=[])

    def renew(self, timeout):
        pass

    def destroy(self):
        self.destroy_calls += 1
        if self.destroy_error:
            raise RuntimeError("sentinel-private-sdk-error")


@pytest.fixture
def transport(monkeypatch, tmp_path):
    remotes = []
    requests = []
    lock = threading.Lock()

    def create(image, **kwargs):
        with lock:
            remote = Remote(len(remotes) + 1)
            remotes.append(remote)
            requests.append({"image": image, **kwargs})
        return remote

    monkeypatch.setattr(provider_module, "_import_sdk", lambda: (SimpleNamespace(create=create), SimpleNamespace, SimpleNamespace))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    config = AppConfig(
        sandbox=SandboxConfig(
            use="deerflow.community.opensandbox:OpenSandboxProvider",
            image="test-image@sha256:fixture",
            api_key="sentinel-api-key",
            domain="sandbox.invalid:443",
            protocol="https",
            request_timeout=17,
            ready_timeout=19,
            use_server_proxy=True,
            environment={"BENCH_SECRET": "sentinel-environment"},
        )
    )
    push_current_app_config(config)
    try:
        yield SimpleNamespace(remotes=remotes, requests=requests, config=config)
    finally:
        pop_current_app_config()


def test_factory_preserves_connection_config_without_exporting_secrets(transport):
    provider, snapshot = bench._make_opensandbox_provider({"replicas": 2, "idle_timeout": 0, "image": None})
    try:
        assert get_app_config() is transport.config
        assert transport.config.sandbox.image == "test-image@sha256:fixture"
        sid = provider.acquire("thread", user_id="owner")
        request = transport.requests[0]
        assert request["image"] == "test-image@sha256:fixture"
        assert request["env"] == {"BENCH_SECRET": "sentinel-environment"}
        assert vars(request["connection_config"]) == {
            "api_key": "sentinel-api-key",
            "domain": "sandbox.invalid:443",
            "protocol": "https",
            "request_timeout": timedelta(seconds=17),
            "use_server_proxy": True,
        }
        assert request["ready_timeout"].total_seconds() == 19
        assert snapshot == {"image": request["image"], "replicas": 2, "idle_timeout": 0}
        assert "sentinel" not in json.dumps(snapshot)
        provider.release(sid)
    finally:
        provider.shutdown()


@pytest.mark.parametrize("cold", [False, True])
def test_cli_measures_real_reclaim_and_destroys_all_created_remotes(transport, tmp_path, cold):
    output = tmp_path / "results.jsonl"
    args = ["--provider", "opensandbox", "--iterations", "2", "--idle-timeout", "0", "--output", str(output)]
    if cold:
        args.append("--no-warmpool")
    assert bench.main(args) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["warm_hit"] for row in rows] == [False, not cold]
    assert all(row["success"] and row["provider"] == "opensandbox" for row in rows)
    assert all(row["health_check_skip_seconds"] is None for row in rows)
    # One separate warm-up remote, then two cold remotes or one reused remote.
    assert len(transport.remotes) == (3 if cold else 2)
    assert all(remote.destroy_calls == 1 for remote in transport.remotes)
    assert "sentinel" not in output.read_text(encoding="utf-8")


def test_state_reuse_preserves_remote_files(transport, tmp_path):
    output = tmp_path / "state.jsonl"
    assert bench.main(["--provider", "opensandbox", "--workload", "state_reuse", "--iterations", "2", "--idle-timeout", "0", "--output", str(output)]) == 0
    assert transport.remotes[-1].state == "benchmark-state-42"


def test_replica_pressure_keeps_concurrent_scopes_separate(transport, tmp_path):
    output = tmp_path / "pressure.jsonl"
    assert (
        bench.main(
            [
                "--provider",
                "opensandbox",
                "--scenario",
                "replica_pressure",
                "--iterations",
                "4",
                "--concurrency",
                "2",
                "--users",
                "2",
                "--replicas",
                "1",
                "--idle-timeout",
                "0",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert all(row["active_at_acquire"] == 2 and row["success"] for row in rows)
    assert len({row["sandbox_id"] for row in rows}) == 2
    assert all(remote.destroy_calls == 1 for remote in transport.remotes)


def test_failed_command_still_releases_and_destroys_remote(transport):
    provider, _ = bench._make_opensandbox_provider({"idle_timeout": 0})
    sid = provider.acquire("thread", user_id="owner")
    transport.remotes[0].command_error = True
    try:
        row = bench._run_one_turn(provider, "opensandbox", "warm_same_thread", "noop", "true", 0, 1, "owner", "thread", True)
        assert not row.success
        assert row.sandbox_id == sid
        assert transport.remotes[0].destroy_calls == 1
        assert not provider._warm_pool and not provider._sandboxes
    finally:
        provider.shutdown()


def test_failed_destroy_invalidates_measurement_and_fails_shutdown(transport):
    provider, _ = bench._make_opensandbox_provider({"idle_timeout": 0})
    provider.acquire("thread", user_id="owner")
    transport.remotes[0].destroy_error = True
    try:
        row = bench._run_one_turn(provider, "opensandbox", "warm_same_thread", "noop", "true", 0, 1, "owner", "thread", True)
        assert not row.success
        assert "offline-remote-1" in row.error
        assert "sentinel-private-sdk-error" not in row.error
    finally:
        with pytest.raises(RuntimeError, match="cleanup"):
            provider.shutdown()
    # atexit must not repeat the error or pretend that a closed SDK client retried it.
    provider.shutdown()
    assert transport.remotes[0].destroy_calls == 1


def test_shutdown_attempts_every_remote_before_reporting_failure(transport):
    provider, _ = bench._make_opensandbox_provider({"idle_timeout": 0})
    provider.acquire("first", user_id="owner")
    provider.acquire("second", user_id="owner")
    transport.remotes[0].destroy_error = True
    with pytest.raises(RuntimeError, match="cleanup"):
        provider.shutdown()
    assert [remote.destroy_calls for remote in transport.remotes] == [1, 1]


def test_shutdown_failure_is_also_visible_in_jsonl(transport, monkeypatch, tmp_path):
    original_factory = bench.PROVIDER_FACTORIES["opensandbox"]

    def factory(config):
        provider, snapshot = original_factory(config)
        original_create = provider._create_sandbox

        def create(*args, **kwargs):
            sandbox = original_create(*args, **kwargs)
            transport.remotes[-1].destroy_error = True
            return sandbox

        provider._create_sandbox = create
        return provider, snapshot

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "opensandbox", factory)
    output = tmp_path / "cleanup.jsonl"
    with pytest.raises(RuntimeError, match="cleanup"):
        bench.main(["--provider", "opensandbox", "--iterations", "1", "--warmup-iterations", "0", "--idle-timeout", "0", "--output", str(output)])
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["success"]
    assert rows[-1]["scenario"] == "shutdown"
    assert rows[-1]["success"] is False
    assert "sentinel-private-sdk-error" not in output.read_text(encoding="utf-8")
    assert summarize.main([str(output), "--json"]) == 1


def test_image_override_and_failed_construction_restore_config(transport):
    provider, snapshot = bench._make_opensandbox_provider({"image": "override-image", "idle_timeout": 0})
    try:
        assert snapshot["image"] == "override-image"
        assert get_app_config() is transport.config
        assert transport.config.sandbox.image == "test-image@sha256:fixture"
    finally:
        provider.shutdown()
    bad = transport.config.model_copy(update={"sandbox": transport.config.sandbox.model_copy(update={"request_timeout": -1})})
    push_current_app_config(bad)
    try:
        with pytest.raises(ValueError, match="request_timeout"):
            bench._make_opensandbox_provider({})
        assert get_app_config() is bad
    finally:
        pop_current_app_config()


def test_idle_reaping_forces_a_new_remote(transport, monkeypatch, tmp_path):
    clock = [100.0]
    # Warm-pool idle age is written and read on the monotonic clock, so freeze
    # that one and let the benchmark's sleep advance it. Freezing `time.time`
    # instead leaves both ends of the comparison on the real clock: the entry
    # never expires, the reaper removes nothing, and the next turn is a warm hit.
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bench.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    output = tmp_path / "idle.jsonl"
    assert (
        bench.main(
            [
                "--provider",
                "opensandbox",
                "--scenario",
                "idle_timeout",
                "--iterations",
                "1",
                "--warmup-iterations",
                "0",
                "--idle-timeout",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["warm_hit"] for row in rows] == [False, False]
    assert all(row["success"] for row in rows)
    assert len(transport.remotes) == 2
    assert all(remote.destroy_calls == 1 for remote in transport.remotes)


@pytest.mark.parametrize("extra", [["--fault-inject", "0"], ["--health-check-skip-seconds", "1"]])
def test_unsupported_options_fail_before_creating_resources(transport, extra):
    with pytest.raises(SystemExit, match="opensandbox"):
        bench.main(["--provider", "opensandbox", *extra])
    assert not transport.remotes


@pytest.mark.parametrize("provider", ["opensandbox", "boxlite", "aio-docker"])
@pytest.mark.parametrize("value", ["-5", "nan", "NaN", "-inf"])
def test_invalid_idle_timeout_fails_before_provider_creation(monkeypatch, provider, value):
    assert provider in bench.PROVIDER_FACTORIES

    def unexpected_provider(*args, **kwargs):
        pytest.fail("invalid idle timeout must be rejected before provisioning")

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, provider, unexpected_provider)
    with pytest.raises(SystemExit, match="idle timeout must be nonnegative"):
        bench.main(["--provider", provider, "--scenario", "warm_same_thread", f"--idle-timeout={value}"])


@pytest.mark.parametrize("provider", ["boxlite", "aio-docker"])
@pytest.mark.parametrize("value", ["-5", "nan", "NaN", "-inf"])
def test_invalid_health_check_skip_fails_before_provider_creation(monkeypatch, provider, value):
    assert provider in bench.PROVIDER_FACTORIES

    def unexpected_provider(*args, **kwargs):
        pytest.fail("invalid health-check skip must be rejected before provisioning")

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, provider, unexpected_provider)
    with pytest.raises(SystemExit, match="health-check skip seconds must be nonnegative"):
        bench.main(["--provider", provider, f"--health-check-skip-seconds={value}"])


@pytest.mark.parametrize("provider", ["opensandbox", "boxlite", "aio-docker"])
def test_idle_timeout_scenario_rejects_infinite_timeout_before_provider_creation(monkeypatch, provider):
    def unexpected_provider(*args, **kwargs):
        pytest.fail("an infinite idle_timeout scenario must be rejected before provisioning")

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, provider, unexpected_provider)

    with pytest.raises(SystemExit, match="finite positive idle timeout"):
        bench.main(["--provider", provider, "--scenario", "idle_timeout", "--idle-timeout=inf"])


@pytest.mark.parametrize("provider", ["boxlite", "aio-docker"])
@pytest.mark.parametrize("option", ["--idle-timeout", "--health-check-skip-seconds"])
@pytest.mark.parametrize("value", [None, "0", "2.5", "inf"])
def test_nonnegative_timing_values_reach_provider_factory(monkeypatch, tmp_path, provider, option, value):
    captured = []

    class FakeSandbox:
        def execute_command(self, command, timeout=None):
            return "ok"

    class FakeProvider:
        def __init__(self):
            self._lock = threading.Lock()
            self._warm_pool = {}

        def acquire(self, thread_id, *, user_id=None):
            return "sandbox-id"

        def get(self, sandbox_id):
            return FakeSandbox()

        def release(self, sandbox_id):
            return None

        def shutdown(self):
            return None

    def factory(config):
        captured.append(config)
        return FakeProvider(), {
            "image": config["image"],
            "replicas": config["replicas"],
            "idle_timeout": config["idle_timeout"],
            "health_check_skip_seconds": config["health_check_skip_seconds"],
        }

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, provider, factory)
    output = tmp_path / f"{provider}-{option[2:]}-{value or 'default'}.jsonl"
    args = ["--provider", provider, "--iterations", "1", "--warmup-iterations", "0", "--output", str(output)]
    if value is not None:
        args.append(f"{option}={value}")

    assert bench.main(args) == 0
    key = option[2:].replace("-", "_")
    expected = float(value) if value is not None else {"idle_timeout": 600.0, "health_check_skip_seconds": 0.0}[key]
    assert captured[0][key] == expected
    assert json.loads(output.read_text(encoding="utf-8"))[key] == expected


@pytest.mark.parametrize("value", [0.0, 7.5, float("inf")])
def test_aio_factory_forwards_health_check_skip_to_config_and_snapshot(monkeypatch, value):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as aio_module

    captured = {}

    class FakeAioProvider:
        def __init__(self):
            captured.update(vars(aio_module.get_app_config().sandbox))
            self._config = {"image": "resolved-aio-image"}

    monkeypatch.setattr(aio_module, "AioSandboxProvider", FakeAioProvider)

    provider, snapshot = bench._make_aio_provider({"health_check_skip_seconds": value})

    assert isinstance(provider, FakeAioProvider)
    assert captured["health_check_skip_seconds"] == value
    assert snapshot["health_check_skip_seconds"] == value
    assert snapshot["image"] == "resolved-aio-image"
