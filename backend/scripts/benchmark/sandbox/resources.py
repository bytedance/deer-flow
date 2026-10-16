#!/usr/bin/env python3
"""Sample resources for a uniquely prefixed Docker benchmark run, without mutation.

Run from ``backend`` alongside the benchmark::

    python -m scripts.benchmark.sandbox.resources \
        --prefix deerflow-bench-<run-id>- --output resources.jsonl --duration 60

The caller must reserve a unique prefix and use it for benchmark containers.
Only matching *running* containers are measured. An empty successful inventory
means zero; unavailable, partial or invalid measurements remain unknown (null).
Peaks are peaks of samples, not guaranteed process maxima. Docker's reported
memory excludes cache on Linux; CPU is Docker's percentage and may exceed 100.
This does not measure Docker VM overhead or assign active/warm lifecycle states.
Use the provider benchmark's lifecycle records alongside these samples.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


def _validate_prefix(prefix: str) -> None:
    if not isinstance(prefix, str) or len(prefix) < 8 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*-", prefix):
        raise ValueError("Use a unique container prefix of at least 8 characters ending in '-'; only Docker name characters are allowed")


def parse_bytes(value: str) -> int | None:
    """Parse Docker's decimal SI and binary IEC memory values; invalid is unknown."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmMgGtTpP]?[iI]?[bB])\s*", value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    power = "bkmgtp".index(unit[0]) if unit != "b" else 0
    amount = number * (1024 if "i" in unit else 1000) ** power
    return int(amount) if math.isfinite(amount) else None


def _cpu_percent(value: str) -> float | None:
    if not re.fullmatch(r"\d+(?:\.\d+)?%", value.strip()):
        return None
    result = float(value.strip()[:-1])
    return result if math.isfinite(result) else None


def _docker(command: list[str], timeout: float) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return only selected JSON fields downstream; never persist CLI error output."""
    try:
        process = subprocess.run(["docker", *command], check=True, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"docker_{command[0]}_timeout"
    except subprocess.CalledProcessError:
        return None, f"docker_{command[0]}_failed"
    except OSError:
        return None, f"docker_{command[0]}_unavailable"
    try:
        rows = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    except (ValueError, TypeError):
        return None, f"invalid_{command[0]}_json"
    if any(not isinstance(row, dict) for row in rows):
        return None, f"invalid_{command[0]}_json"
    return rows, None


def collect_docker_sample(prefix: str, *, command_timeout: float = 5.0) -> dict[str, Any]:
    """Inventory exact name-prefix matches, then request stats for their IDs only."""
    _validate_prefix(prefix)
    if not math.isfinite(command_timeout) or command_timeout <= 0:
        raise ValueError("command_timeout must be finite and positive")
    started = time.monotonic()
    sample: dict[str, Any] = {
        "record_type": "resource_sample",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "monotonic_s": started,
        "container_prefix": prefix,
        "matched_containers": None,
        "containers": [],
        "total_memory_bytes": None,
        "total_cpu_percent": None,
        "errors": [],
    }

    def finish() -> dict[str, Any]:
        sample["collection_seconds"] = time.monotonic() - started
        return sample

    inventory, error = _docker(["ps", "--no-trunc", "--format", "{{json .}}"], command_timeout)
    if inventory is None:
        sample["errors"].append(error)
        return finish()
    selected: dict[str, str] = {}
    for row in inventory:
        name = row.get("Names")
        if not isinstance(name, str):
            sample["errors"].append("invalid_inventory")
            return finish()
        if not name.startswith(prefix):
            continue
        container_id = row.get("ID")
        if not isinstance(container_id, str) or not re.fullmatch(r"[a-f0-9]{64}", container_id) or container_id in selected:
            sample["errors"].append("invalid_inventory")
            return finish()
        selected[container_id] = name
    sample["matched_containers"] = len(selected)
    if not selected:
        sample["total_memory_bytes"] = 0
        sample["total_cpu_percent"] = 0.0
        return finish()

    # An empty argument list means "all containers" to docker stats. Never call it
    # until exact local selection has produced at least one validated ID.
    stats, error = _docker(["stats", "--no-stream", "--format", "{{json .}}", "--", *selected], command_timeout)
    if stats is None:
        sample["errors"].append(error)
        stats = []
    for container_id, name in selected.items():
        # Docker stats normally abbreviates ID even though inventory is no-trunc.
        matching = [row for row in stats if isinstance(row.get("ID"), str) and re.fullmatch(r"[a-f0-9]{12,64}", row["ID"]) and container_id.startswith(row["ID"])]
        stat = matching[0] if len(matching) == 1 else {}
        usage = str(stat.get("MemUsage", "")).split("/")
        memory = parse_bytes(usage[0]) if len(usage) == 2 else None
        limit = parse_bytes(usage[1]) if len(usage) == 2 else None
        cpu = _cpu_percent(str(stat.get("CPUPerc", "")))
        if memory is None or limit is None or cpu is None:
            sample["errors"].append("missing_or_invalid_container_stats")
        sample["containers"].append({"container_id": container_id, "name": name, "memory_bytes": memory, "memory_limit_bytes": limit, "cpu_percent": cpu})
    containers = sample["containers"]
    if all(item["memory_bytes"] is not None for item in containers):
        sample["total_memory_bytes"] = sum(item["memory_bytes"] for item in containers)
    if all(item["cpu_percent"] is not None for item in containers):
        sample["total_cpu_percent"] = sum(item["cpu_percent"] for item in containers)
    sample["errors"] = list(dict.fromkeys(sample["errors"]))
    return finish()


class DockerResourceSampler:
    """Background sampler with drain-on-exit and an exclusively created JSONL file."""

    def __init__(self, prefix: str, output: str | Path, *, interval: float = 1.0, command_timeout: float = 5.0):
        _validate_prefix(prefix)
        if not all(math.isfinite(value) and value > 0 for value in (interval, command_timeout)):
            raise ValueError("interval and command_timeout must be finite and positive")
        self.prefix = prefix
        self.output = Path(output)
        self.interval = interval
        self.command_timeout = command_timeout
        self._stop = threading.Event()
        self._first_sample = threading.Event()
        self._thread: threading.Thread | None = None
        self._file: TextIO | None = None
        self._error: BaseException | None = None
        self.summary: dict[str, Any] = {
            "record_type": "resource_summary",
            "container_prefix": prefix,
            "sample_count": 0,
            "incomplete_samples": 0,
            "peak_sampled_total_memory_bytes": None,
            "peak_sampled_total_cpu_percent": None,
            "max_sampled_containers": None,
            "interval_seconds": interval,
            "peak_semantics": "maximum observed sample; not a guaranteed peak or host/VM total",
        }

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _write(self, value: dict[str, Any]) -> None:
        assert self._file is not None
        self._file.write(json.dumps(value, allow_nan=False) + "\n")
        self._file.flush()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                sample = collect_docker_sample(self.prefix, command_timeout=self.command_timeout)
                self._write(sample)
                self.summary["sample_count"] += 1
                self.summary["incomplete_samples"] += bool(sample["errors"])
                for field, target in (("total_memory_bytes", "peak_sampled_total_memory_bytes"), ("total_cpu_percent", "peak_sampled_total_cpu_percent"), ("matched_containers", "max_sampled_containers")):
                    value = sample[field]
                    previous = self.summary[target]
                    if value is not None and (previous is None or value > previous):
                        self.summary[target] = value
                self._first_sample.set()
                self._stop.wait(self.interval)
        except BaseException as exc:
            self._error = exc
        finally:
            self._first_sample.set()

    def start(self) -> DockerResourceSampler:
        if self._thread is not None:
            raise RuntimeError("A sampler instance can only be started once")
        self._file = self.output.open("x", encoding="utf-8")
        self._thread = threading.Thread(target=self._run, name="sandbox-resource-sampler")
        try:
            self._thread.start()
        except BaseException:
            self._file.close()
            self._file = None
            raise
        return self

    def wait_for_first_sample(self, timeout: float | None = None) -> bool:
        """Optional synchronization before a workload; never starts Docker resources."""
        return self._first_sample.wait(timeout)

    def stop(self) -> dict[str, Any]:
        if self._thread is None or self._file is None:
            return self.summary
        self._stop.set()
        # Each subprocess has a timeout. Drain the in-flight sample before closing
        # its output; a stop must not leave the writer or a Docker client running.
        self._thread.join()
        try:
            self.summary["timestamp_utc"] = datetime.now(UTC).isoformat()
            self.summary["monotonic_s"] = time.monotonic()
            self.summary["sampler_failed"] = self._error is not None
            self._write(self.summary)
        finally:
            self._file.close()
            self._file = None
        if self._error is not None:
            raise RuntimeError("Resource sampler failed; measurements are incomplete") from self._error
        return self.summary

    def __enter__(self) -> DockerResourceSampler:
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", required=True, help="Unique benchmark container prefix, ending in '-'")
    parser.add_argument("--output", required=True, type=Path, help="New JSONL file; existing files are never overwritten")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between completed samples")
    parser.add_argument("--command-timeout", type=float, default=5.0)
    parser.add_argument("--duration", type=float, required=True, help="Bounded measurement duration in seconds")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("duration must be finite and positive")
    try:
        sampler = DockerResourceSampler(args.prefix, args.output, interval=args.interval, command_timeout=args.command_timeout)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        with sampler:
            threading.Event().wait(args.duration)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
