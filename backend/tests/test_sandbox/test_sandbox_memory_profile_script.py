from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "sandbox_memory_profile.py"
    spec = importlib.util.spec_from_file_location("sandbox_memory_profile", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_memory_bytes_handles_kubernetes_units():
    mod = _load_module()

    assert mod.parse_memory_bytes("512Ki") == 512 * 1024
    assert mod.parse_memory_bytes("256Mi") == 256 * 1024 * 1024
    assert mod.parse_memory_bytes("1Gi") == 1024 * 1024 * 1024
    assert mod.parse_memory_bytes("0.1Gi") == 107374182
    assert mod.parse_memory_bytes("100M") == 100 * 1000 * 1000
    assert mod.parse_memory_bytes("bad") is None


def test_parse_top_pods_skips_header_and_preserves_raw_values():
    mod = _load_module()

    pods = mod.parse_top_pods(
        """NAME\tCPU(cores)\tMEMORY(bytes)
sandbox-abc 29m 792Mi
sandbox-def 1 501Mi
"""
    )

    assert [pod.name for pod in pods] == ["sandbox-abc", "sandbox-def"]
    assert pods[0].cpu_millicores == 29
    assert pods[0].memory_bytes == 792 * 1024 * 1024
    assert pods[1].cpu_millicores == 1000


def test_parse_processes_sorts_by_rss_and_limits_results():
    mod = _load_module()

    processes = mod.parse_processes(
        """PID\tPPID\tRSS\tCOMMAND
1 0 100 init
20 1 2048 python worker.py
21 1 bad ignored
30 1 512 node server.js
""",
        limit=2,
    )

    assert [(process.pid, process.rss_kib, process.command) for process in processes] == [
        (20, 2048, "python worker.py"),
        (30, 512, "node server.js"),
    ]


def test_parse_processes_rejects_invalid_limit():
    mod = _load_module()

    try:
        mod.parse_processes("1 0 100 init\n", limit=0)
    except ValueError as exc:
        assert "process limit" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_report_merges_top_and_pod_metadata():
    mod = _load_module()
    top_pods = mod.parse_top_pods("sandbox-abc 29m 792Mi\n")
    pod_json = {
        "items": [
            {
                "metadata": {
                    "name": "sandbox-abc",
                    "labels": {"sandbox-id": "abc"},
                },
                "status": {
                    "phase": "Running",
                    "startTime": "2026-05-26T00:00:00Z",
                },
                "spec": {
                    "containers": [
                        {
                            "name": "sandbox",
                            "image": "sandbox:latest",
                            "resources": {
                                "requests": {"memory": "256Mi"},
                                "limits": {"memory": "1Gi"},
                            },
                        }
                    ]
                },
            }
        ]
    }

    report = mod.build_report(
        namespace="deer-flow",
        selector="app=deer-flow-sandbox",
        sample="empty",
        top_pods=top_pods,
        pod_json=pod_json,
        process_samples={
            "sandbox-abc": [
                mod.ProcessSample(pid=20, ppid=1, rss_kib=2048, command="python worker.py"),
            ]
        },
    )

    assert report["summary"]["pod_count"] == 1
    assert report["summary"]["total_memory_mib"] == 792
    assert report["summary"]["pods_with_process_samples"] == 1
    assert report["pods"][0]["phase"] == "Running"
    assert report["pods"][0]["processes"][0]["rss_mib"] == 2
    assert report["pods"][0]["containers"]["sandbox"]["limits"]["memory"] == "1Gi"


def test_render_markdown_escapes_process_command_pipes():
    mod = _load_module()
    report = mod.build_report(
        namespace="deer-flow",
        selector="app=deer-flow-sandbox",
        sample="pipe-command",
        top_pods=mod.parse_top_pods("sandbox-abc 29m 792Mi\n"),
        pod_json={"items": []},
        process_samples={
            "sandbox-abc": [
                mod.ProcessSample(pid=20, ppid=1, rss_kib=2048, command="bash -c 'cat a | sort'"),
            ]
        },
    )

    markdown = mod.render_markdown(report)

    assert "cat a \\| sort" in markdown


def test_build_report_counts_unparsed_memory_values():
    mod = _load_module()
    report = mod.build_report(
        namespace="deer-flow",
        selector="app=deer-flow-sandbox",
        sample="partial",
        top_pods=mod.parse_top_pods("sandbox-abc 29m 792Mi\nsandbox-def bad unknown\n"),
        pod_json={"items": []},
    )

    assert report["summary"]["pod_count"] == 2
    assert report["summary"]["parsed_memory_count"] == 1
    assert report["summary"]["unparsed_memory_count"] == 1
    assert report["summary"]["parsed_cpu_count"] == 1
    assert report["summary"]["unparsed_cpu_count"] == 1


def test_build_report_includes_process_sample_errors():
    mod = _load_module()
    report = mod.build_report(
        namespace="deer-flow",
        selector="app=deer-flow-sandbox",
        sample="partial",
        top_pods=mod.parse_top_pods("sandbox-abc 29m 792Mi\n"),
        pod_json={"items": []},
        process_errors={"sandbox-abc": "exec denied"},
    )

    assert report["summary"]["pods_with_process_sample_errors"] == 1
    assert report["process_errors"] == {"sandbox-abc": "exec denied"}


def test_collect_process_samples_records_errors_and_continues(monkeypatch):
    mod = _load_module()
    pods = [
        mod.TopPod("sandbox-ok", "1m", "1Mi", 1, 1024 * 1024),
        mod.TopPod("sandbox-denied", "1m", "1Mi", 1, 1024 * 1024),
    ]

    def fake_run_kubectl(args, *, kubectl, timeout=mod.DEFAULT_KUBECTL_TIMEOUT):
        if "sandbox-denied" in args:
            raise subprocess.CalledProcessError(1, args, stderr="exec denied")
        return "PID PPID RSS COMMAND\n20 1 2048 python worker.py\n"

    monkeypatch.setattr(mod, "run_kubectl", fake_run_kubectl)

    result = mod.collect_process_samples(
        pods,
        namespace="deer-flow",
        kubectl="kubectl",
        limit=5,
    )

    assert result.samples["sandbox-ok"][0].pid == 20
    assert result.errors == {"sandbox-denied": "exec denied"}


def test_collect_process_samples_records_timeout_and_continues(monkeypatch):
    mod = _load_module()
    pods = [
        mod.TopPod("sandbox-timeout", "1m", "1Mi", 1, 1024 * 1024),
        mod.TopPod("sandbox-ok", "1m", "1Mi", 1, 1024 * 1024),
    ]

    def fake_run_kubectl(args, *, kubectl, timeout=mod.DEFAULT_KUBECTL_TIMEOUT):
        if "sandbox-timeout" in args:
            raise subprocess.TimeoutExpired(args, timeout)
        return "PID PPID RSS COMMAND\n20 1 2048 python worker.py\n"

    monkeypatch.setattr(mod, "run_kubectl", fake_run_kubectl)

    result = mod.collect_process_samples(
        pods,
        namespace="deer-flow",
        kubectl="kubectl",
        limit=5,
        kubectl_timeout=7,
    )

    assert result.samples["sandbox-ok"][0].pid == 20
    assert result.errors == {"sandbox-timeout": "kubectl exec timed out after 7 seconds"}


def test_render_markdown_includes_sample_and_notes():
    mod = _load_module()
    report = mod.build_report(
        namespace="deer-flow",
        selector="app=deer-flow-sandbox",
        sample="after-python",
        top_pods=mod.parse_top_pods("sandbox-abc 29m 792Mi\n"),
        pod_json={"items": []},
    )

    markdown = mod.render_markdown(report)

    assert "Sample: `after-python`" in markdown
    assert "Pods with process samples: `0`" in markdown
    assert "Pods with process sample errors: `0`" in markdown
    assert "| sandbox-abc |" in markdown
    assert "kubectl top reports Kubernetes/container working set memory" in markdown


def test_collect_rejects_invalid_kubectl_timeout():
    mod = _load_module()

    try:
        mod.collect(
            namespace="deer-flow",
            selector="app=deer-flow-sandbox",
            sample="empty",
            kubectl="kubectl",
            kubectl_timeout=0,
        )
    except ValueError as exc:
        assert "kubectl-timeout" in str(exc)
    else:
        raise AssertionError("expected ValueError")
