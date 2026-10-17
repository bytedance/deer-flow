from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/sandbox/resources.py"
    spec = importlib.util.spec_from_file_location("bench_sandbox_resources", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resources = _load_module()
PREFIX = "deerflow-bench-abc123-"
OWN_ID = "a" * 64
OTHER_ID = "b" * 64


def _jsonl(*rows):
    return "\n".join(json.dumps(row) for row in rows)


@pytest.mark.parametrize("text,expected", [("0B", 0), ("1.5kB", 1500), ("2 MB", 2_000_000), ("2MiB", 2 * 1024**2), ("1.25GiB", int(1.25 * 1024**3)), ("1TiB", 1024**4)])
def test_docker_memory_units(text, expected):
    assert resources.parse_bytes(text) == expected


@pytest.mark.parametrize("text", ["", "N/A", "nanMiB", "-1MiB", "1.0unknown", "infB"])
def test_missing_or_invalid_memory_is_unknown(text):
    assert resources.parse_bytes(text) is None


@pytest.mark.parametrize("prefix", ["", "-", "deerflow", "bad prefix-", "*all*"])
def test_sampler_requires_explicit_bounded_prefix(prefix, tmp_path):
    with pytest.raises(ValueError, match="prefix"):
        resources.DockerResourceSampler(prefix, tmp_path / "resources.jsonl")


def test_inventory_filters_exact_prefix_and_stats_targets_only_owned_ids(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "ps":
            return SimpleNamespace(stdout=_jsonl({"ID": OWN_ID, "Names": PREFIX + "one"}, {"ID": OTHER_ID, "Names": "production"}, {"ID": "c" * 64, "Names": "other-" + PREFIX + "two"}))
        return SimpleNamespace(stdout=_jsonl({"ID": OWN_ID[:12], "Name": PREFIX + "one", "MemUsage": "1.5MiB / 8GiB", "CPUPerc": "123.45%"}))

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    result = resources.collect_docker_sample(PREFIX, command_timeout=2)
    assert [command[1] for command, _ in calls] == ["ps", "stats"]
    assert calls[1][0][-2:] == ["--", OWN_ID]
    assert OTHER_ID not in calls[1][0]
    assert all(kwargs == {"check": True, "capture_output": True, "encoding": "utf-8", "errors": "replace", "timeout": 2} for _, kwargs in calls)
    assert result["matched_containers"] == 1
    assert result["total_memory_bytes"] == 1_572_864
    assert result["total_cpu_percent"] == 123.45
    assert result["containers"][0]["memory_limit_bytes"] == 8 * 1024**3
    assert result["errors"] == []
    assert result["timestamp_utc"].endswith("+00:00")
    assert result["monotonic_s"] > 0


def test_known_empty_inventory_records_zero_without_unscoped_stats(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    sample = resources.collect_docker_sample(PREFIX)
    assert len(calls) == 1
    assert sample["matched_containers"] == 0
    assert sample["total_memory_bytes"] == 0
    assert sample["total_cpu_percent"] == 0
    assert sample["errors"] == []


@pytest.mark.parametrize(
    "failure,code", [(subprocess.CalledProcessError(1, "docker", stderr="secret credential"), "docker_ps_failed"), (subprocess.TimeoutExpired("docker", 1), "docker_ps_timeout"), (FileNotFoundError("private path"), "docker_ps_unavailable")]
)
def test_inventory_failure_is_unknown_and_does_not_leak_command_output(monkeypatch, failure, code):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(resources.subprocess, "run", fail)
    sample = resources.collect_docker_sample(PREFIX)
    assert sample["matched_containers"] is None
    assert sample["total_memory_bytes"] is None
    assert sample["total_cpu_percent"] is None
    assert sample["errors"] == [code]
    assert "secret" not in json.dumps(sample)
    assert "private path" not in json.dumps(sample)


@pytest.mark.parametrize("stats", ["", "{broken json", _jsonl({"ID": OTHER_ID, "Name": "production", "MemUsage": "2MiB / 8GiB", "CPUPerc": "50%"}), _jsonl({"ID": OWN_ID[:12], "MemUsage": "N/A", "CPUPerc": "--"})])
def test_missing_stats_never_become_zero_or_count_other_containers(monkeypatch, stats):
    def fake_run(command, **kwargs):
        return SimpleNamespace(stdout=_jsonl({"ID": OWN_ID, "Names": PREFIX + "one"}) if command[1] == "ps" else stats)

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    sample = resources.collect_docker_sample(PREFIX)
    assert sample["matched_containers"] == 1
    assert sample["total_memory_bytes"] is None
    assert sample["total_cpu_percent"] is None
    assert sample["errors"]
    assert all(container["container_id"] == OWN_ID for container in sample["containers"])


def test_sampler_drains_inflight_sample_and_records_sampled_peak(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    stop_entered = threading.Event()
    stopped = threading.Event()
    sample_calls = []

    def collect(prefix, *, command_timeout):
        sample_calls.append(prefix)
        entered.set()
        assert release.wait(5)
        return {"record_type": "resource_sample", "containers": [], "matched_containers": 2, "total_memory_bytes": 2048, "total_cpu_percent": 50.0, "errors": []}

    monkeypatch.setattr(resources, "collect_docker_sample", collect)
    output = tmp_path / "resources.jsonl"
    sampler = resources.DockerResourceSampler(PREFIX, output, interval=60)
    sampler.start()
    assert entered.wait(5)

    def stop():
        stop_entered.set()
        sampler.stop()
        stopped.set()

    stopper = threading.Thread(target=stop)
    stopper.start()
    try:
        assert stop_entered.wait(5)
        assert not stopped.is_set()
    finally:
        release.set()
        stopper.join(5)
        sampler.stop()
    assert stopped.is_set()
    assert sample_calls == [PREFIX]
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["record_type"] == "resource_sample"
    summary = rows[1]
    assert summary["record_type"] == "resource_summary"
    assert summary["sample_count"] == 1
    assert summary["peak_sampled_total_memory_bytes"] == 2048
    assert summary["peak_sampled_total_cpu_percent"] == 50
    assert summary["max_sampled_containers"] == 2
    assert not sampler.running


def test_summary_preserves_unknown_measurements_and_output_is_exclusive(monkeypatch, tmp_path):
    monkeypatch.setattr(resources, "collect_docker_sample", lambda *args, **kwargs: {"record_type": "resource_sample", "matched_containers": None, "total_memory_bytes": None, "total_cpu_percent": None, "errors": ["docker_ps_failed"]})
    output = tmp_path / "resources.jsonl"
    with resources.DockerResourceSampler(PREFIX, output, interval=60) as sampler:
        sampler.wait_for_first_sample(timeout=5)
    summary = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert summary["peak_sampled_total_memory_bytes"] is None
    assert summary["peak_sampled_total_cpu_percent"] is None
    assert summary["max_sampled_containers"] is None
    assert summary["incomplete_samples"] == 1
    with pytest.raises(FileExistsError):
        resources.DockerResourceSampler(PREFIX, output).start()


def test_invalid_inventory_does_not_dispatch_stats(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=_jsonl({"ID": "--all", "Names": PREFIX + "one"}))

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    sample = resources.collect_docker_sample(PREFIX)
    assert len(calls) == 1
    assert sample["matched_containers"] is None
    assert sample["errors"] == ["invalid_inventory"]


def test_stats_timeout_retains_inventory_but_not_fabricated_resource_values(monkeypatch):
    def fake_run(command, **kwargs):
        if command[1] == "ps":
            return SimpleNamespace(stdout=_jsonl({"ID": OWN_ID, "Names": PREFIX + "one"}))
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    sample = resources.collect_docker_sample(PREFIX)
    assert sample["matched_containers"] == 1
    assert sample["total_memory_bytes"] is None
    assert sample["total_cpu_percent"] is None
    assert "docker_stats_timeout" in sample["errors"]


@pytest.mark.parametrize("duration", ["0", "-1", "inf", "nan"])
def test_cli_requires_bounded_positive_duration(duration, tmp_path):
    output = tmp_path / "out.jsonl"
    with pytest.raises(SystemExit) as exc_info:
        resources.main(["--prefix", PREFIX, "--output", str(output), "--duration", duration])
    assert exc_info.value.code == 2
    assert not output.exists()


def test_cli_interrupt_exits_sampler_context_before_returning(monkeypatch, tmp_path):
    calls = []

    class Sampler:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            calls.append("start")
            return self

        def __exit__(self, *args):
            calls.append("stop")

    class Interrupt:
        def wait(self, duration):
            raise KeyboardInterrupt

    monkeypatch.setattr(resources, "DockerResourceSampler", Sampler)
    monkeypatch.setattr(resources.threading, "Event", Interrupt)
    assert resources.main(["--prefix", PREFIX, "--output", str(tmp_path / "out.jsonl"), "--duration", "60"]) == 130
    assert calls == ["start", "stop"]
