#!/usr/bin/env python3
"""Collect Kubernetes sandbox pod memory snapshots for DeerFlow.

This script is intentionally lightweight: it shells out to ``kubectl`` and
emits either JSON or Markdown so maintainers can compare sandbox backends and
workloads without adding runtime dependencies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

DEFAULT_NAMESPACE = "deer-flow"
DEFAULT_SELECTOR = "app=deer-flow-sandbox"
DEFAULT_KUBECTL_TIMEOUT = 30


@dataclass(frozen=True)
class TopPod:
    name: str
    cpu_raw: str
    memory_raw: str
    cpu_millicores: int | None
    memory_bytes: int | None


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    ppid: int | None
    rss_kib: int
    command: str


@dataclass(frozen=True)
class ProcessSampleResult:
    samples: dict[str, list[ProcessSample]]
    errors: dict[str, str]


def parse_cpu_millicores(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("m"):
        number = value[:-1]
        return int(number) if number.isdigit() else None
    if value.isdigit():
        return int(value) * 1000
    return None


def parse_memory_bytes(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None

    suffixes = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }

    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            number = value[: -len(suffix)]
            try:
                return int(Decimal(number) * multiplier)
            except InvalidOperation:
                return None

    try:
        return int(value)
    except ValueError:
        return None


def format_mib(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value / 1024 / 1024:.1f} MiB"


def run_kubectl(
    args: list[str], *, kubectl: str, timeout: int = DEFAULT_KUBECTL_TIMEOUT
) -> str:
    completed = subprocess.run(
        [kubectl, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout


def parse_top_pods(output: str) -> list[TopPod]:
    pods: list[TopPod] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if parts and parts[0].upper() == "NAME":
            continue
        if len(parts) < 3:
            continue
        name, cpu_raw, memory_raw = parts[:3]
        pods.append(
            TopPod(
                name=name,
                cpu_raw=cpu_raw,
                memory_raw=memory_raw,
                cpu_millicores=parse_cpu_millicores(cpu_raw),
                memory_bytes=parse_memory_bytes(memory_raw),
            )
        )
    return pods


def parse_processes(output: str, *, limit: int) -> list[ProcessSample]:
    if limit < 1:
        raise ValueError("process limit must be greater than 0")

    processes: list[ProcessSample] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=3)
        if parts and parts[0].upper() == "PID":
            continue
        if len(parts) < 4:
            continue
        pid_raw, ppid_raw, rss_raw, command = parts
        try:
            pid = int(pid_raw)
            rss_kib = int(rss_raw)
        except ValueError:
            continue
        try:
            ppid = int(ppid_raw)
        except ValueError:
            ppid = None
        processes.append(
            ProcessSample(pid=pid, ppid=ppid, rss_kib=rss_kib, command=command)
        )
    processes.sort(key=lambda process: process.rss_kib, reverse=True)
    return processes[:limit]


def _container_resources(pod: dict[str, Any]) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for container in pod.get("spec", {}).get("containers", []):
        name = container.get("name", "")
        if not name:
            continue
        resources[name] = {
            "image": container.get("image", ""),
            "requests": container.get("resources", {}).get("requests", {}),
            "limits": container.get("resources", {}).get("limits", {}),
        }
    return resources


def merge_pod_data(
    top_pods: list[TopPod], pod_json: dict[str, Any]
) -> list[dict[str, Any]]:
    pod_items = pod_json.get("items", []) if isinstance(pod_json, dict) else []
    metadata_by_name = {
        pod.get("metadata", {}).get("name"): pod
        for pod in pod_items
        if pod.get("metadata", {}).get("name")
    }

    rows: list[dict[str, Any]] = []
    for top in top_pods:
        pod = metadata_by_name.get(top.name, {})
        metadata = pod.get("metadata", {})
        status = pod.get("status", {})
        rows.append(
            {
                "name": top.name,
                "cpu": {
                    "raw": top.cpu_raw,
                    "millicores": top.cpu_millicores,
                },
                "memory": {
                    "raw": top.memory_raw,
                    "bytes": top.memory_bytes,
                    "mib": None
                    if top.memory_bytes is None
                    else round(top.memory_bytes / 1024 / 1024, 2),
                },
                "phase": status.get("phase", ""),
                "start_time": status.get("startTime", ""),
                "labels": metadata.get("labels", {}),
                "containers": _container_resources(pod),
                "processes": [],
            }
        )
    return rows


def attach_process_samples(
    pods: list[dict[str, Any]],
    process_samples: dict[str, list[ProcessSample]],
) -> list[dict[str, Any]]:
    for pod in pods:
        samples = process_samples.get(pod["name"], [])
        pod["processes"] = [
            {
                "pid": sample.pid,
                "ppid": sample.ppid,
                "rss_kib": sample.rss_kib,
                "rss_mib": round(sample.rss_kib / 1024, 2),
                "command": sample.command,
            }
            for sample in samples
        ]
    return pods


def build_report(
    *,
    namespace: str,
    selector: str,
    sample: str,
    top_pods: list[TopPod],
    pod_json: dict[str, Any],
    process_samples: dict[str, list[ProcessSample]] | None = None,
    process_errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    pods = merge_pod_data(top_pods, pod_json)
    if process_samples:
        pods = attach_process_samples(pods, process_samples)
    memory_values = [
        pod["memory"]["bytes"] for pod in pods if pod["memory"]["bytes"] is not None
    ]
    cpu_values = [
        pod["cpu"]["millicores"] for pod in pods if pod["cpu"]["millicores"] is not None
    ]
    unparsed_memory_count = len(pods) - len(memory_values)
    unparsed_cpu_count = len(pods) - len(cpu_values)

    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - keep Python 3.10 compatibility.
        "namespace": namespace,
        "selector": selector,
        "sample": sample,
        "summary": {
            "pod_count": len(pods),
            "parsed_memory_count": len(memory_values),
            "unparsed_memory_count": unparsed_memory_count,
            "total_memory_bytes": sum(memory_values),
            "total_memory_mib": round(sum(memory_values) / 1024 / 1024, 2),
            "average_memory_mib": round(
                (sum(memory_values) / len(memory_values)) / 1024 / 1024, 2
            )
            if memory_values
            else None,
            "max_memory_mib": round(max(memory_values) / 1024 / 1024, 2)
            if memory_values
            else None,
            "parsed_cpu_count": len(cpu_values),
            "unparsed_cpu_count": unparsed_cpu_count,
            "total_cpu_millicores": sum(cpu_values),
            "pods_with_process_samples": sum(1 for pod in pods if pod["processes"]),
            "pods_with_process_sample_errors": len(process_errors or {}),
        },
        "pods": pods,
        "process_errors": process_errors or {},
        "notes": [
            "kubectl top reports Kubernetes/container working set memory, not exclusive RSS/PSS.",
            "Process RSS samples are collected with ps inside the sandbox container and do not include all cgroup memory such as page cache.",
            "Compare multiple samples: empty sandbox, after bash, after Python/Node, after artifact generation, and warm reuse.",
            "Use identical workloads when comparing AIO with another sandbox backend.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DeerFlow Sandbox Memory Profile",
        "",
        f"- Captured at: `{report['captured_at']}`",
        f"- Namespace: `{report['namespace']}`",
        f"- Selector: `{report['selector']}`",
        f"- Sample: `{report['sample']}`",
        f"- Pods: `{summary['pod_count']}`",
        f"- Parsed memory samples: `{summary['parsed_memory_count']}`",
        f"- Unparsed memory samples: `{summary['unparsed_memory_count']}`",
        f"- Total memory: `{format_mib(summary['total_memory_bytes'])}`",
        f"- Average memory: `{summary['average_memory_mib']} MiB`"
        if summary["average_memory_mib"] is not None
        else "- Average memory: `-`",
        f"- Max memory: `{summary['max_memory_mib']} MiB`"
        if summary["max_memory_mib"] is not None
        else "- Max memory: `-`",
        f"- Total CPU: `{summary['total_cpu_millicores']}m`",
        f"- Pods with process samples: `{summary['pods_with_process_samples']}`",
        f"- Pods with process sample errors: `{summary['pods_with_process_sample_errors']}`",
        "",
        "| Pod | Phase | CPU | Memory | Start Time |",
        "| --- | --- | ---: | ---: | --- |",
    ]

    for pod in report["pods"]:
        lines.append(
            "| {name} | {phase} | {cpu} | {memory} | {start_time} |".format(
                name=pod["name"],
                phase=pod["phase"] or "-",
                cpu=pod["cpu"]["raw"],
                memory=pod["memory"]["raw"],
                start_time=pod["start_time"] or "-",
            )
        )

    sampled_pods = [pod for pod in report["pods"] if pod["processes"]]
    if sampled_pods:
        lines.extend(["", "## Top Processes"])
        for pod in sampled_pods:
            lines.extend(
                [
                    "",
                    f"### {pod['name']}",
                    "",
                    "| PID | PPID | RSS | Command |",
                    "| ---: | ---: | ---: | --- |",
                ]
            )
            for process in pod["processes"]:
                lines.append(
                    "| {pid} | {ppid} | {rss} | `{command}` |".format(
                        pid=process["pid"],
                        ppid=process["ppid"] if process["ppid"] is not None else "-",
                        rss=format_mib(process["rss_kib"] * 1024),
                        command=str(process["command"])
                        .replace("`", "'")
                        .replace("|", "\\|"),
                    )
                )

    if report["process_errors"]:
        lines.extend(["", "## Process Sample Errors"])
        for pod_name, error in sorted(report["process_errors"].items()):
            lines.append(f"- `{pod_name}`: {error}")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in report["notes"])
    lines.append("")
    return "\n".join(lines)


def collect_process_samples(
    top_pods: list[TopPod],
    *,
    namespace: str,
    kubectl: str,
    limit: int,
    kubectl_timeout: int = DEFAULT_KUBECTL_TIMEOUT,
) -> ProcessSampleResult:
    samples: dict[str, list[ProcessSample]] = {}
    errors: dict[str, str] = {}
    command = (
        "ps -eo pid,ppid,rss,args --sort=-rss 2>/dev/null || ps -eo pid,ppid,rss,args"
    )
    for pod in top_pods:
        try:
            output = run_kubectl(
                ["exec", "-n", namespace, pod.name, "--", "sh", "-c", command],
                kubectl=kubectl,
                timeout=kubectl_timeout,
            )
        except subprocess.CalledProcessError as exc:
            errors[pod.name] = (exc.stderr or str(exc)).strip()
            continue
        except subprocess.TimeoutExpired as exc:
            errors[pod.name] = f"kubectl exec timed out after {exc.timeout} seconds"
            continue
        samples[pod.name] = parse_processes(output, limit=limit)
    return ProcessSampleResult(samples=samples, errors=errors)


def collect(
    namespace: str,
    selector: str,
    sample: str,
    kubectl: str,
    *,
    include_processes: bool = False,
    process_limit: int = 10,
    kubectl_timeout: int = DEFAULT_KUBECTL_TIMEOUT,
) -> dict[str, Any]:
    if process_limit < 1:
        raise ValueError("--process-limit must be greater than 0")
    if kubectl_timeout < 1:
        raise ValueError("--kubectl-timeout must be greater than 0")
    top_output = run_kubectl(
        ["top", "pod", "-n", namespace, "-l", selector, "--no-headers"],
        kubectl=kubectl,
        timeout=kubectl_timeout,
    )
    top_pods = parse_top_pods(top_output)
    pods_output = run_kubectl(
        ["get", "pods", "-n", namespace, "-l", selector, "-o", "json"],
        kubectl=kubectl,
        timeout=kubectl_timeout,
    )
    process_result = None
    if include_processes:
        process_result = collect_process_samples(
            top_pods,
            namespace=namespace,
            kubectl=kubectl,
            limit=process_limit,
            kubectl_timeout=kubectl_timeout,
        )
    return build_report(
        namespace=namespace,
        selector=selector,
        sample=sample,
        top_pods=top_pods,
        pod_json=json.loads(pods_output),
        process_samples=process_result.samples if process_result else None,
        process_errors=process_result.errors if process_result else None,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--selector",
        default=DEFAULT_SELECTOR,
        help=f"Pod label selector (default: {DEFAULT_SELECTOR})",
    )
    parser.add_argument(
        "--sample",
        default="unspecified",
        help="Human-readable sample label, such as empty, after-bash, after-python",
    )
    parser.add_argument("--kubectl", default="kubectl", help="kubectl executable path")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--include-processes",
        action="store_true",
        help="Run kubectl exec ps in each sandbox pod and include top process RSS samples",
    )
    parser.add_argument(
        "--process-limit",
        type=int,
        default=10,
        help="Maximum processes to include per pod when --include-processes is set",
    )
    parser.add_argument(
        "--kubectl-timeout",
        type=int,
        default=DEFAULT_KUBECTL_TIMEOUT,
        help=f"Timeout in seconds for each kubectl call (default: {DEFAULT_KUBECTL_TIMEOUT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        report = collect(
            namespace=args.namespace,
            selector=args.selector,
            sample=args.sample,
            kubectl=args.kubectl,
            include_processes=args.include_processes,
            process_limit=args.process_limit,
            kubectl_timeout=args.kubectl_timeout,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        return exc.returncode or 1
    except subprocess.TimeoutExpired as exc:
        print(f"kubectl timed out after {exc.timeout} seconds", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
