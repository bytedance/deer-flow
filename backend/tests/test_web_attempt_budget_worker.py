"""Pin the Web attempt counter to the real run worker's streaming lifetime."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import MessagesState, StateGraph

from deerflow.community.serper import tools as serper
from deerflow.community.web_attempt_budget import counter_for_config, register_run, unregister_run
from deerflow.config.web_attempt_budget_config import WebAttemptBudgetConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_during_stream", [False, True])
async def test_worker_unregisters_budget_after_streaming_and_allows_fresh_registration(monkeypatch, fail_during_stream):
    manager = RunManager()
    record = await manager.create_or_reject("budget-lifecycle-thread")
    entered, release = asyncio.Event(), asyncio.Event()
    seen_counters = []
    tool_counters = []

    monkeypatch.setattr(serper, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    monkeypatch.setattr(serper, "_get_api_key", lambda *_args, **_kwargs: "test")

    def fake_post(*_args, **kwargs):
        tool_counters.append(kwargs["attempt_budget"])
        return {"organic": []}, None

    monkeypatch.setattr(serper, "_serper_post", fake_post)

    async def hold(state, config):
        seen_counters.append(counter_for_config(config))
        serper.web_search_tool.invoke({"query": "offline probe"}, config=config)
        entered.set()
        await release.wait()
        if fail_during_stream:
            raise RuntimeError("offline stream failure")
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("hold", hold)
    builder.set_entry_point("hold")
    builder.set_finish_point("hold")
    graph = builder.compile()
    policy = SimpleNamespace(web_attempt_budget=WebAttemptBudgetConfig(max_attempts=2))
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    worker = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None, app_config=policy),
            agent_factory=lambda **_kwargs: graph,
            graph_input={"messages": []},
            config={
                "configurable": {"thread_id": record.thread_id, "context": {"run_id": "forged-run", "app_config": policy}},
                "context": {"run_id": "forged-run", "app_config": policy},
            },
        )
    )
    runtime = {"configurable": {"__pregel_runtime": SimpleNamespace(context={"run_id": record.run_id, "app_config": policy})}}
    entered_wait = asyncio.create_task(entered.wait())
    try:
        done, _ = await asyncio.wait({entered_wait, worker}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
        assert entered_wait in done, f"worker stopped before streaming: status={record.status}, error={record.error}"
        counter = counter_for_config(runtime)
        assert counter is not None and counter.limit == 2
        assert seen_counters == [counter]
        assert tool_counters == [counter]
        counter.reserve()
        assert counter.used == 1
    finally:
        if not entered_wait.done():
            entered_wait.cancel()
        await asyncio.gather(entered_wait, return_exceptions=True)
        release.set()
        await asyncio.wait_for(worker, 5)

    assert record.status == (RunStatus.error if fail_during_stream else RunStatus.success)
    # A stale cross-process reference must fail closed after this worker drops
    # its registration, while the same ID can be registered afresh on recovery.
    assert counter_for_config(runtime).limit == 0
    register_run(record.run_id, 2)
    try:
        assert counter_for_config(runtime).used == 0
    finally:
        unregister_run(record.run_id)
