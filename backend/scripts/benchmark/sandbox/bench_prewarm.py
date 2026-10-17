"""Opt-in AIO prewarm A/B through a real agent graph and deterministic model.

Run from backend with an explicit isolated DEER_FLOW_CONFIG_PATH/DEER_FLOW_HOME:
python -m scripts.benchmark.sandbox.bench_prewarm --output prewarm.jsonl

No paid model calls. The graph uses production thread/sandbox middleware, bash
tool, authorization and execution-lease cleanup. This measures that bounded
agent path, not HTTP/SSE latency or live-model behavior. Cases start with fresh
thread identities; exact acquired resources are destroyed between batches.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import json
import math
import random
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config import get_app_config
from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.lease import get_sandbox_lease_manager, register_sandbox_prewarm_cleanup, release_sandbox_execution_lease_async, sandbox_lease_owner
from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.sandbox_provider import set_sandbox_provider, shutdown_sandbox_provider
from scripts.benchmark.sandbox.bench_provider import _evict_from_warm, _make_aio_provider, _pool_counts
from scripts.benchmark.sandbox.resources import DockerResourceSampler

COMMAND_MARKER = "deerflow-bench-command-ok"
COMMAND = f"python -c \"print('{COMMAND_MARKER}')\""
PROMPTS = {
    "tool": f"Run this command:\n```sh\n{COMMAND}\n```",
    "plain": "Explain why the sky is blue. Do not run any tools.",
    "fenced_no_tool": "Explain this example without running it:\n```python\nprint(42)\n```",
    "model_error": "Run this example:\n```python\nprint(42)\n```",
    "cancel": f"Run this command:\n```sh\n{COMMAND}\n```",
}


@dataclass
class Trace:
    started: float = field(default_factory=time.monotonic)
    timestamps: dict[str, float] = field(default_factory=dict)
    acquisitions: list[dict[str, Any]] = field(default_factory=list)
    releases: list[str] = field(default_factory=list)
    sandbox_ids: set[str] = field(default_factory=set)
    model_started: asyncio.Event = field(default_factory=asyncio.Event)
    acquire_started: asyncio.Event = field(default_factory=asyncio.Event)
    acquire_ready: asyncio.Event = field(default_factory=asyncio.Event)
    tool_requested: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: asyncio.Event = field(default_factory=asyncio.Event)
    tool_sandbox_id: str | None = None
    cleanup_error_type: str | None = None
    lifecycle_samples: list[dict[str, Any]] = field(default_factory=list)

    def mark(self, name: str) -> None:
        self.timestamps.setdefault(name, time.monotonic())
        event = getattr(self, name, None)
        if isinstance(event, asyncio.Event):
            event.set()


_TRACE: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("benchmark_trace", default=None)


@contextmanager
def observe_provider(provider):
    """Observation-only wrappers in this standalone process; restore on exit."""
    acquire, release, initialize = provider.acquire_async, provider.release, sandbox_tools.ensure_sandbox_initialized_async

    def sample(trace, event):
        active, warm = _pool_counts(provider)
        trace.lifecycle_samples.append({"event": event, "monotonic_s": time.monotonic(), "active": active, "warm": warm})

    async def timed_acquire(*args, **kwargs):
        trace = _TRACE.get()
        if trace is None:
            return await acquire(*args, **kwargs)
        trace.mark("acquire_started")
        entry = {"started": time.monotonic(), "sandbox_id": None}
        trace.acquisitions.append(entry)
        try:
            sid = await acquire(*args, **kwargs)
            entry.update(ready=time.monotonic(), sandbox_id=sid)
            trace.sandbox_ids.add(sid)
            trace.mark("acquire_ready")
            sample(trace, "acquire_ready")
            return sid
        finally:
            entry["finished"] = time.monotonic()

    def timed_release(sid):
        result = release(sid)
        if (trace := _TRACE.get()) is not None:
            trace.sandbox_ids.add(sid)
            trace.releases.append(sid)
            trace.timestamps["released"] = time.monotonic()
            sample(trace, "released")
        return result

    async def timed_initialize(runtime=None):
        trace = _TRACE.get()
        if trace is not None:
            trace.mark("tool_requested")
        sandbox = await initialize(runtime)
        if trace is not None:
            trace.mark("tool_ready")
            trace.tool_sandbox_id = sandbox.id
        return sandbox

    provider.acquire_async, provider.release = timed_acquire, timed_release
    sandbox_tools.ensure_sandbox_initialized_async = timed_initialize
    try:
        yield
    finally:
        provider.acquire_async, provider.release = acquire, release
        sandbox_tools.ensure_sandbox_initialized_async = initialize


class ScriptedModel(BaseChatModel):
    """Exactly one predetermined bash request, or a predetermined terminal case."""

    trace: Any = Field(exclude=True)
    case: str
    delay: float
    gate: Any = Field(default=None, exclude=True)

    @property
    def _llm_type(self):
        return "offline-sandbox-benchmark"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError("benchmark must use the asynchronous model path")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content="Finished the fixed command.")
        else:
            self.trace.mark("model_started")
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(self.delay)
            self.trace.mark("model_first_response")
            if self.case == "model_error":
                raise RuntimeError("scripted model failure")
            answer = AIMessage(content="Fixed explanation; no tools required.")
            if self.case in ("tool", "cancel"):
                answer = AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": COMMAND, "description": "Deterministic benchmark command"}, "id": "bench-command", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def run_case(provider, app_config, *, case: str, prewarm: bool, model_delay: float, thread_id: str, user_id: str, trace: Trace | None = None, model_gate=None) -> dict[str, Any]:
    """Run the real graph; even errors/cancellation use the runtime's final fence."""
    if case not in PROMPTS:
        raise ValueError(f"Unknown benchmark case: {case}")
    trace = trace or Trace()
    config = app_config.model_copy(deep=True)
    config.sandbox.prewarm = prewarm
    context = {"thread_id": thread_id, "user_id": user_id, "app_config": config}
    model = ScriptedModel(trace=trace, case=case, delay=model_delay, gate=model_gate)
    graph = create_agent(model, tools=[sandbox_tools.bash_tool], middleware=[ThreadDataMiddleware(), SandboxMiddleware()], state_schema=ThreadState)
    output = None
    outcome = "completed"
    error = None

    async def invoke():
        token = _TRACE.set(trace)
        try:
            register_sandbox_prewarm_cleanup(context)
            return await graph.ainvoke({"messages": [HumanMessage(content=PROMPTS[case])]}, context=context, config={"configurable": {"thread_id": thread_id}, "recursion_limit": 10})
        finally:
            trace.mark("cleanup_started")
            try:
                await release_sandbox_execution_lease_async(context)
            except BaseException as exc:
                trace.cleanup_error_type = type(exc).__name__
                raise
            finally:
                trace.mark("cleanup_finished")
                _TRACE.reset(token)

    task = asyncio.create_task(invoke())
    try:
        if case == "cancel":
            await asyncio.wait_for(trace.acquire_started.wait(), timeout=60)
            trace.mark("cancel_requested")
            task.cancel()
        output = await task
    except asyncio.CancelledError:
        outcome = "cancelled"
    except Exception as exc:
        outcome = "model_error" if case == "model_error" and str(exc) == "scripted model failure" else "failed"
        error = type(exc).__name__
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    tool_messages = [message for message in (output or {}).get("messages", []) if isinstance(message, ToolMessage)]
    tool_valid = len(tool_messages) == 1 and str(tool_messages[0].content).strip() == COMMAND_MARKER
    owner = sandbox_lease_owner(context)
    lease_remaining = owner is not None and get_sandbox_lease_manager(provider).binding_for(owner) is not None
    requested = trace.timestamps.get("tool_requested", float("inf"))
    speculative = [entry for entry in trace.acquisitions if entry["started"] < requested and entry["sandbox_id"] is not None]

    def duration(start: str, end: str) -> float | None:
        stamps = trace.timestamps
        return round((stamps[end] - stamps[start]) * 1000, 3) if start in stamps and end in stamps else None

    expected_outcome = {"cancel": "cancelled", "model_error": "model_error"}.get(case, "completed")
    success = outcome == expected_outcome and not lease_remaining and trace.cleanup_error_type is None and (tool_valid if case == "tool" else not tool_messages)
    active, warm = _pool_counts(provider)
    finished = time.monotonic()
    return {
        "record_type": "prewarm_case",
        "case": case,
        "prewarm": prewarm,
        "user_id": user_id,
        "thread_id": thread_id,
        "model_delay_seconds": model_delay,
        "outcome": outcome,
        "success": success,
        "error_type": error,
        "cleanup_error_type": trace.cleanup_error_type,
        "lifecycle_samples": trace.lifecycle_samples,
        "acquire_calls": len(trace.acquisitions),
        "sandbox_ids": sorted(trace.sandbox_ids),
        "release_calls": len(trace.releases),
        "prewarm_reused": bool(speculative and trace.tool_sandbox_id in {entry["sandbox_id"] for entry in speculative}),
        "unused_prewarm": bool(speculative and not trace.tool_requested.is_set()),
        "tool_output_valid": tool_valid,
        "lease_remaining": lease_remaining,
        "active_after_cleanup": active,
        "warm_after_cleanup": warm,
        "first_tool_wait_ms": duration("tool_requested", "tool_ready"),
        "cleanup_ms": duration("cleanup_started", "cleanup_finished"),
        "cancel_to_cleanup_ms": duration("cancel_requested", "cleanup_finished"),
        "elapsed_ms": round((finished - trace.started) * 1000, 3),
        "finished_utc": datetime.now(UTC).isoformat(),
        "started_monotonic_s": trace.started,
        "finished_monotonic_s": finished,
        "events_ms": {name: round((stamp - trace.started) * 1000, 3) for name, stamp in trace.timestamps.items()},
        "acquire_elapsed_ms": round(sum(entry["finished"] - entry["started"] for entry in trace.acquisitions) * 1000, 3),
        "unused_active_ms": duration("acquire_ready", "released") if speculative and not trace.tool_requested.is_set() else 0.0,
    }


async def run_matrix(provider, config, args, stream) -> bool:
    rng = random.Random(args.seed)
    success = True
    with observe_provider(provider):
        for case in args.cases:
            for delay in args.model_delays:
                for iteration in range(args.iterations):
                    variants = [False, True]
                    rng.shuffle(variants)
                    for prewarm in variants:
                        rows = await asyncio.gather(
                            *[run_case(provider, config, case=case, prewarm=prewarm, model_delay=delay, user_id=f"bench-user-{lane % args.users}", thread_id=f"{args.run_id}-{uuid.uuid4().hex[:12]}") for lane in range(args.concurrency)]
                        )
                        for row in rows:
                            row.update(iteration=iteration, concurrency=args.concurrency, users=args.users)
                            stream.write(json.dumps(row, allow_nan=False) + "\n")
                            stream.flush()
                            success = success and row["success"]
                        # Separate measurement from reset; only destroy IDs
                        # returned by this batch, after all execution holders drain.
                        sandbox_ids = sorted({sid for row in rows for sid in row["sandbox_ids"]})
                        reset_started = time.monotonic()
                        errors = []
                        for sid in sandbox_ids:
                            try:
                                await asyncio.to_thread(_evict_from_warm, provider, sid)
                            except Exception as exc:
                                errors.append({"sandbox_id": sid, "error_type": type(exc).__name__})
                        stream.write(
                            json.dumps(
                                {
                                    "record_type": "batch_cleanup",
                                    "case": case,
                                    "prewarm": prewarm,
                                    "model_delay_seconds": delay,
                                    "iteration": iteration,
                                    "sandbox_ids": sandbox_ids,
                                    "success": not errors,
                                    "errors": errors,
                                    "started_monotonic_s": reset_started,
                                    "finished_monotonic_s": time.monotonic(),
                                }
                            )
                            + "\n"
                        )
                        stream.flush()
                        if errors:
                            return False
    return success


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=list(PROMPTS), default=list(PROMPTS))
    parser.add_argument("--model-delays", nargs="+", type=float, default=[0, 1, 3])
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--users", type=int, default=1)
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--prewarm-max-concurrent", type=int, default=1)
    parser.add_argument("--seed", type=int, default=5002)
    parser.add_argument("--image")
    parser.add_argument("--resource-interval", type=float, default=1)
    args = parser.parse_args(argv)
    if min(args.iterations, args.concurrency, args.users, args.replicas, args.prewarm_max_concurrent) < 1 or any(not math.isfinite(delay) or delay < 0 for delay in args.model_delays):
        parser.error("counts must be positive and model delays finite/nonnegative")
    if not math.isfinite(args.resource_interval) or args.resource_interval <= 0:
        parser.error("resource interval must be finite and positive")
    args.run_id = uuid.uuid4().hex[:12]
    config = get_app_config().model_copy(deep=True)
    if not config.sandbox.use.endswith(":AioSandboxProvider"):
        parser.error("AIO prewarm comparison requires an AioSandboxProvider config; refusing a silently disabled treatment")
    config.sandbox.prewarm_max_concurrent = args.prewarm_max_concurrent
    prefix = f"deerflow-bench-{args.run_id}"
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, check=True).stdout
    patch = subprocess.run(["git", "diff", "HEAD", "--binary"], capture_output=True, check=True).stdout
    sampler = DockerResourceSampler(prefix + "-", args.output.with_suffix(".resources.jsonl"), interval=args.resource_interval)
    with args.output.open("x", encoding="utf-8") as stream:
        provider, effective = _make_aio_provider({"image": args.image, "container_prefix": prefix, "replicas": args.replicas, "idle_timeout": 600})
        set_sandbox_provider(provider)
        try:
            stream.write(
                json.dumps(
                    {
                        "record_type": "configuration",
                        "revision": revision,
                        "git_dirty": bool(status),
                        "tracked_patch_sha256": hashlib.sha256(patch).hexdigest(),
                        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "seed": args.seed,
                        "image": effective["image"],
                        "container_prefix": prefix,
                        "prewarm_max_concurrent": args.prewarm_max_concurrent,
                        "replicas": args.replicas,
                        "model": "scripted-no-paid-api",
                        "matrix": {key: getattr(args, key) for key in ("cases", "model_delays", "iterations", "concurrency", "users")},
                    }
                )
                + "\n"
            )
            sampler.start()
            sampler.wait_for_first_sample(timeout=10)
            success = asyncio.run(run_matrix(provider, config, args, stream))
        finally:
            try:
                shutdown_sandbox_provider()
            finally:
                sampler.stop()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
