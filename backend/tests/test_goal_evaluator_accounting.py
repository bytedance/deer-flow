"""Critic usage is billed as middleware without critic text in user history."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.routers.console import _ModelPricing, _run_cost
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import goal
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore


class ScriptedModel(BaseChatModel):
    answer: str
    identifier: str
    reported_usage: dict | None = None
    answers: list[str] | None = None
    normal_completion: bool = False

    @property
    def _llm_type(self):
        return "scripted-accounting"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        answer = self.answers.pop(0) if self.answers else self.answer
        metadata = {"model_name": self.identifier}
        if self.normal_completion:
            metadata["finish_reason"] = "stop"
        response = AIMessage(content=answer, usage_metadata=self.reported_usage, response_metadata=metadata)
        return ChatResult(generations=[ChatGeneration(message=response)])


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def run_store(request):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["valid", "invalid_json", "missing_usage", "recovered_json", "repeated_invalid_json", "unsatisfied_json"])
async def test_worker_terminal_ledger_includes_evaluator_usage_without_visible_critic(run_store, monkeypatch, response):
    events = MemoryRunEventStore()
    checkpointer = InMemorySaver()
    manager = RunManager(store=run_store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    lead = ScriptedModel(answer="The report is verified.", identifier="lead-model", reported_usage={"input_tokens": 30, "output_tokens": 10, "total_tokens": 40})
    verdict = json.dumps({"satisfied": response != "unsatisfied_json", "blocker": "missing_evidence", "reason": "PRIVATE_CRITIC_VERDICT", "relied_on_assumption": False})
    critic_calls = 2 if response in {"recovered_json", "repeated_invalid_json"} else 1
    critic = ScriptedModel(
        answer="PRIVATE_CRITIC_INVALID" if response in {"invalid_json", "repeated_invalid_json"} else verdict,
        answers=["PRIVATE_CRITIC_INVALID", verdict] if response == "recovered_json" else None,
        normal_completion=response in {"recovered_json", "repeated_invalid_json", "unsatisfied_json"},
        identifier="critic-model",
        reported_usage=None if response == "missing_usage" else {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100, "input_token_details": {"cache_read": 32}},
    )
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: critic)

    async def node(state, config):
        answer = await lead.ainvoke(state["messages"], config=config)
        return {"messages": [answer], "title": "Report"}

    graph = StateGraph(get_thread_state_schema("full"))
    graph.add_node("report", node)
    graph.add_edge(START, "report")
    graph.add_edge("report", END)
    compiled = graph.compile(checkpointer=checkpointer)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, event_store=events, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    row = await run_store.get(record.run_id, user_id="alice")
    assert row["llm_call_count"] == 1 + critic_calls
    assert row["lead_agent_tokens"] == 40
    pricing = {"lead-model": _ModelPricing(2, 4, "USD"), "critic-model": _ModelPricing(2, 4, "USD", 0.5)}
    cost = _run_cost(pricing, model_name="lead-model", total_input_tokens=row["total_input_tokens"], total_output_tokens=row["total_output_tokens"], token_usage_by_model=row["token_usage_by_model"])
    if response == "missing_usage":
        assert row["token_usage_by_model"]["critic-model"]["missing_usage_calls"] == 1
        assert cost is None
    else:
        assert row["middleware_tokens"] == 100 * critic_calls
        assert row["total_input_tokens"] == 30 + 80 * critic_calls
        assert row["total_output_tokens"] == 10 + 20 * critic_calls
        assert row["total_tokens"] == 40 + 100 * critic_calls
        assert row["token_usage_by_model"]["critic-model"]["cache_read_tokens"] == 32 * critic_calls
        assert cost == pytest.approx(0.0001 + 0.000192 * critic_calls)
    if response in {"recovered_json", "repeated_invalid_json", "unsatisfied_json"}:
        assert row["goal_verdict"]["satisfied"] is (response == "recovered_json")
        assert row["goal_verdict"]["continuations"] == 0
    history = await events.list_messages("result", user_id="alice")
    assert "PRIVATE_CRITIC" not in json.dumps(history)


@pytest.mark.asyncio
async def test_evaluator_external_usage_is_json_safe_and_source_deduplicated():
    events = MemoryRunEventStore()
    journal = RunJournal("run", "thread", events)
    model = ScriptedModel(answer='{"satisfied": true, "reason": "PRIVATE_CRITIC"}', identifier="critic-model", reported_usage={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})
    records = []

    def sink(values):
        json.dumps(values)
        records.extend(values)
        journal.record_external_llm_usage_records(values)
        journal.record_external_llm_usage_records(values)

    ambient = var_child_runnable_config.set({"callbacks": [journal]})
    try:
        await goal.evaluate_goal_completion(goal.build_goal_state("Report"), [HumanMessage(content="Report"), AIMessage(content="Verified")], model=model, usage_callback=sink)
    finally:
        var_child_runnable_config.reset(ambient)
    completion = journal.get_completion_data()
    assert completion["total_tokens"] == completion["middleware_tokens"] == 25
    assert completion["llm_call_count"] == 1
    assert len(records) == 1
    await journal.close()
    assert await events.list_messages("thread") == []


@pytest.mark.asyncio
async def test_paid_evaluator_usage_survives_post_response_observer_failure(monkeypatch):
    from deerflow.extensions import notify

    model = ScriptedModel(answer='{"satisfied": true}', identifier="critic-model", reported_usage={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})
    journal = RunJournal("run", "thread", MemoryRunEventStore())

    async def fail_after_provider(*args, invoke, **kwargs):
        await invoke()
        raise RuntimeError("observer failed after response")

    monkeypatch.setattr(notify, "observe_system_model_call", fail_after_provider)
    with pytest.raises(RuntimeError, match="observer"):
        await goal.evaluate_goal_completion(goal.build_goal_state("Report"), [HumanMessage(content="Report"), AIMessage(content="Verified")], model=model, extensions=object(), usage_callback=journal.record_external_llm_usage_records)
    completion = journal.get_completion_data()
    assert completion["middleware_tokens"] == 25
    assert completion["llm_call_count"] == 1
    await journal.close()


@pytest.mark.asyncio
async def test_evaluator_exception_without_usage_marks_attempt_unpriced():
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("provider failed")), model_name="critic-model")
    journal = RunJournal("run", "thread", MemoryRunEventStore())
    with pytest.raises(RuntimeError, match="provider"):
        await goal.evaluate_goal_completion(goal.build_goal_state("Report"), [HumanMessage(content="Report"), AIMessage(content="Verified")], model=model, usage_callback=journal.record_external_llm_usage_records)
    completion = journal.get_completion_data()
    assert completion["llm_call_count"] == 1
    assert completion["token_usage_by_model"]["critic-model"]["missing_usage_calls"] == 1
    await journal.close()
