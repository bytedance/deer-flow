#!/usr/bin/env python3
"""Shared infrastructure for the checkpoint benchmark family.

Pure, stateless helpers plus the child-process controller protocol used by
both bench_channels.py (storage microbenchmark) and bench_production.py
(production-shaped benchmark). Scripts in this folder import this module via
a sibling sys.path insert; it is not a package.
"""

from __future__ import annotations

import cProfile
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import AnyMessage

try:
    import resource
except ImportError:  # pragma: no cover - Windows only
    resource = None  # type: ignore[assignment]

GIT_SHA_ENV = "DEERFLOW_CHECKPOINT_BENCH_GIT_SHA"


def parse_positive_int_csv(value: str, *, option: str) -> list[int]:
    if not value or value.startswith(",") or value.endswith(",") or ",," in value:
        raise ValueError(f"{option} must be a comma-separated list of positive integers")
    result: list[int] = []
    seen: set[int] = set()
    duplicates: list[int] = []
    try:
        parsed = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError(f"{option} must be a comma-separated list of positive integers") from exc
    if any(item <= 0 for item in parsed):
        raise ValueError(f"{option} values must be positive integers")
    for item in parsed:
        if item not in seen:
            result.append(item)
            seen.add(item)
        elif item not in duplicates:
            duplicates.append(item)
    if duplicates:
        print(
            f"{option}: ignored duplicate value(s): {', '.join(str(item) for item in duplicates)}; use --repetitions for repeated samples.",
            file=sys.stderr,
        )
    return result


def parse_choice_csv(value: str, *, option: str, choices: tuple[str, ...]) -> list[str]:
    if not value or value.startswith(",") or value.endswith(",") or ",," in value:
        raise ValueError(f"{option} must contain one or more of: {', '.join(choices)}")
    result: list[str] = []
    duplicates: list[str] = []
    for raw in value.split(","):
        item = raw.strip()
        if item not in choices:
            raise ValueError(f"{option} contains unsupported value {item!r}; expected: {', '.join(choices)}")
        if item not in result:
            result.append(item)
        elif item not in duplicates:
            duplicates.append(item)
    if duplicates:
        print(
            f"{option}: ignored duplicate value(s): {', '.join(duplicates)}; use --repetitions for repeated samples.",
            file=sys.stderr,
        )
    return result


def canonical_messages_digest(messages: list[AnyMessage]) -> str:
    canonical = [
        {
            "id": message.id,
            "type": message.type,
            "content": message.content,
        }
        for message in messages
    ]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def window_median(values: list[float], window: Literal["first", "middle", "last"]) -> float:
    if not values:
        return 0.0
    width = max(1, len(values) // 10)
    if window == "first":
        selected = values[:width]
    elif window == "last":
        selected = values[-width:]
    else:
        center = len(values) // 2
        start = max(0, center - width // 2)
        selected = values[start : start + width]
    return statistics.median(selected)


def resolve_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            # scripts/benchmark/checkpoint/checkpoint_bench_common.py -> repo root
            cwd=Path(__file__).resolve().parents[4],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def safe_error(error: BaseException | str, *, work_dir: Path | None = None) -> str:
    message = str(error).replace(str(Path.home()), "<home>")
    if work_dir is not None:
        message = message.replace(str(work_dir), "<work-dir>")
    return message[:2000]


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak_rss) if sys.platform == "darwin" else int(peak_rss * 1024)


def run_profiled(fn: Callable[..., dict[str, Any]], *args: Any, profile_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Run *fn* under cProfile, mark the row, and dump stats."""
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profiler = cProfile.Profile()
    row = profiler.runcall(fn, *args, **kwargs)
    row["profiled"] = True
    profiler.dump_stats(profile_path)
    return row


def run_child_case(
    *,
    script: Path,
    worker_args: list[str],
    failure_row: Callable[[str], dict[str, Any]],
    timeout_seconds: float,
    git_sha: str,
) -> dict[str, Any]:
    """Run one benchmark case in a fresh child process; return its JSONL row.

    The child prints exactly one JSON row on its last stdout line. Any
    protocol failure is converted into a failure row via *failure_row*.
    """
    command = [sys.executable, str(script), *worker_args]
    started = time.perf_counter()
    child_env = os.environ.copy()
    child_env[GIT_SHA_ENV] = git_sha
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        return failure_row(f"child process timed out after {timeout_seconds:g} seconds")
    child_process_ms = (time.perf_counter() - started) * 1000
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not output_lines:
        return failure_row(f"child process returned {completed.returncode} without a result")
    try:
        row = json.loads(output_lines[-1])
    except json.JSONDecodeError:
        return failure_row(f"child process returned {completed.returncode} with malformed JSON")
    row["child_process_ms"] = child_process_ms
    if completed.returncode != 0 and row.get("success"):
        row["success"] = False
        row["error"] = f"child process exited with status {completed.returncode}"
    return row
