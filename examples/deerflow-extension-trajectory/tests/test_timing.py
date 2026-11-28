"""Actual SDK streaming, parallel tool boundaries, durable evidence and policies."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from deerflow_extension_api import AgentBuildContext, AgentScope, ExtensionData
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
)
from deerflow.extensions.registry import LoadedExtensions
from deerflow.extensions.stack import compose_with_extensions
from deerflow_extension_trajectory.checkpoints import project
from deerflow_extension_trajectory.middleware import TimingContributor, TimingMiddleware
from deerflow_extension_trajectory.timing import KEY, TimingOptions, TimingRepository


@asynccontextmanager
async def mock_chat(transport, *, model="fixture", streaming=False):
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        yield ChatOpenAI(
            model=model,
            api_key="test",
            http_async_client=client,
            streaming=streaming,
            max_retries=0,
        )


def completion(content=None, *, calls=(), model="fixture"):
    """Build an OpenAI-compatible response for the offline SDK transport."""
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = list(calls)
    return httpx.Response(
        200,
        json={
            "id": "fixture-response",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if calls else "stop",
                }
            ],
        },
    )


def tool_call(name, call_id, **arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


async def run_turn(graph, *, anchor="u", config=None):
    return await graph.ainvoke(
        {"messages": [HumanMessage(id=anchor, content="test")]},
        config if config is not None else {"configurable": {"thread_id": "thread"}},
        context={"user_id": "alice", "thread_id": "thread", "run_id": "run"},
    )


def middlewares(repository, clock, scope=AgentScope.LEAD, *, retry=None):
    class ClockedTiming(TimingContributor):
        def contribute_middlewares(self, app_store, ctx):
            placements = super().contribute_middlewares(app_store, ctx)
            for placement in placements:
                if isinstance(placement.middleware, TimingMiddleware):
                    placement.middleware.clock = clock
            return placements

    ctx = AgentBuildContext(scope=scope, model_name="measured-model")
    extensions = LoadedExtensions(
        app_store=ExtensionData("test"),
        middleware_contributors=(("trajectory", ClockedTiming(repository)),),
        has_middleware_contributors=True,
    )
    host = [ToolErrorHandlingMiddleware()]
    if retry is not None:
        host.insert(0, retry)
    return compose_with_extensions(host, scope, ctx, extensions)


def test_policy_uses_measured_values_and_separates_slow_from_failure():
    policy = TimingOptions(
        {"slow_thresholds_ms": {"tool": 500, "tool:task": None, "model": 1000}}
    )
    record = {
        "operation": "tool",
        "name": "bash",
        "duration_ms": 600,
        "outcome": "completed",
    }
    assert policy.project(record)["is_slow"]
    assert policy.project({**record, "name": "task"})["is_slow"] is False
    assert (
        policy.project({**record, "duration_ms": 10, "outcome": "failed"})["is_slow"]
        is False
    )
    for invalid in [None, -1, float("nan"), float("inf"), True, "100"]:
        assert policy.project({**record, "duration_ms": invalid}) is None
    snapshot = SimpleNamespace(
        values={"messages": [HumanMessage(id="u", content="legacy")]},
        next=(),
        created_at="2026-01-01",
        config={},
    )
    assert "timing" not in project(snapshot)["messages"][0]
    for invalid in [-1, 0, True, "100", float("inf")]:
        with pytest.raises(ValueError):
            TimingOptions({"slow_thresholds_ms": {"tool": invalid}})


@pytest.mark.parametrize("mode,execution", [("full", None), ("delta", "child-E1")])
@pytest.mark.asyncio
async def test_complete_stream_is_measured_through_last_chunk_and_reopens(
    tmp_path, mode, execution
):
    clock = {"ns": 0}
    first, release = asyncio.Event(), asyncio.Event()
    repository = TimingRepository(tmp_path / "timings.sqlite")

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"id":"s1","object":"chat.completion.chunk","model":"test","choices":[{"index":0,"delta":{"role":"assistant","content":"hello "},"finish_reason":null}]}\n\n'
            first.set()
            await release.wait()
            yield b'data: {"id":"s1","object":"chat.completion.chunk","model":"test","choices":[{"index":0,"delta":{"content":"world"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

    def transport(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Stream()
        )

    async with mock_chat(transport, model="test", streaming=True) as model:
        async with AsyncSqliteSaver.from_conn_string(
            str(tmp_path / "checkpoints.sqlite")
        ) as saver:
            from deerflow.agents.thread_state import (
                get_thread_state_schema,
                normalize_middleware_state_schemas,
            )

            chain = normalize_middleware_state_schemas(
                middlewares(
                    repository,
                    lambda: clock["ns"],
                    AgentScope.SUBAGENT if execution else AgentScope.LEAD,
                ),
                mode,
            )
            graph = create_agent(
                model,
                middleware=chain,
                checkpointer=saver,
                state_schema=get_thread_state_schema(mode, 3),
            )
            config = {
                "configurable": {"thread_id": "thread"},
                "metadata": {"deerflow_subagent_execution_id": execution}
                if execution
                else {},
            }
            task = asyncio.create_task(run_turn(graph, config=config))
            await first.wait()
            assert not (tmp_path / "timings.sqlite").exists()
            clock["ns"] = 42_000_000
            release.set()
            result = await task
            message = result["messages"][-1]
            assert message.content == "hello world"
            saved = project(await graph.aget_state(config))
            assert saved["messages"][-1]["timing"]["duration_ms"] == 42
            rows = [
                {
                    "id": message.id,
                    "kind": "assistant",
                    "checkpoint_id": "c",
                    "timing": None,
                }
            ]
            reopened = TimingRepository(tmp_path / "timings.sqlite")
            enriched, warnings = await reopened.enrich(
                rows, "alice", "thread", execution
            )
            assert not warnings
            assert enriched[0]["timing"]["duration_ms"] == 42
            assert enriched[0]["timing"]["measurement"] == "logical_response"
            other, _ = await reopened.enrich(
                [{**rows[0], "timing": None}], "bob", "thread", execution
            )
            assert other[0]["timing"] is None


@pytest.mark.asyncio
async def test_cancelled_model_keeps_a_durable_duration(tmp_path):
    repository = TimingRepository(tmp_path / "timings.sqlite")
    now = {"ns": 0}
    started = asyncio.Event()
    park = asyncio.Event()

    async def transport(request):
        started.set()
        await park.wait()
        raise AssertionError("cancelled request should not finish")

    async with mock_chat(transport, model="test") as model:
        graph = create_agent(
            model, middleware=middlewares(repository, lambda: now["ns"])
        )
        task = asyncio.create_task(run_turn(graph, anchor="anchor"))
        await started.wait()
        now["ns"] = 17_000_000
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    rows, _ = await TimingRepository(tmp_path / "timings.sqlite").enrich(
        [{"id": "anchor", "kind": "user", "checkpoint_id": "c"}], "alice", "thread"
    )
    assert rows[1]["timing"]["duration_ms"] == 17
    assert rows[1]["timing"]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_parallel_tools_and_timeout_have_individual_durations(tmp_path):
    now = {"ns": 0}
    started = {name: asyncio.Event() for name in ["a", "b", "timeout", "failed"]}
    release = {name: asyncio.Event() for name in started}
    written = {name: asyncio.Event() for name in started}
    repository = TimingRepository(tmp_path / "timings.sqlite")
    append = repository.append
    loop = asyncio.get_running_loop()

    def observed_append(record):
        append(record)
        if record.get("tool_call_id") in written:
            loop.call_soon_threadsafe(written[record["tool_call_id"]].set)

    repository.append = observed_append

    @tool
    async def probe(label: str) -> str:
        """Deterministic boundary used to control concurrent operations."""
        started[label].set()
        await release[label].wait()
        if label == "timeout":
            raise TimeoutError("test timeout")
        if label == "failed":
            raise ValueError("test failure")
        return label

    calls = 0

    def transport(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return completion(
                calls=[tool_call("probe", label, label=label) for label in started],
                model="test",
            )
        return completion("finished", model="test")

    async with mock_chat(transport, model="test") as model:
        graph = create_agent(
            model,
            tools=[probe],
            middleware=middlewares(repository, lambda: now["ns"]),
        )
        task = asyncio.create_task(run_turn(graph))
        async with asyncio.timeout(10):
            await asyncio.gather(*(event.wait() for event in started.values()))
            for label, ms in [
                ("a", 10),
                ("timeout", 15),
                ("failed", 20),
                ("b", 30),
            ]:
                now["ns"] = ms * 1_000_000
                release[label].set()
                await written[label].wait()
        result = await task
        tools = [message for message in result["messages"] if message.type == "tool"]
        rows = project(
            SimpleNamespace(
                values={"messages": tools},
                next=(),
                config={},
                created_at="2026-01-01",
            )
        )["messages"]
        for row in rows:
            row["checkpoint_id"] = "c"
        enriched, warnings = await repository.enrich(rows, "alice", "thread")
        assert not warnings
        timings = {
            m.tool_call_id: row["timing"]
            for m, row in zip(tools, enriched, strict=True)
        }
        assert {key: timing["duration_ms"] for key, timing in timings.items()} == {
            "a": 10,
            "timeout": 15,
            "failed": 20,
            "b": 30,
        }
        assert timings["timeout"]["outcome"] == "timeout"
        assert timings["failed"]["outcome"] == "failed"
        assert timings["a"]["outcome"] == "completed"
        assert calls == 2


@pytest.mark.parametrize("scope", [AgentScope.LEAD, AgentScope.SUBAGENT])
@pytest.mark.asyncio
async def test_model_timeout_without_output_is_saved_and_attributed_to_anchor(
    tmp_path, scope
):
    repo = TimingRepository(tmp_path / "timings.sqlite")
    clock = {"ns": 0}

    def timeout(request):
        clock["ns"] = 25_000_000
        raise httpx.ReadTimeout("test timeout", request=request)

    async with mock_chat(timeout, model="test") as model:
        graph = create_agent(
            model, middleware=middlewares(repo, lambda: clock["ns"], scope)
        )
        with pytest.raises(Exception):
            await run_turn(graph, anchor="anchor")
    rows, warnings = await TimingRepository(tmp_path / "timings.sqlite").enrich(
        [{"id": "anchor", "kind": "user", "checkpoint_id": "c"}], "alice", "thread"
    )
    assert not warnings
    if scope == AgentScope.SUBAGENT:
        assert len(rows) == 1
        assert not (tmp_path / "timings.sqlite").exists()
        return
    assert len(rows) == 2
    assert rows[1]["source"] == "runtime_timing"
    assert rows[1]["timing"]["duration_ms"] == 25
    assert rows[1]["timing"]["outcome"] == "timeout"
    assert rows[1]["anchor_message_id"] == "anchor"


def test_routes_and_exports_include_measured_and_unrecorded_steps_after_reopen(
    tmp_path,
):
    import io
    import zipfile
    from fastapi.testclient import TestClient
    from trajectory_plugin_gateway import (
        TIMING_THREAD,
        create_app,
    )

    base = f"/api/ext-trajectory/threads/{TIMING_THREAD}"
    with TestClient(create_app(tmp_path, timing_evidence=True)):
        pass
    with TestClient(create_app(tmp_path, seed=False, timing_evidence=True)) as client:
        response = client.get(base + "/export", headers={"x-test-user": "alice"})
        assert response.status_code == 200, response.text
        data = response.json()
        measured = [r for r in data["rows"] if r.get("timing")]
        assert len(measured) == 5
        assert (
            next(r for r in data["rows"] if r.get("id") == "legacy-ai")["timing"]
            is None
        )
        assert len([r for r in measured if r["timing"]["is_slow"]]) == 1
        assert len([r for r in measured if r["timing"]["outcome"] == "timeout"]) == 2
        assert any(r.get("source") == "runtime_timing" for r in measured)
        archive = client.get(
            base + "/export?format=markdown", headers={"x-test-user": "alice"}
        )
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            markdown = bundle.read("trajectory.md").decode()
        assert "实测耗时" in markdown and "耗时：未记录" in markdown
        assert (
            client.get(
                base + "/checkpoints", headers={"x-test-user": "bob"}
            ).status_code
            == 404
        )


@pytest.mark.parametrize("write_fails", [False, True])
@pytest.mark.asyncio
async def test_accepted_timing_write_drains_and_preserves_cancellation(
    tmp_path, write_fails
):
    import threading

    repository = TimingRepository(tmp_path / "timings.sqlite")
    entered, release = threading.Event(), threading.Event()
    append = repository.append
    record = {
        "span_id": "cancel-write",
        "user_id": "alice",
        "thread_id": "thread",
        "operation": "model",
        "name": "test",
        "outcome": "cancelled",
        "duration_ms": 12,
        "anchor_id": "anchor",
        "ended_at": "2026-01-01T00:00:00Z",
    }

    def blocked_write(value):
        entered.set()
        release.wait()
        if write_fails:
            raise OSError("fixture write failure")
        append(value)

    repository.append = blocked_write
    task = asyncio.create_task(repository.aappend(record))
    try:
        await asyncio.to_thread(entered.wait)
        task.cancel()
        tick = asyncio.Event()
        asyncio.get_running_loop().call_soon(tick.set)
        await tick.wait()
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    if not write_fails:
        reopened = TimingRepository(tmp_path / "timings.sqlite")
        rows, _ = await reopened.enrich(
            [{"id": "anchor", "kind": "user", "checkpoint_id": "c"}],
            "alice",
            "thread",
        )
        assert rows[1]["timing"]["duration_ms"] == 12


@pytest.mark.parametrize("exhausted", [False, True])
@pytest.mark.asyncio
async def test_full_model_response_duration_includes_host_retry(tmp_path, exhausted):
    from deerflow.config.app_config import AppConfig
    from deerflow.agents.middlewares.llm_error_handling_middleware import (
        LLMErrorHandlingMiddleware,
    )

    repository = TimingRepository(tmp_path / "timings.sqlite")
    now = {"ns": 0}
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        now["ns"] = 10_000_000 if calls == 1 else 35_000_000
        if calls == 1 or exhausted:
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": "fixture rate limit",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
            )
        return completion("retried", model="test")

    config = AppConfig(
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        llm_call={
            "retry_max_attempts": 2,
            "retry_base_delay_ms": 0,
            "retry_cap_delay_ms": 0,
            "burst_retry_base_delay_ms": 0,
        },
    )
    chain = middlewares(
        repository,
        lambda: now["ns"],
        retry=LLMErrorHandlingMiddleware(app_config=config),
    )
    async with mock_chat(provider, model="test") as model:
        graph = create_agent(model, middleware=chain)
        result = await run_turn(graph)
    assert calls == 2
    message = result["messages"][-1]
    snapshot = SimpleNamespace(
        values={"messages": [message]}, next=(), created_at="2026-01-01", config={}
    )
    rows, _ = await repository.enrich(project(snapshot)["messages"], "alice", "thread")
    assert len(rows) == 1
    assert rows[0]["timing"]["duration_ms"] == 35
    expected = "failed" if exhausted else "completed"
    assert rows[0]["timing"]["outcome"] == expected
    assert message.additional_kwargs[KEY]["outcome"] == expected
    if exhausted:
        assert message.additional_kwargs[KEY]["error_type"] == "RateLimitError"
        assert (
            repository._find("alice", "thread", None, ["u"])[0]["outcome"] == "failed"
        )
        # Older checkpoints stamped fallback messages as completed.
        message.additional_kwargs[KEY]["outcome"] = "completed"
        legacy_rows, _ = await TimingRepository(tmp_path / "legacy.sqlite").enrich(
            project(snapshot)["messages"], "alice", "thread"
        )
        assert legacy_rows[0]["timing"]["outcome"] == "failed"
        assert legacy_rows[0]["timing"]["duration_ms"] == 35
