"""A breached compaction budget must not be re-spent on every turn."""

from __future__ import annotations

import copy
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from test_summarization_cost_recovery import FreeModel, _middleware, _state, _text

from deerflow.agents.middlewares import summarization_middleware as module
from deerflow.agents.middlewares.summarization_middleware import SummaryGenerationError


class ProgressModel(FreeModel):
    """Produce a new carry each time so the no-op cache cannot hide spend."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.reply = f"summary-{len(self.prompts) + 1}"
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.fixture(autouse=True)
def isolated_cooldowns(monkeypatch):
    monkeypatch.setattr(module, "_SUMMARY_CHUNK_RETRY_CACHE", OrderedDict(), raising=False)


async def compact(middleware, state, runtime, asynchronous, manual=False):
    method = middleware.acompact_state if asynchronous else middleware.compact_state
    if manual:
        with pytest.raises(SummaryGenerationError):
            if asynchronous:
                await method(state, runtime, force=True, raise_on_failure=True)
            else:
                method(state, runtime, force=True, raise_on_failure=True)
        return None
    return await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
@pytest.mark.parametrize("rebuild", [False, True], ids=["same-instance", "new-instance"])
async def test_breach_cooldown_survives_new_turns_and_middleware_rebuilds(monkeypatch, caplog, asynchronous, manual, rebuild):
    runtime = SimpleNamespace(context={"thread_id": "over-limit", "user_id": "alice"})
    state, _ = _state(_text(128 * 80), "S")
    original = copy.deepcopy(state)
    model = ProgressModel(hard_limit=140)
    hook, observed = Mock(), Mock()
    monkeypatch.setattr(module, "notify_context_compacted", observed)
    middleware = _middleware(model, budget=128, before_summarization=[hook])
    assert await compact(middleware, state, runtime, asynchronous, manual) is None
    assert len(model.prompts) == 64 and model.guard_hits == 0
    assert state == original
    # A full-source hash would miss the next trigger as history grows.
    state["messages"].extend([HumanMessage(content="next request", id="next-user"), AIMessage(content="next answer", id="next-ai")])
    original = copy.deepcopy(state)
    if rebuild:
        middleware = _middleware(model, budget=128, before_summarization=[hook])
    assert await compact(middleware, state, runtime, asynchronous, manual) is None
    assert len(model.prompts) == 64, "the blocked retry must make no additional model calls"
    assert state == original
    assert middleware.summary_call_count == middleware.summary_noop_count == middleware.summary_skip_count == 0
    hook.assert_not_called()
    observed.assert_not_called()
    assert "cooldown" in caplog.text
    assert "trim_tokens_to_summarize" in caplog.text
    assert "evidence_" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_cooldown_expires_without_sleeping(monkeypatch, asynchronous):
    clock = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0], raising=False)
    runtime = SimpleNamespace(context={"thread_id": "expiry", "user_id": "alice"})
    state, _ = _state(_text(128 * 80), "S")
    model = ProgressModel(hard_limit=140)
    middleware = _middleware(model, budget=128)
    assert await compact(middleware, state, runtime, asynchronous) is None
    assert len(model.prompts) == 64
    clock[0] += 299
    assert await compact(middleware, state, runtime, asynchronous) is None
    assert len(model.prompts) == 64
    clock[0] += 1
    assert await compact(middleware, state, runtime, asynchronous) is None
    assert len(model.prompts) == 128 and model.guard_hits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("remedy", ["larger-budget", "smaller-source"])
async def test_remediation_can_retry_immediately(asynchronous, remedy):
    runtime = SimpleNamespace(context={"thread_id": "remedy", "user_id": "alice"})
    state, _ = _state(_text(128 * 80), "S")
    model = ProgressModel(hard_limit=70)
    middleware = _middleware(model, budget=128)
    assert await compact(middleware, state, runtime, asynchronous) is None
    assert len(model.prompts) == 64
    if remedy == "larger-budget":
        middleware = _middleware(model, budget=20000)
    else:
        state["messages"][0] = state["messages"][0].model_copy(update={"content": "shortened input"})
    assert await compact(middleware, state, runtime, asynchronous) is not None
    assert 64 < len(model.prompts) <= 66 and model.guard_hits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["user", "thread", "agent", "window", "subagent"])
async def test_breach_does_not_suppress_another_execution_scope(scope):
    runtime = SimpleNamespace(context={"thread_id": "shared-id", "user_id": "alice", "agent_name": "researcher"})
    if scope == "subagent":
        runtime.context.update(is_subagent=True, agent_id="child", sandbox_lease_owner_id="execution-1")
    state, _ = _state(_text(128 * 80), "S")
    first = ProgressModel()
    assert await compact(_middleware(first, budget=128), state, runtime, True) is None
    assert len(first.prompts) == 64
    if scope == "subagent":
        runtime.context["sandbox_lease_owner_id"] = "execution-2"
    elif scope == "window":
        state["messages"][0] = state["messages"][0].model_copy(update={"id": "different-window"})
    else:
        key = {"user": "user_id", "thread": "thread_id", "agent": "agent_name"}[scope]
        runtime.context[key] = "another-value"
    other = ProgressModel()
    assert await compact(_middleware(other, budget=128), state, runtime, True) is None
    assert len(other.prompts) == 64 and other.guard_hits == 0


@pytest.mark.asyncio
async def test_ordinary_generation_failure_does_not_start_chunk_cooldown():
    runtime = SimpleNamespace(context={"thread_id": "transient", "user_id": "alice"})
    state, _ = _state("short source", "S")
    model = FreeModel(reply="")
    middleware = _middleware(model)
    assert await compact(middleware, state, runtime, True) is None
    model.reply = "Recovered summary"
    assert await compact(middleware, state, runtime, True) is not None
    assert len(model.prompts) == 2
