#!/usr/bin/env python3
"""Provider-agnostic sandbox benchmark.

Measures acquire / run / release latency across providers, scenarios,
workloads, and concurrency levels.  Outputs JSONL for aggregation.

Usage::

    python scripts/benchmark/sandbox/bench_provider.py \\
        --provider boxlite \\
        --scenario warm_same_thread \\
        --workload noop \\
        --iterations 50 \\
        --concurrency 4 \\
        --output results.jsonl

    python scripts/benchmark/sandbox/bench_provider.py \\
        --provider boxlite \\
        --scenario cold_unique_thread \\
        --no-warmpool \\
        --iterations 30 \\
        --output results.jsonl

Providers
---------
``boxlite``       BoxLite micro-VM sandbox (requires ``pip install boxlite``).
``aio-docker``    AIO Docker sandbox (requires Docker daemon + ``deerflow-harness`` extras).

Scenarios
---------
``warm_same_thread``       Reuse a scope per concurrent lane — warm pool hit after first turn.
``cold_unique_thread``     Fresh ``thread_id`` per turn — never hits warm pool.
``warm_miss_many_threads`` Rotate through N distinct threads — verifies isolation.
``idle_timeout``           Release, sleep > timeout, re-acquire — verify reaper works.
``replica_pressure``       Hold concurrent active clients past the replica soft cap.

Workloads
---------
``noop``          ``true`` — exposes acquire/release overhead.
``python_small``  ``python -c "print(sum(range(100000)))"`` — typical agent code.
``fs_1mb``        Write + read 1 MB file inside sandbox.
``sleep_2s``      ``sleep 2`` — verifies timeout handling + active-box protection.
``state_reuse``   Write state in turn N, verify it persists in turn N+1 (warm only).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import re
import statistics
import sys
import threading
import time
import types
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ── Output schema ───────────────────────────────────────────────────────


@dataclass
class BenchResult:
    provider: str
    scenario: str
    workload: str
    iteration: int
    concurrency: int
    thread_id: str
    user_id: str
    acquire_ms: float
    run_ms: float
    release_ms: float
    total_ms: float
    warm_hit: bool | None = None
    success: bool = True
    error: str | None = None
    # Provider config snapshot (written once per batch)
    replicas: int | None = None
    idle_timeout: float | None = None
    health_check_skip_seconds: float | None = None
    image: str | None = None
    no_warmpool: bool = False
    sandbox_id: str | None = None
    users: int = 1
    run_id: str | None = None
    # These are instantaneous provider snapshots, not Docker/VM resource metrics.
    active_at_acquire: int | None = None
    warm_at_acquire: int | None = None
    cleanup_ms: float = 0.0
    barrier_wait_ms: float = 0.0
    fault_injected: bool = False


# ── Workloads ───────────────────────────────────────────────────────────

WORKLOADS: dict[str, str] = {
    "noop": "true",
    "python_small": 'python -c "print(sum(range(100000)))"',
    "fs_1mb": """python - <<'PY'
from pathlib import Path
p = Path("/tmp/bench_file.txt")
p.write_text("x" * 1024 * 1024)
print(len(p.read_text()))
PY""",
    "sleep_2s": """python - <<'PY'
import time
time.sleep(2)
print("done")
PY""",
}

# state_reuse is a two-step workload; handled separately
_STATE_WRITE = """python - <<'PY'
from pathlib import Path
Path("/tmp/warm_state.txt").write_text("benchmark-state-42")
print("written")
PY"""

_STATE_READ = """python - <<'PY'
from pathlib import Path
print(Path("/tmp/warm_state.txt").read_text())
PY"""


# ── Provider factories ──────────────────────────────────────────────────


def _stub_config(sandbox_attrs: dict[str, Any] | None = None) -> types.SimpleNamespace:
    """Build a stub config namespace mimicking ``get_app_config()``."""
    attrs = sandbox_attrs or {}
    return types.SimpleNamespace(sandbox=types.SimpleNamespace(**attrs))


@contextmanager
def _patched_module_attr(module_name: str, attr_name: str, value: Any):
    module = importlib.import_module(module_name)
    original = getattr(module, attr_name)
    setattr(module, attr_name, value)
    try:
        yield module
    finally:
        setattr(module, attr_name, original)


def _boxlite_version() -> str | None:
    try:
        return importlib.metadata.version("boxlite")
    except importlib.metadata.PackageNotFoundError:
        return None


def _chmod_boxlite_shims(boxes_dir: str) -> int:
    fixed = 0
    for shim in Path(boxes_dir).glob("*/bin/boxlite-shim"):
        st = shim.stat()
        if st.st_mode & 0o111:
            continue
        shim.chmod(st.st_mode | 0o111)
        fixed += 1
    return fixed


def _create_box_with_097_shim_workaround(
    create_box: Callable[[str], Any],
    sandbox_id: str,
    *,
    boxes_dir: str,
) -> Any:
    try:
        return create_box(sandbox_id)
    except RuntimeError as exc:
        version = _boxlite_version()
        if version != "0.9.7":
            raise RuntimeError(f"BoxLite benchmark shim workaround only supports boxlite 0.9.7; got {version!r}") from exc
        fixed = _chmod_boxlite_shims(boxes_dir)
        if fixed == 0:
            raise
        return create_box(sandbox_id)


def _make_boxlite_provider(config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Create a BoxliteProvider with stub config; returns (provider, config_used).

    On BoxLite 0.9.7 only, retries a failed create after fixing missing execute
    bits on extracted ``boxlite-shim`` binaries under ``~/.boxlite/boxes``.
    """
    from deerflow.community.boxlite.provider import BoxliteProvider

    sandbox_attrs = {
        "image": config.get("image") or "python:3.12-slim",
        "replicas": config.get("replicas", 3),
        "idle_timeout": config.get("idle_timeout", 600),
        "health_check_skip_seconds": config.get("health_check_skip_seconds", 0.0),
    }
    if "memory_mib" in config:
        sandbox_attrs["memory_mib"] = config["memory_mib"]
    if "cpus" in config:
        sandbox_attrs["cpus"] = config["cpus"]
    if "environment" in config:
        sandbox_attrs["environment"] = config["environment"]

    with _patched_module_attr(
        "deerflow.community.boxlite.provider",
        "get_app_config",
        lambda: _stub_config(sandbox_attrs),
    ):
        provider = BoxliteProvider()

    original_create_box = provider._create_box
    boxes_dir = os.path.expanduser("~/.boxlite/boxes")

    def _patched_create_box(self: Any, sandbox_id: str) -> Any:
        return _create_box_with_097_shim_workaround(
            original_create_box,
            sandbox_id,
            boxes_dir=boxes_dir,
        )

    provider._create_box = types.MethodType(_patched_create_box, provider)
    return provider, sandbox_attrs


def _make_aio_provider(config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Create an AioSandboxProvider with stub config."""
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.config.sandbox_config import SandboxNetworkConfig

    sandbox_attrs = {
        "image": config.get("image"),
        "port": config.get("port"),
        "container_prefix": config.get("container_prefix"),
        "replicas": config.get("replicas", 3),
        "idle_timeout": config.get("idle_timeout", 600),
        "mounts": config.get("mounts", []),
        "environment": config.get("environment", {}),
        "provisioner_url": config.get("provisioner_url", ""),
    }
    stub = _stub_config(sandbox_attrs)
    stub.sandbox.network = SandboxNetworkConfig()

    with _patched_module_attr(
        "deerflow.community.aio_sandbox.aio_sandbox_provider",
        "get_app_config",
        lambda: stub,
    ):
        provider = AioSandboxProvider()
    return provider, {**sandbox_attrs, "image": provider._config["image"]}


PROVIDER_FACTORIES: dict[str, Callable] = {
    "boxlite": _make_boxlite_provider,
    "aio-docker": _make_aio_provider,
}


# ── Warm-hit tracking ───────────────────────────────────────────────────
_WARM_HIT_STATE = threading.local()


def _install_warm_hit_tracking(provider: Any) -> None:
    """Record warm-pool reclaims from inside the provider acquire path."""
    if getattr(provider, "_bench_warm_hit_tracking_installed", False):
        return

    installed = False
    for method_name in ("_reclaim_warm_pool", "_reclaim_warm_pool_sandbox"):
        original = getattr(provider, method_name, None)
        if original is None:
            continue

        def _wrapped(*args: Any, _original: Callable = original, **kwargs: Any):
            result = _original(*args, **kwargs)
            if result is not None:
                _WARM_HIT_STATE.value = True
            return result

        setattr(provider, method_name, _wrapped)
        installed = True

    setattr(provider, "_bench_warm_hit_tracking_installed", installed)


def _reset_warm_hit_tracking() -> None:
    _WARM_HIT_STATE.value = False


def _warm_hit_from_acquire() -> bool:
    return bool(getattr(_WARM_HIT_STATE, "value", False))


def _evict_from_warm(provider: Any, sandbox_id: str) -> None:
    """Destroy exactly this acquired resource; never pop AIO metadata first."""
    with provider._lock:
        entry = provider._warm_pool.get(sandbox_id)
    destroy = getattr(provider, "destroy", None)
    if callable(destroy):
        if destroy(sandbox_id) is False:
            raise RuntimeError(f"Destroy deferred for {sandbox_id}; cold baseline is invalid")
        backend = getattr(provider, "_backend", None)
        if entry is not None and backend is not None and backend.is_alive(entry[0]):
            raise RuntimeError(f"Container still alive after destroy: {sandbox_id}")
    elif callable(getattr(provider, "_invalidate_box", None)):
        # BoxLite has no public destroy; its terminal-invalidation path owns all
        # identity/health-check bookkeeping and propagates close failures.
        provider._invalidate_box(sandbox_id, reason="benchmark_no_warmpool")
    else:
        raise RuntimeError("Provider has no supported benchmark destroy adapter")


def _crash_warm_resource(provider: Any, sandbox_id: str) -> None:
    """Crash the exact returned resource, leaving its stale entry for recovery."""
    with provider._lock:
        entry = provider._warm_pool.get(sandbox_id)
    if entry is None:
        raise RuntimeError(f"No warm resource to fault: {sandbox_id}")
    resource = entry[0]
    backend = getattr(provider, "_backend", None)
    if backend is not None:
        backend.destroy(resource)
        if backend.is_alive(resource):
            raise RuntimeError(f"Fault injection did not stop {sandbox_id}")
    else:
        resource.close()


def _pool_counts(provider: Any) -> tuple[int | None, int]:
    with provider._lock:
        count_active = getattr(provider, "_active_count_locked", None)
        return count_active() if callable(count_active) else None, len(provider._warm_pool)


# ── Core benchmark runner ───────────────────────────────────────────────


def _run_one_turn(
    provider: Any,
    provider_name: str,
    scenario: str,
    workload_name: str,
    command: str,
    iteration: int,
    concurrency: int,
    user_id: str,
    thread_id: str,
    no_warmpool: bool,
    state_write_turn: bool = False,
    expected_state: str | None = None,
    acquired_barrier: threading.Barrier | None = None,
) -> BenchResult:
    """Execute one acquire→run→release cycle and return a BenchResult."""
    t0 = time.perf_counter()
    sid: str | None = None
    warm_hit: bool | None = None
    acquire_ms = 0.0
    run_ms = 0.0
    release_ms = 0.0
    release_needed = False
    cleanup_ms = 0.0
    active_count: int | None = None
    warm_count: int | None = None
    barrier_wait_ms = 0.0

    try:
        tracked_warm_hit = getattr(provider, "_bench_warm_hit_tracking_installed", False)
        _reset_warm_hit_tracking()
        t_a = time.perf_counter()
        try:
            sid = provider.acquire(thread_id, user_id=user_id)
        finally:
            acquire_ms = (time.perf_counter() - t_a) * 1000
        if tracked_warm_hit:
            warm_hit = _warm_hit_from_acquire()
        release_needed = True

        if acquired_barrier is not None:
            t_barrier = time.perf_counter()
            acquired_barrier.wait(timeout=120)
        active_count, warm_count = _pool_counts(provider)
        if acquired_barrier is not None:
            # Keep every acquired client alive until all snapshots are taken.
            acquired_barrier.wait(timeout=120)
            barrier_wait_ms = (time.perf_counter() - t_barrier) * 1000

        sandbox = provider.get(sid)
        if sandbox is None:
            raise RuntimeError(f"acquire returned {sid!r} but get() returned None")

        cmd = command
        if state_write_turn:
            cmd = _STATE_WRITE
        elif expected_state is not None:
            cmd = _STATE_READ

        t_c = time.perf_counter()
        try:
            output = sandbox.execute_command(cmd, timeout=30)
        finally:
            run_ms = (time.perf_counter() - t_c) * 1000
        # Sandbox.execute_command is a text API. Both adapters render nonzero
        # exits in-band; AIO also reports indeterminate/terminated sessions.
        if output.startswith("Error:") or re.search(r"(?:Exit Code:|Command exited with code)\s*-?[1-9]\d*", output) or "command outcome is unknown" in output.casefold() or "command was terminated" in output.casefold():
            raise RuntimeError(output)

        if expected_state is not None:
            if expected_state.strip() not in output.strip():
                raise RuntimeError(f"State reuse failed: expected {expected_state!r} in output, got {output.strip()!r}")

        t_e = time.perf_counter()
        try:
            provider.release(sid)
        finally:
            release_ms += (time.perf_counter() - t_e) * 1000
        release_needed = False

        if no_warmpool:
            t_cleanup = time.perf_counter()
            try:
                _evict_from_warm(provider, sid)
            finally:
                cleanup_ms += (time.perf_counter() - t_cleanup) * 1000

        return BenchResult(
            provider=provider_name,
            scenario=scenario,
            workload=workload_name,
            iteration=iteration,
            concurrency=concurrency,
            thread_id=thread_id,
            user_id=user_id,
            acquire_ms=acquire_ms,
            run_ms=run_ms,
            release_ms=release_ms,
            total_ms=(time.perf_counter() - t0) * 1000,
            warm_hit=warm_hit,
            success=True,
            no_warmpool=no_warmpool,
            sandbox_id=sid,
            active_at_acquire=active_count,
            warm_at_acquire=warm_count,
            cleanup_ms=cleanup_ms,
            barrier_wait_ms=barrier_wait_ms,
        )

    except Exception as exc:
        if acquired_barrier is not None:
            acquired_barrier.abort()
        release_error: str | None = None
        if sid is not None and release_needed:
            try:
                t_release = time.perf_counter()
                try:
                    provider.release(sid)
                finally:
                    release_ms += (time.perf_counter() - t_release) * 1000
                if no_warmpool:
                    t_cleanup = time.perf_counter()
                    try:
                        _evict_from_warm(provider, sid)
                    finally:
                        cleanup_ms += (time.perf_counter() - t_cleanup) * 1000
            except Exception as release_exc:
                release_error = repr(release_exc)
        error = str(exc) if str(exc).startswith("Error:") else repr(exc)
        if release_error is not None:
            error = f"{error}; release_error={release_error}"
        return BenchResult(
            provider=provider_name,
            scenario=scenario,
            workload=workload_name,
            iteration=iteration,
            concurrency=concurrency,
            thread_id=thread_id,
            user_id=user_id,
            acquire_ms=acquire_ms,
            run_ms=run_ms,
            release_ms=release_ms,
            total_ms=(time.perf_counter() - t0) * 1000,
            warm_hit=warm_hit,
            success=False,
            error=error,
            no_warmpool=no_warmpool,
            sandbox_id=sid,
            active_at_acquire=active_count,
            warm_at_acquire=warm_count,
            cleanup_ms=cleanup_ms,
            barrier_wait_ms=barrier_wait_ms,
        )


def _write_results(results: list[BenchResult], output_path: Path, config_used: dict[str, Any]) -> None:
    for result in results:
        result.replicas = config_used.get("replicas")
        result.idle_timeout = config_used.get("idle_timeout")
        result.health_check_skip_seconds = config_used.get("health_check_skip_seconds")
        result.image = config_used.get("image")
    with output_path.open("a", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


def _run_scenario(
    provider: Any,
    provider_name: str,
    scenario: str,
    workload_name: str,
    iterations: int,
    concurrency: int,
    output_path: Path,
    no_warmpool: bool,
    config_used: dict[str, Any],
    fault_inject_after: int | None = None,
    users: int = 1,
    run_id: str | None = None,
) -> list[BenchResult]:
    command = WORKLOADS.get(workload_name, WORKLOADS["noop"])
    run_id = run_id or uuid.uuid4().hex[:12]
    is_state_reuse = workload_name == "state_reuse"
    pressure_slots = max(concurrency, int(config_used.get("replicas", 3)) * 2)
    scope_locks: dict[tuple[str, str], threading.Lock] = {}
    scope_lock_guard = threading.Lock()

    def _run_one(i: int, barrier: threading.Barrier | None = None) -> BenchResult:
        # Repeated state turns stay paired per user; every invocation gets a
        # fresh namespace, so an earlier process cannot masquerade as cold.
        user_index = (i // 2 if is_state_reuse else i) % users
        user_id = f"bench-user-{user_index}"
        if scenario == "cold_unique_thread":
            tid = f"cold-{i}"
        elif scenario == "warm_same_thread":
            tid = f"warm-hit-{i % concurrency}"
        elif scenario == "replica_pressure":
            tid = f"pressure-{i % pressure_slots}"
        else:
            tid = f"thread-{i % max(concurrency, 4)}"
        tid = f"{run_id}-{tid}"
        with scope_lock_guard:
            scope_lock = scope_locks.setdefault((user_id, tid), threading.Lock())
        with scope_lock:
            result = _run_one_turn(
                provider,
                provider_name,
                scenario,
                workload_name,
                command,
                i,
                concurrency,
                user_id,
                tid,
                no_warmpool,
                state_write_turn=is_state_reuse and i % 2 == 0,
                expected_state="benchmark-state-42" if is_state_reuse and i % 2 == 1 else None,
                acquired_barrier=barrier,
            )
            result.users = users
            result.run_id = run_id
            if fault_inject_after == i and result.success:
                try:
                    if result.sandbox_id is None:
                        raise RuntimeError("Fault injection requires a returned sandbox ID")
                    _crash_warm_resource(provider, result.sandbox_id)
                    result.fault_injected = True
                except Exception as exc:
                    result.success = False
                    result.error = f"Fault injection failed: {exc!r}"
            return result

    results: list[BenchResult] = []
    if concurrency == 1:
        results = [_run_one(i) for i in range(iterations)]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            if scenario == "replica_pressure":
                # Real simultaneous active clients, including the last partial
                # batch. Barrier failures abort peers rather than leak holders.
                for start in range(0, iterations, concurrency):
                    batch = range(start, min(start + concurrency, iterations))
                    barrier = threading.Barrier(len(batch))
                    futures = [pool.submit(_run_one, i, barrier) for i in batch]
                    results.extend(future.result() for future in as_completed(futures))
            else:
                futures = [pool.submit(_run_one, i) for i in range(iterations)]
                results.extend(future.result() for future in as_completed(futures))
    results.sort(key=lambda result: result.iteration)
    _write_results(results, output_path, config_used)
    return results


# ── CLI ─────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Provider-agnostic sandbox benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--provider",
        default="boxlite",
        choices=list(PROVIDER_FACTORIES),
        help="Sandbox provider to benchmark",
    )
    p.add_argument(
        "--scenario",
        default="warm_same_thread",
        choices=[
            "warm_same_thread",
            "cold_unique_thread",
            "warm_miss_many_threads",
            "idle_timeout",
            "replica_pressure",
        ],
        help="Benchmark scenario",
    )
    p.add_argument(
        "--workload",
        default="noop",
        choices=list(WORKLOADS) + ["state_reuse"],
        help="Command to run inside the sandbox",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of acquire→run→release turns (default: 50)",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent turns (default: 1)",
    )
    p.add_argument(
        "--output",
        default="bench_results.jsonl",
        help="JSONL output file (appended, default: bench_results.jsonl)",
    )
    p.add_argument("--users", type=int, default=1, help="Distinct user identities, assigned round-robin (default: 1)")
    p.add_argument("--run-id", default=None, help="Thread namespace; defaults to a fresh ID to avoid reuse from an earlier invocation")
    p.add_argument(
        "--no-warmpool",
        action="store_true",
        help="Evict from warm pool immediately after release (baseline)",
    )
    p.add_argument(
        "--replicas",
        type=int,
        default=3,
        help="sandbox.replicas config value (default: 3)",
    )
    p.add_argument(
        "--idle-timeout",
        type=float,
        default=600,
        help="sandbox.idle_timeout in seconds (default: 600)",
    )
    p.add_argument(
        "--health-check-skip-seconds",
        type=float,
        default=0.0,
        help="sandbox.health_check_skip_seconds in seconds (default: 0.0)",
    )
    p.add_argument(
        "--image",
        default=None,
        help="OCI image override (default: provider-specific)",
    )
    p.add_argument(
        "--warmup-iterations",
        type=int,
        default=1,
        help="Warm-up turns before timed iterations (default: 1)",
    )
    p.add_argument(
        "--fault-inject",
        type=int,
        default=None,
        metavar="N",
        help="After iteration N, close the warm-pool box to simulate a VM crash",
    )
    return p.parse_args(argv)


# ── Main ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if min(args.concurrency, args.users, args.replicas) < 1 or min(args.iterations, args.warmup_iterations) < 0:
        raise SystemExit("concurrency, users and replicas must be positive; iteration counts must be nonnegative")
    if args.fault_inject is not None and (args.concurrency != 1 or args.no_warmpool or args.scenario != "warm_same_thread"):
        raise SystemExit("fault injection requires warm_same_thread, concurrency=1 and an enabled warm pool")
    if args.fault_inject is not None and not 0 <= args.fault_inject < args.iterations:
        raise SystemExit("fault injection iteration must be inside the measured batch")
    if args.scenario == "idle_timeout" and (args.concurrency != 1 or args.idle_timeout <= 0):
        raise SystemExit("idle_timeout requires concurrency=1 and a positive idle timeout")
    if args.workload == "state_reuse" and (args.scenario != "warm_same_thread" or args.concurrency != 1):
        raise SystemExit("state_reuse requires --scenario warm_same_thread --concurrency 1")
    args.run_id = args.run_id or uuid.uuid4().hex[:12]

    output_path = Path(args.output)

    config: dict[str, Any] = {
        "replicas": args.replicas,
        "idle_timeout": args.idle_timeout,
        "health_check_skip_seconds": args.health_check_skip_seconds,
        "image": args.image,
        # Never discover/clean containers belonging to a user's regular stack.
        "container_prefix": f"deerflow-bench-{args.run_id}",
    }

    factory = PROVIDER_FACTORIES[args.provider]
    provider, config_used = factory(config)
    _install_warm_hit_tracking(provider)

    if output_path.exists():
        header = f"# provider={args.provider} scenario={args.scenario} workload={args.workload} concurrency={args.concurrency} iterations={args.iterations} no_warmpool={args.no_warmpool}\n"
        with output_path.open("a", encoding="utf-8") as f:
            f.write(header)

    try:
        # --- Warm-up (not measured) ---
        if args.warmup_iterations > 0:
            print(
                f"Warming up ({args.warmup_iterations} turn(s))...",
                file=sys.stderr,
            )
            for i in range(args.warmup_iterations):
                warmup = _run_one_turn(
                    provider=provider,
                    provider_name=args.provider,
                    scenario="warmup",
                    workload_name="noop",
                    command="true",
                    iteration=-(args.warmup_iterations - i),
                    concurrency=1,
                    user_id="bench-user",
                    thread_id=f"{args.run_id}-warmup",
                    no_warmpool=True,
                )
                if not warmup.success:
                    warmup.run_id = args.run_id
                    _write_results([warmup], output_path, config_used)
                    print(f"Warm-up failed: {warmup.error}", file=sys.stderr)
                    return 1

        # --- Idle-timeout scenario: special handling ---
        if args.scenario == "idle_timeout":
            return _run_idle_timeout_scenario(provider, args, output_path, config_used)

        # --- Replica pressure scenario: special handling ---
        if args.scenario == "replica_pressure":
            return _run_replica_pressure_scenario(provider, args, output_path, config_used)

        # --- Standard scenarios ---
        print(
            f"Running: provider={args.provider} scenario={args.scenario} workload={args.workload} concurrency={args.concurrency} iterations={args.iterations}",
            file=sys.stderr,
        )

        results = _run_scenario(
            provider=provider,
            provider_name=args.provider,
            scenario=args.scenario,
            workload_name=args.workload,
            iterations=args.iterations,
            concurrency=args.concurrency,
            output_path=output_path,
            no_warmpool=args.no_warmpool,
            config_used=config_used,
            fault_inject_after=args.fault_inject,
            users=args.users,
            run_id=args.run_id,
        )

        _print_summary(results, args)
        return int(any(not result.success for result in results))

    finally:
        provider.shutdown()


def _run_idle_timeout_scenario(
    provider: Any,
    args: argparse.Namespace,
    output_path: Path,
    config_used: dict[str, Any],
) -> int:
    """Acquire, release, force-reap warm entries, verify re-acquire is cold.

    The idle reaper thread runs every 60 s by default — too slow for a
    benchmark.  We call ``_reap_expired_warm`` directly after the sleep to
    simulate the reaper firing.
    """
    idle = args.idle_timeout
    print(
        f"Idle timeout scenario: acquire, release, force-reap after {idle + 1}s sleep (timeout={idle}s)",
        file=sys.stderr,
    )

    results: list[BenchResult] = []
    for i in range(min(args.iterations, 20)):
        tid = f"{args.run_id}-idle-{i}"
        user_id = f"bench-user-{i % args.users}"
        r1 = _run_one_turn(
            provider,
            args.provider,
            "idle_timeout",
            args.workload,
            WORKLOADS.get(args.workload, "true"),
            i * 2,
            args.concurrency,
            user_id,
            tid,
            args.no_warmpool,
        )
        results.append(r1)

        # Sleep past the idle timeout, then force-reap
        print(f"  Sleeping {idle + 1}s then force-reaping...", file=sys.stderr)
        time.sleep(idle + 1)
        provider._reap_expired_warm(idle_timeout=idle)

        r2 = _run_one_turn(
            provider,
            args.provider,
            "idle_timeout",
            args.workload,
            WORKLOADS.get(args.workload, "true"),
            i * 2 + 1,
            args.concurrency,
            user_id,
            tid,
            args.no_warmpool,
        )
        if r2.warm_hit:
            r2.success = False
            r2.error = "Idle-timeout reaping retained a warm entry"
            print(
                f"  WARNING: turn {i * 2 + 1} was a warm hit — reaping may not have removed the entry",
                file=sys.stderr,
            )
        results.append(r2)

    for r in results:
        r.users = args.users
        r.run_id = args.run_id
    _write_results(results, output_path, config_used)

    _print_summary(results, args)
    return int(any(not result.success for result in results))


def _run_replica_pressure_scenario(
    provider: Any,
    args: argparse.Namespace,
    output_path: Path,
    config_used: dict[str, Any],
) -> int:
    """Hold real concurrent clients; replicas is a soft warm-pool cap."""
    results = _run_scenario(
        provider,
        args.provider,
        "replica_pressure",
        args.workload,
        args.iterations,
        args.concurrency,
        output_path,
        args.no_warmpool,
        config_used,
        users=args.users,
        run_id=args.run_id,
    )
    _print_summary(results, args)
    return int(any(not result.success for result in results))


def _print_summary(results: list[BenchResult], args: argparse.Namespace) -> None:
    """Print a quick summary to stderr."""
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]
    warm = [r for r in ok if r.warm_hit]
    cold = [r for r in ok if r.warm_hit is False]

    if not ok:
        print("All iterations failed.", file=sys.stderr)
        for r in fail:
            print(f"  {r.error}", file=sys.stderr)
        return

    def _p(arr: list[float], pct: int) -> float:
        if len(arr) < 2:
            return arr[0] if arr else 0.0
        # Match summarize.py: inclusive, linearly interpolated percentiles.
        return statistics.quantiles(arr, n=100, method="inclusive")[pct - 1]

    a = [r.acquire_ms for r in ok]
    t = [r.total_ms for r in ok]

    print(file=sys.stderr)
    print(
        f"Results: {len(ok)} ok, {len(fail)} fail, {len(warm)} warm hits, {len(cold)} cold",
        file=sys.stderr,
    )
    print(
        f"  acquire: p50={_p(a, 50):.1f}ms p95={_p(a, 95):.1f}ms p99={_p(a, 99):.1f}ms",
        file=sys.stderr,
    )
    print(
        f"  total:   p50={_p(t, 50):.1f}ms p95={_p(t, 95):.1f}ms p99={_p(t, 99):.1f}ms",
        file=sys.stderr,
    )
    print(f"  output → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
