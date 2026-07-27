#!/usr/bin/env python3
"""Production-shaped full/delta checkpoint benchmark.

Measures user-visible run, state, and history latency on the production path:
the real lead-agent graph (scripted deterministic model), a real
AsyncSqliteSaver, and the real Gateway route stack for reads. Every case runs
in a fresh child process with a fresh database, mirroring the
restart-required checkpoint mode boundary.

Examples::

    PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_production.py \
        --turns 100,1000 --payload-bytes 128 \
        --snapshot-frequencies 10,100,1000 \
        --repetitions 7 --output production-bench.jsonl

    PYTHONPATH=. uv run python scripts/benchmark/checkpoint/summarize_production.py \
        production-bench.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint_bench_common as common  # noqa: E402

Mode = Literal["full", "delta"]

SCHEMA_VERSION = 1
BENCHMARK_VERSION = 1
BENCHMARK_NAME = "checkpoint_production"
DEFAULT_HISTORY_LIMITS = (10, 50, 200)
DEFAULT_READ_REPETITIONS = 25
WARMUP_TURNS = 2
_MODES: tuple[Mode, ...] = ("full", "delta")


@dataclass(frozen=True)
class ProductionCase:
    mode: Mode
    turns: int
    payload_bytes: int
    snapshot_frequency: int | None
    history_limits: tuple[int, ...]
    read_repetitions: int
    repetition: int
    seed: int

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"unsupported mode: {self.mode!r}")
        if self.turns <= WARMUP_TURNS:
            raise ValueError(f"turns must exceed the {WARMUP_TURNS}-turn warm-up")
        if self.payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        if self.mode == "full" and self.snapshot_frequency is not None:
            raise ValueError("snapshot_frequency is a delta-only axis")
        if self.mode == "delta" and (self.snapshot_frequency is None or self.snapshot_frequency <= 0):
            raise ValueError("delta mode requires a positive snapshot_frequency")
        if not self.history_limits or any(limit <= 0 for limit in self.history_limits):
            raise ValueError("history_limits must be positive")
        if self.read_repetitions <= 0:
            raise ValueError("read_repetitions must be positive")
        if self.repetition < 0:
            raise ValueError("repetition must be non-negative")


def expand_cases(
    *,
    modes: list[str],
    turn_counts: list[int],
    payload_bytes: list[int],
    snapshot_frequencies: list[int],
    repetitions: int,
    seed: int = 1,
    history_limits: tuple[int, ...] = DEFAULT_HISTORY_LIMITS,
    read_repetitions: int = DEFAULT_READ_REPETITIONS,
) -> list[ProductionCase]:
    """Build the matrix with alternating mode order to reduce order bias."""
    cases: list[ProductionCase] = []
    group_index = 0
    for repetition in range(repetitions):
        for payload in payload_bytes:
            for turns in turn_counts:
                ordered_modes = list(modes)
                if group_index % 2 == 1:
                    ordered_modes.reverse()
                for mode in ordered_modes:
                    frequencies: list[int | None] = snapshot_frequencies if mode == "delta" else [None]
                    for frequency in frequencies:
                        cases.append(
                            ProductionCase(
                                mode=mode,  # type: ignore[arg-type]
                                turns=turns,
                                payload_bytes=payload,
                                snapshot_frequency=frequency,
                                history_limits=history_limits,
                                read_repetitions=read_repetitions,
                                repetition=repetition,
                                seed=seed,
                            )
                        )
                group_index += 1
    return cases


def _base_row(case: ProductionCase) -> dict:
    import importlib.metadata
    import os
    import platform

    git_sha = os.environ.get(common.GIT_SHA_ENV) or common.resolve_git_sha()
    try:
        langgraph_version = importlib.metadata.version("langgraph")
    except importlib.metadata.PackageNotFoundError:
        langgraph_version = "unknown"
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark": BENCHMARK_NAME,
        "success": True,
        "error": None,
        "profiled": False,
        "git_sha": git_sha,
        "python_version": platform.python_version(),
        "langgraph_version": langgraph_version,
        "platform": platform.platform(),
        "mode": case.mode,
        "snapshot_frequency": case.snapshot_frequency,
        "turns": case.turns,
        "payload_bytes": case.payload_bytes,
        "history_limits": list(case.history_limits),
        "read_repetitions": case.read_repetitions,
        "repetition": case.repetition,
        "seed": case.seed,
    }


def _failure_row(case: ProductionCase, error: str) -> dict:
    row = _base_row(case)
    row["success"] = False
    row["error"] = common.safe_error(error)
    return row


def _comparison_key(row: dict) -> tuple:
    # snapshot_frequency is intentionally excluded: every delta frequency
    # pairs against the same full row, and all frequencies must agree on
    # the materialized digests.
    return (row.get("turns"), row.get("payload_bytes"), row.get("repetition"))


def validate_cross_mode_rows(rows: list[dict]) -> None:
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault(_comparison_key(row), []).append(row)
    for group in grouped.values():
        successful = [row for row in group if row.get("success")]
        modes = {row.get("mode") for row in successful}
        if not {"full", "delta"}.issubset(modes):
            continue
        signatures = {(row.get("message_count"), row.get("seed_content_sha256"), row.get("state_wire_sha256"), row.get("history_wire_sha256")) for row in successful}
        if len(signatures) == 1:
            continue
        for row in successful:
            row["success"] = False
            row["error"] = "cross-mode materialized state mismatch"


def _profile_filename(case: ProductionCase) -> str:
    return f"production-{case.mode}-turns-{case.turns}-payload-{case.payload_bytes}-freq-{case.snapshot_frequency}-rep-{case.repetition}.prof"


def _worker_main(encoded_case: str, *, profile_path: Path | None = None) -> int:
    try:
        raw = json.loads(encoded_case)
        history_limits = raw.get("history_limits")
        if history_limits is not None:
            raw["history_limits"] = tuple(history_limits)
        case = ProductionCase(**raw)
    except (TypeError, ValueError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "benchmark_version": BENCHMARK_VERSION, "benchmark": BENCHMARK_NAME, "success": False, "error": common.safe_error(exc)}, separators=(",", ":")))
        return 2
    with tempfile.TemporaryDirectory(prefix="deerflow-checkpoint-production-") as temp_dir:
        if profile_path is None:
            row = _run_case(case, work_dir=Path(temp_dir))
        else:
            row = common.run_profiled(_run_case, case, work_dir=Path(temp_dir), profile_path=profile_path)
    print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    return 0 if row.get("success") else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Production-shaped full/delta checkpoint benchmark")
    parser.add_argument("--modes", default="full,delta")
    parser.add_argument("--turns", default="10,100,500,1000,2000")
    parser.add_argument("--payload-bytes", default="128")
    parser.add_argument("--snapshot-frequencies", default="10,50,100,500,1000")
    parser.add_argument("--history-limits", default=",".join(str(v) for v in DEFAULT_HISTORY_LIMITS))
    parser.add_argument("--read-repetitions", type=int, default=DEFAULT_READ_REPETITIONS)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-case", help=argparse.SUPPRESS)
    parser.add_argument("--worker-profile", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.worker_case is not None:
        return _worker_main(args.worker_case, profile_path=args.worker_profile)
    if args.output is None:
        parser.error("--output is required")
    try:
        modes = common.parse_choice_csv(args.modes, option="--modes", choices=_MODES)
        turn_counts = common.parse_positive_int_csv(args.turns, option="--turns")
        payload_bytes = common.parse_positive_int_csv(args.payload_bytes, option="--payload-bytes")
        frequencies = common.parse_positive_int_csv(args.snapshot_frequencies, option="--snapshot-frequencies")
        history_limits = tuple(common.parse_positive_int_csv(args.history_limits, option="--history-limits"))
        if args.repetitions <= 0 or args.read_repetitions <= 0 or args.timeout_seconds <= 0:
            raise ValueError("repetition and timeout values must be positive")
    except ValueError as exc:
        parser.error(str(exc))

    cases = expand_cases(
        modes=modes,
        turn_counts=turn_counts,
        payload_bytes=payload_bytes,
        snapshot_frequencies=frequencies,
        repetitions=args.repetitions,
        seed=args.seed,
        history_limits=history_limits,
        read_repetitions=args.read_repetitions,
    )
    git_sha = common.resolve_git_sha()
    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] {case.mode} turns={case.turns} payload={case.payload_bytes} freq={case.snapshot_frequency} repetition={case.repetition}",
            file=sys.stderr,
        )
        worker_args = ["--worker-case", json.dumps(asdict(case), separators=(",", ":"))]
        if args.profile_dir is not None:
            worker_args.extend(["--worker-profile", str(args.profile_dir / _profile_filename(case))])
        rows.append(
            common.run_child_case(
                script=Path(__file__).resolve(),
                worker_args=worker_args,
                failure_row=lambda error, c=case: _failure_row(c, error),
                timeout_seconds=args.timeout_seconds,
                git_sha=git_sha,
            )
        )
    validate_cross_mode_rows(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    failures = sum(1 for row in rows if not row.get("success"))
    print(f"Wrote {len(rows)} result row(s) to {args.output}; failures={failures}", file=sys.stderr)
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Worker: production-shaped run + read phases (single event loop)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import hashlib  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httpx  # noqa: E402
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402


class _ScriptedBenchModel(FakeMessagesListChatModel):
    """Deterministic model: call k returns a fixed-size AIMessage.

    Content and IDs depend only on the call index, so full and delta modes
    produce byte-identical message streams. Serves the ainvoke path via
    BaseChatModel's default ``_agenerate`` fallback (``run_in_executor`` over
    ``_generate``); streaming is not supported.
    """

    def __init__(self, *, payload_bytes: int) -> None:
        super().__init__(responses=[])
        self._bench_payload_bytes = payload_bytes
        self._bench_call_index = 0

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        index = self._bench_call_index
        self._bench_call_index += 1
        message = AIMessage(id=f"bench-ai-{index:08d}", content="x" * self._bench_payload_bytes)
        return ChatResult(generations=[ChatGeneration(message=message)])


class _TimingSaver:
    """Delegating saver wrapper recording write timing.

    LangGraph issues ``aput``/``aput_writes`` as concurrent asyncio tasks, so
    per-call latencies overlap (queueing on the single sqlite connection is
    counted in every concurrent call). Summing them double-counts and can
    exceed the turn wall clock. ``intervals`` keeps absolute (start, end) per
    call so the run phase can compute the merged busy time — the honest,
    wall-bounded write cost. ``timings_ms`` remains the cumulative-per-method
    ledger used for read-path attribution.
    """

    def __init__(self, saver: Any) -> None:
        self._saver = saver
        self.timings_ms: dict[str, float] = defaultdict(float)
        self.intervals: list[tuple[str, float, float]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._saver, name)

    async def _timed(self, label: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return await fn(*args, **kwargs)
        finally:
            end = time.perf_counter()
            self.timings_ms[label] += (end - start) * 1000
            self.intervals.append((label, start * 1000, end * 1000))

    async def aput(self, *args: Any, **kwargs: Any) -> Any:
        return await self._timed("aput", self._saver.aput, *args, **kwargs)

    async def aput_writes(self, *args: Any, **kwargs: Any) -> Any:
        return await self._timed("aput_writes", self._saver.aput_writes, *args, **kwargs)

    async def aget_tuple(self, *args: Any, **kwargs: Any) -> Any:
        return await self._timed("aget_tuple", self._saver.aget_tuple, *args, **kwargs)

    def alist(self, *args: Any, **kwargs: Any) -> Any:
        # alist is an async generator on real savers; wrap it to time the
        # full iteration when consumed.
        agen = self._saver.alist(*args, **kwargs)
        timing = self.timings_ms

        async def _wrapped() -> Any:
            start_total = time.perf_counter()
            try:
                async for item in agen:
                    yield item
            finally:
                timing["alist"] += (time.perf_counter() - start_total) * 1000

        return _wrapped()


def _thread_id(case: ProductionCase) -> str:
    return f"checkpoint-production-{case.seed}-{case.repetition}"


async def _run_phase(case: ProductionCase, saver: Any, timing: _TimingSaver, work_dir: Path) -> dict[str, Any]:
    """Seed the thread through the real lead-agent graph; measure per-turn latency."""
    from deerflow.agents.lead_agent.agent import make_lead_agent
    from deerflow.config.app_config import AppConfig, set_app_config
    from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode

    app_config = AppConfig.model_validate(
        {
            # Mirrors tests/test_lead_agent_model_resolution.py::_make_model:
            # `use` is a required ModelConfig field, so a provider/api_key
            # style entry does not validate.
            "models": [
                {
                    "name": "bench-model",
                    "display_name": "bench-model",
                    "description": None,
                    "use": "langchain_openai:ChatOpenAI",
                    "model": "bench",
                    "supports_thinking": False,
                    "supports_vision": False,
                }
            ],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            # Title and memory middleware would fire background LLM calls and
            # debounce timers; both pollute per-turn latency, so disable them.
            "title": {"enabled": False},
            "memory": {"enabled": False},
            "database": {
                "backend": "sqlite",
                "sqlite_dir": str(work_dir),
                "checkpoint_channel_mode": case.mode,
                "checkpoint_delta_snapshot_frequency": case.snapshot_frequency or 1000,
            },
        }
    )
    set_app_config(app_config)

    model = _ScriptedBenchModel(payload_bytes=case.payload_bytes)

    def _fake_create_chat_model(**kwargs: Any) -> Any:
        return model

    with patch("deerflow.agents.lead_agent.agent.create_chat_model", _fake_create_chat_model):
        graph = make_lead_agent({"configurable": {}})
    # Attach the timed saver post-construction, mirroring the run worker
    # (deerflow.runs.worker assigns ``agent.checkpointer`` the same way), so
    # every checkpoint write flows through ``timing``.
    graph.checkpointer = timing

    config: dict[str, Any] = {"configurable": {"thread_id": _thread_id(case)}}
    inject_checkpoint_mode(config, case.mode)

    turn_ms: list[float] = []
    write_ms: list[float] = []
    write_methods = {"aput", "aput_writes"}
    for turn in range(case.turns):
        intervals_before = len(timing.intervals)
        start = time.perf_counter()
        await graph.ainvoke(
            {"messages": [HumanMessage(id=f"bench-h-{turn:08d}", content="y" * case.payload_bytes)]},
            config,
        )
        turn_ms.append((time.perf_counter() - start) * 1000)
        write_ms.append(_merged_busy_ms(iv for iv in timing.intervals[intervals_before:] if iv[0] in write_methods))

    return {"graph": graph, "config": config, "turn_ms": turn_ms[WARMUP_TURNS:], "write_ms": write_ms[WARMUP_TURNS:]}


def _merged_busy_ms(intervals: Any) -> float:
    """Union of (start, end) write intervals in ms — wall-bounded write cost.

    Concurrent write tasks overlap; merging their intervals yields the time
    the event loop was actually inside aput/aput_writes, which cannot exceed
    the turn wall clock the way a naive latency sum does.
    """
    merged: list[list[float]] = []
    for _label, start, end in sorted(intervals, key=lambda iv: iv[1]):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


# ``ThreadHistoryRequest.limit`` is validated with ``le=100``: the production
# route cannot serve a larger page. Configured history limits above the cap
# are measured at the cap and labelled by the *effective* limit so no metric
# field ever claims a request the API would reject.
_HISTORY_ROUTE_MAX_LIMIT = 100


def _wire_messages_digest(messages: Any) -> str:
    """Digest wire-format messages, excluding volatile checkpoint ids/timestamps."""
    canonical = [[message.get("type"), message.get("id"), message.get("content") if isinstance(message.get("content"), str) else json.dumps(message.get("content"), sort_keys=True)] for message in messages or []]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _combined_digest(digests: list[str]) -> str:
    return hashlib.sha256("".join(digests).encode("utf-8")).hexdigest()


def _make_gateway_app(saver: Any, mode: str, store: Any) -> Any:
    """Minimal authed gateway app, mirroring tests/_router_auth_helpers.py.

    Reimplemented inline: benchmark scripts must not import from tests/.
    """
    from unittest.mock import MagicMock
    from uuid import uuid4

    from fastapi import FastAPI, Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware

    from app.gateway.auth.models import User
    from app.gateway.authz import AuthContext, Permissions
    from app.gateway.routers import threads
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    permissions = [Permissions.THREADS_READ, Permissions.THREADS_WRITE, Permissions.THREADS_DELETE]

    class _StubAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            user = User(email="bench@example.com", password_hash="x", system_role="user", id=uuid4())
            request.state.user = user
            request.state.auth = AuthContext(user=user, permissions=list(permissions))
            # Mirror the production AuthMiddleware: the user contextvar must be
            # set or thread-meta lookups hit user_id=AUTO and raise per request.
            token = set_current_user(user)
            try:
                return await call_next(request)
            finally:
                reset_current_user(token)

    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware)
    app.state.store = store
    app.state.checkpointer = saver
    app.state.thread_store = MemoryThreadMetaStore(store)
    app.state.checkpoint_channel_mode = mode
    app.state.run_event_store = MagicMock()
    app.include_router(threads.router)
    return app


async def _read_phase(case: ProductionCase, saver: Any, timing: _TimingSaver) -> dict[str, Any]:
    """Measure state/history endpoint latency through the real route stack.

    Runs in the same event loop as the run phase (the AsyncSqliteSaver is
    bound to its creating loop), driving the real threads router over an
    ASGI transport. ``saver`` must be the RAW saver, not the timing
    wrapper: ``Pregel.aget_state`` gates delta replay behind
    ``isinstance(self.checkpointer, BaseCheckpointSaver)``
    (langgraph/pregel/main.py), so the duck-typed ``_TimingSaver``
    silently materializes delta channels as empty. The wrapper therefore
    stays on the run phase only and the row records
    ``saver_read_attribution: False``; the ``*_saver_ms`` fields remain in
    the schema but report 0.0.
    """
    from langgraph.store.memory import InMemoryStore

    from app.gateway import services as gateway_services

    store = InMemoryStore()
    app = _make_gateway_app(saver, case.mode, store)

    graph_build_ms: list[float] = []
    original_resolve = gateway_services.resolve_agent_factory
    real_factory = original_resolve(None)

    def _timed_factory(config: Any = None) -> Any:
        start = time.perf_counter()
        graph = real_factory(config)
        graph_build_ms.append((time.perf_counter() - start) * 1000)
        return graph

    # The accessor graph cache is keyed (assistant_id, mode); the factory
    # identity check compares the callable, so one stable wrapper instance.
    gateway_services.resolve_agent_factory = lambda assistant_id=None: _timed_factory

    # The accessor graph is compiled lazily inside the first request and
    # rebuilds the lead agent, so the scripted model must be patched in for
    # the whole read phase, exactly as in _run_phase.
    model = _ScriptedBenchModel(payload_bytes=case.payload_bytes)

    def _fake_create_chat_model(**kwargs: Any) -> Any:
        return model

    thread_id = _thread_id(case)
    transport = httpx.ASGITransport(app=app)
    result: dict[str, Any] = {}
    try:
        with patch("deerflow.agents.lead_agent.agent.create_chat_model", _fake_create_chat_model):
            async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:

                async def _timed_request(label: str, method: str, url: str, **kwargs: Any) -> tuple[Any, float, float]:
                    del label  # timing only; labels aid debugging failures
                    saver_before = timing.timings_ms["aget_tuple"] + timing.timings_ms["alist"]
                    start = time.perf_counter()
                    response = await client.request(method, url, **kwargs)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    # The read phase drives the RAW saver (see docstring), so
                    # the timing wrapper never advances here: saver_ms — and
                    # thus every read-path *_saver_ms field — is structurally 0.0.
                    saver_ms = timing.timings_ms["aget_tuple"] + timing.timings_ms["alist"] - saver_before
                    response.raise_for_status()
                    return response, elapsed_ms, saver_ms

                # --- state endpoint: one cold sample after clearing the accessor cache
                gateway_services._state_accessor_graph_cache.clear()
                graph_build_ms.clear()
                response, state_cold_ms, state_cold_saver_ms = await _timed_request("state-cold", "GET", f"/api/threads/{thread_id}/state")
                # Cold/warm contract, asserted structurally: the cold request
                # MUST build the accessor graph exactly once (otherwise the
                # cold sample did not exercise the cold path), and warm
                # requests MUST NOT build again (otherwise the cache is not
                # hit and warm samples silently measure the cold path).
                if len(graph_build_ms) != 1:
                    raise AssertionError(f"state cold read triggered {len(graph_build_ms)} accessor graph builds; expected exactly 1")
                cold_graph_build_ms = graph_build_ms[0]
                state_payload = response.json()
                state_digest = _wire_messages_digest((state_payload.get("values") or {}).get("messages"))

                state_warm: list[float] = []
                for _ in range(case.read_repetitions):
                    _response, elapsed_ms, _saver_ms = await _timed_request("state-warm", "GET", f"/api/threads/{thread_id}/state")
                    state_warm.append(elapsed_ms)
                if len(graph_build_ms) != 1:
                    raise AssertionError("state warm reads triggered an accessor graph rebuild; cache was not hit")

                # --- history endpoint per limit, same cold/warm split
                history_metrics: dict[str, Any] = {}
                history_digests: list[str] = []
                effective_limits = list(dict.fromkeys(min(limit, _HISTORY_ROUTE_MAX_LIMIT) for limit in case.history_limits))
                for limit_index, limit in enumerate(effective_limits):
                    gateway_services._state_accessor_graph_cache.clear()
                    response, cold_ms, cold_saver_ms = await _timed_request(
                        f"history-cold-{limit}",
                        "POST",
                        f"/api/threads/{thread_id}/history",
                        json={"limit": limit},
                    )
                    expected_builds = 2 + limit_index
                    if len(graph_build_ms) != expected_builds:
                        raise AssertionError(f"history cold read (limit={limit}) triggered {len(graph_build_ms)} total accessor graph builds; expected {expected_builds}")
                    entries = response.json()
                    digest_source: list[Any] = []
                    for entry in entries:
                        digest_source.extend((entry.get("values") or {}).get("messages") or [])
                    history_digests.append(_wire_messages_digest(digest_source))
                    warm: list[float] = []
                    for _ in range(case.read_repetitions):
                        _r, elapsed_ms, _s = await _timed_request(
                            f"history-warm-{limit}",
                            "POST",
                            f"/api/threads/{thread_id}/history",
                            json={"limit": limit},
                        )
                        warm.append(elapsed_ms)
                    if len(graph_build_ms) != expected_builds:
                        raise AssertionError(f"history warm reads (limit={limit}) triggered an accessor graph rebuild; cache was not hit")
                    history_metrics[f"history_limit_{limit}_cold_ms"] = cold_ms
                    history_metrics[f"history_limit_{limit}_cold_saver_ms"] = cold_saver_ms
                    history_metrics[f"history_limit_{limit}_warm_p50_ms"] = common.percentile(warm, 50)
                    history_metrics[f"history_limit_{limit}_warm_p95_ms"] = common.percentile(warm, 95)

                result.update(
                    {
                        "state_cold_ms": state_cold_ms,
                        "state_cold_saver_ms": state_cold_saver_ms,
                        "state_cold_graph_build_ms": cold_graph_build_ms,
                        "state_warm_p50_ms": common.percentile(state_warm, 50),
                        "state_warm_p95_ms": common.percentile(state_warm, 95),
                        "state_wire_sha256": state_digest,
                        "history_wire_sha256": _combined_digest(history_digests),
                        "saver_read_attribution": False,
                        **history_metrics,
                    }
                )
    finally:
        gateway_services.resolve_agent_factory = original_resolve
    return result


def _storage_file_stats(db_path: Path) -> dict[str, Any]:
    return {
        "db_bytes": common.file_size(db_path),
        "wal_bytes": common.file_size(Path(f"{db_path}-wal")),
        "shm_bytes": common.file_size(Path(f"{db_path}-shm")),
    }


def _run_case(case: ProductionCase, *, work_dir: Path) -> dict:
    """Run one benchmark case: run phase + read phase in a single event loop."""
    row = _base_row(case)
    db_path = work_dir / "production-benchmark.sqlite"

    async def _async_body() -> dict[str, Any]:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
            await saver.setup()
            timing = _TimingSaver(saver)
            run_info = await _run_phase(case, saver, timing, work_dir)

            # Seed correctness: materialize through the mode-matched accessor.
            from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

            accessor = CheckpointStateAccessor.bind(run_info["graph"], saver, mode=case.mode)
            snapshot = await accessor.aget(run_info["config"])
            messages = list(snapshot.values.get("messages", []))
            seed_digest = common.canonical_messages_digest(messages)

            read_metrics = await _read_phase(case, saver, timing)
            storage_metrics = _storage_file_stats(db_path)

        metrics = {
            "run_turn_p50_ms": common.percentile(run_info["turn_ms"], 50),
            "run_turn_p95_ms": common.percentile(run_info["turn_ms"], 95),
            "checkpoint_write_p50_ms": common.percentile(run_info["write_ms"], 50),
            "checkpoint_write_p95_ms": common.percentile(run_info["write_ms"], 95),
            "checkpoint_write_p99_ms": common.percentile(run_info["write_ms"], 99),
            "message_count": len(messages),
            "seed_content_sha256": seed_digest,
            "peak_rss_bytes": common.peak_rss_bytes(),
            **storage_metrics,
            **read_metrics,
        }
        return metrics

    try:
        row.update(asyncio.run(_async_body()))
    except Exception as exc:
        row["success"] = False
        row["error"] = common.safe_error(exc, work_dir=work_dir)
    return row


if __name__ == "__main__":
    raise SystemExit(main())
