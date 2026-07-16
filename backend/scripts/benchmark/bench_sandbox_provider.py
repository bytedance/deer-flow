#!/usr/bin/env python3
"""Provider-agnostic sandbox benchmark.

Measures acquire / run / release latency across providers, scenarios,
workloads, and concurrency levels.  Outputs JSONL for aggregation.

Usage::

    python scripts/benchmark/bench_sandbox_provider.py \\
        --provider boxlite \\
        --scenario warm_same_thread \\
        --workload noop \\
        --iterations 50 \\
        --concurrency 4 \\
        --output results.jsonl

    python scripts/benchmark/bench_sandbox_provider.py \\
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
``warm_same_thread``       Reuse one ``(user_id, thread_id)`` — warm pool hit after first turn.
``cold_unique_thread``     Fresh ``thread_id`` per turn — never hits warm pool.
``warm_miss_many_threads`` Rotate through N distinct threads — verifies isolation.
``idle_timeout``           Release, sleep > timeout, re-acquire — verify reaper works.
``replica_pressure``       Push past ``replicas`` — verify eviction only targets warm entries.

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
import sys
import threading
import time
import types
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

    with _patched_module_attr(
        "deerflow.community.aio_sandbox.aio_sandbox_provider",
        "get_app_config",
        lambda: _stub_config(sandbox_attrs),
    ):
        provider = AioSandboxProvider()
    return provider, sandbox_attrs


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


def _compute_sandbox_id(provider: Any, thread_id: str, user_id: str) -> str:
    """Compute the deterministic sandbox_id the provider would use."""
    if hasattr(provider, "_sandbox_id"):
        return provider._sandbox_id(thread_id, user_id)
    # Fallback: use the provider's own method or hash
    import hashlib

    return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:8]


def _was_warm_hit(provider: Any, sandbox_id: str) -> bool:
    """Check if the sandbox_id is currently in the provider's warm pool."""
    with provider._lock:
        return sandbox_id in provider._warm_pool


def _evict_from_warm(provider: Any, sandbox_id: str) -> None:
    """Forcibly remove and destroy a warm-pool entry (no-warmpool simulation)."""
    with provider._lock:
        entry = provider._warm_pool.pop(sandbox_id, None)
    if entry is not None:
        box, _ = entry
        try:
            box.close()
        except Exception:
            pass


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
) -> BenchResult:
    """Execute one acquire→run→release cycle and return a BenchResult."""
    t0 = time.perf_counter()
    sandbox_id = _compute_sandbox_id(provider, thread_id, user_id)

    sid: str | None = None
    warm_hit: bool | None = None
    acquire_ms = 0.0
    run_ms = 0.0
    release_ms = 0.0
    release_needed = False

    try:
        tracked_warm_hit = getattr(provider, "_bench_warm_hit_tracking_installed", False)
        _reset_warm_hit_tracking()
        if not tracked_warm_hit:
            warm_hit = _was_warm_hit(provider, sandbox_id)

        t_a = time.perf_counter()
        sid = provider.acquire(thread_id, user_id=user_id)
        t_b = time.perf_counter()
        if tracked_warm_hit:
            warm_hit = _warm_hit_from_acquire()
        acquire_ms = (t_b - t_a) * 1000
        release_needed = True

        sandbox = provider.get(sid)
        if sandbox is None:
            raise RuntimeError(f"acquire returned {sid!r} but get() returned None")

        cmd = command
        if state_write_turn:
            cmd = _STATE_WRITE
        elif expected_state is not None:
            cmd = _STATE_READ

        t_c = time.perf_counter()
        output = sandbox.execute_command(cmd, timeout=30)
        t_d = time.perf_counter()
        run_ms = (t_d - t_c) * 1000
        if output.startswith("Error:"):
            raise RuntimeError(output)

        if expected_state is not None:
            if expected_state.strip() not in output.strip():
                raise RuntimeError(f"State reuse failed: expected {expected_state!r} in output, got {output.strip()!r}")

        t_e = time.perf_counter()
        provider.release(sid)
        release_needed = False
        t_f = time.perf_counter()
        release_ms = (t_f - t_e) * 1000

        if no_warmpool:
            _evict_from_warm(provider, sid)

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
            total_ms=(t_f - t0) * 1000,
            warm_hit=warm_hit,
            success=True,
            no_warmpool=no_warmpool,
        )

    except Exception as exc:
        release_error: str | None = None
        if sid is not None and release_needed:
            t_release = time.perf_counter()
            try:
                provider.release(sid)
                if no_warmpool:
                    _evict_from_warm(provider, sid)
            except Exception as release_exc:
                release_error = repr(release_exc)
            finally:
                release_ms = (time.perf_counter() - t_release) * 1000
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
        )


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
) -> list[BenchResult]:

    command = WORKLOADS.get(workload_name, WORKLOADS["noop"])

    # For state_reuse workload, run paired turns: write → read
    is_state_reuse = workload_name == "state_reuse"

    results: list[BenchResult] = []

    def _run_one(i: int) -> BenchResult:
        if scenario == "cold_unique_thread":
            tid = f"cold-{i}"
        elif scenario == "warm_same_thread":
            tid = "warm-hit"
        elif scenario == "warm_miss_many_threads":
            tid = f"thread-{i % max(concurrency, 4)}"
        elif scenario in ("idle_timeout", "replica_pressure"):
            tid = f"warm-hit-{i % concurrency}"
        else:
            tid = f"default-{i}"

        state_write = is_state_reuse and (i % 2 == 0)
        expect_state = "benchmark-state-42" if is_state_reuse and (i % 2 == 1) else None

        return _run_one_turn(
            provider=provider,
            provider_name=provider_name,
            scenario=scenario,
            workload_name=workload_name,
            command=command,
            iteration=i,
            concurrency=concurrency,
            user_id="bench-user",
            thread_id=tid,
            no_warmpool=no_warmpool,
            state_write_turn=state_write,
            expected_state=expect_state,
        )

    def _tid(i: int) -> str:
        if scenario == "cold_unique_thread":
            return f"cold-{i}"
        elif scenario == "warm_same_thread":
            return "warm-hit"
        elif scenario == "warm_miss_many_threads":
            return f"thread-{i % max(concurrency, 4)}"
        elif scenario in ("idle_timeout", "replica_pressure"):
            return f"warm-hit-{i % concurrency}"
        else:
            return f"default-{i}"

    def _inject_fault(i: int) -> None:
        if fault_inject_after is None or i != fault_inject_after:
            return
        tid = _tid(i)
        sandbox_id = _compute_sandbox_id(provider, tid, "bench-user")
        with provider._lock:
            warm_entry = provider._warm_pool.get(sandbox_id)
        if warm_entry is not None:
            box, _ = warm_entry
            try:
                box.close()
            except Exception:
                pass
            print(
                f"  [fault] killed warm-pool box {sandbox_id} after iteration {i}",
                file=sys.stderr,
            )
        else:
            print(
                f"  [fault] no warm-pool box {sandbox_id} to kill after iteration {i}",
                file=sys.stderr,
            )

    if concurrency == 1:
        for i in range(iterations):
            r = _run_one(i)
            results.append(r)
            _inject_fault(i)
    else:
        sem = threading.BoundedSemaphore(concurrency)

        def _guarded(i: int) -> BenchResult:
            with sem:
                return _run_one(i)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_guarded, i): i for i in range(iterations)}
            for future in as_completed(futures):
                i = futures[future]
                results.append(future.result())
                _inject_fault(i)

    # Annotate with config
    for r in results:
        r.replicas = config_used.get("replicas")
        r.idle_timeout = config_used.get("idle_timeout")
        r.health_check_skip_seconds = config_used.get("health_check_skip_seconds")
        r.image = config_used.get("image")

    # Write JSONL
    with output_path.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

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
    if args.workload == "state_reuse" and (args.scenario != "warm_same_thread" or args.concurrency != 1):
        raise SystemExit("state_reuse requires --scenario warm_same_thread --concurrency 1")

    output_path = Path(args.output)

    config: dict[str, Any] = {
        "replicas": args.replicas,
        "idle_timeout": args.idle_timeout,
        "health_check_skip_seconds": args.health_check_skip_seconds,
        "image": args.image,
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
                _run_one_turn(
                    provider=provider,
                    provider_name=args.provider,
                    scenario="warmup",
                    workload_name="noop",
                    command="true",
                    iteration=-(args.warmup_iterations - i),
                    concurrency=1,
                    user_id="bench-user",
                    thread_id="warmup",
                    no_warmpool=args.no_warmpool,
                )

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
        )

        _print_summary(results, args)

    finally:
        provider.shutdown()

    return 0


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
    idle = min(args.idle_timeout, 10)
    print(
        f"Idle timeout scenario: acquire, release, force-reap after {idle + 1}s sleep (timeout={idle}s)",
        file=sys.stderr,
    )

    results: list[BenchResult] = []
    for i in range(min(args.iterations, 20)):
        tid = f"idle-{i}"
        r1 = _run_one_turn(
            provider,
            args.provider,
            "idle_timeout",
            args.workload,
            WORKLOADS.get(args.workload, "true"),
            i * 2,
            args.concurrency,
            "bench-user",
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
            "bench-user",
            tid,
            args.no_warmpool,
        )
        if r2.warm_hit:
            print(
                f"  WARNING: turn {i * 2 + 1} was a warm hit — reaping may not have removed the entry",
                file=sys.stderr,
            )
        results.append(r2)

    for r in results:
        r.replicas = config_used.get("replicas")
        r.idle_timeout = config_used.get("idle_timeout")
        r.image = config_used.get("image")

    with output_path.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    _print_summary(results, args)
    return 0


def _run_replica_pressure_scenario(
    provider: Any,
    args: argparse.Namespace,
    output_path: Path,
    config_used: dict[str, Any],
) -> int:
    """Push past replicas limit to verify eviction behaviour."""
    replicas = args.replicas
    overcommit = replicas * 2

    print(
        f"Replica pressure: replicas={replicas}, overcommitting to {overcommit} unique threads, {args.iterations} rounds",
        file=sys.stderr,
    )

    results: list[BenchResult] = []
    for i in range(args.iterations):
        tid = f"pressure-{i % overcommit}"
        r = _run_one_turn(
            provider,
            args.provider,
            "replica_pressure",
            args.workload,
            WORKLOADS.get(args.workload, "true"),
            i,
            args.concurrency,
            "bench-user",
            tid,
            args.no_warmpool,
        )

        # Track warm pool evictions
        with provider._lock:
            warm_size = len(provider._warm_pool)
            active_size = len(provider._boxes)
        print(
            f"  iter {i}: warm_pool={warm_size} active={active_size} warm_hit={r.warm_hit}",
            file=sys.stderr,
        )

        results.append(r)

    for r in results:
        r.replicas = config_used.get("replicas")
        r.idle_timeout = config_used.get("idle_timeout")
        r.image = config_used.get("image")

    with output_path.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    _print_summary(results, args)
    return 0


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

    def _p(arr: list[float], pct: float) -> float:
        if not arr:
            return 0.0
        idx = max(0, min(len(arr) - 1, int(len(arr) * pct / 100)))
        return sorted(arr)[idx]

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
