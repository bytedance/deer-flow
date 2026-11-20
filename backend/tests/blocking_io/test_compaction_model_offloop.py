"""Manual compaction must not build its summarization models on the loop.

``POST /api/threads/{thread_id}/compact`` resolves the live config and builds
the summarization middleware right before the summary call. That build
constructs the run-profile model and any separately configured summary model.
Provider construction can read local credentials (Codex CLI ``auth.json``); the
real Codex provider is built here so that IO stays inside the strict gate,
while inference stays offline.
"""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Overwrite

from app.gateway.routers import threads
from app.gateway.services import build_checkpoint_state_mutation_accessor
from deerflow.agents.middlewares import summarization_middleware
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config
from deerflow.models.openai_codex_provider import CodexChatModel
from deerflow.runtime import RunManager
from deerflow.runtime.context_compaction import ContextCompactionDisabled, compact_thread_context
from deerflow.runtime.context_keys import CHECKPOINT_AGENT_NAME_METADATA_KEY, DEFAULT_AGENT_NAME_METADATA_VALUE
from deerflow.runtime.user_context import get_effective_user_id, reset_current_user, set_current_user

pytestmark = pytest.mark.asyncio

THREAD_ID = "compaction-thread"
_SUMMARY = "The user asked for a trip plan and got one."
_KEEP = ("messages", 1)
# Memory stays off, so no pre-compaction flush runs; test_summarization_memory_flush.py covers that hook.
_CONFIG_YAML = """\
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
models:
  - name: fixture-codex
    model: fixture-model
    use: deerflow.models.openai_codex_provider:CodexChatModel
summarization:
  enabled: true
memory:
  enabled: false
"""


def _codex_config(**summarization) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {"name": "fixture-codex", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"},
                {"name": "fixture-summary", "model": "fixture-summary-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"},
            ],
            "summarization": {"enabled": True, **summarization},
            "memory": {"enabled": False},
        }
    )


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """Real Codex construction (credential file IO included); offline inference."""
    credentials = tmp_path / "auth.json"
    credentials.write_text(json.dumps({"access_token": "fixture-token", "account_id": "fixture-account"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_AUTH_PATH", str(credentials))
    calls = []

    async def invoke(model, prompt, config=None, **kwargs):
        calls.append((model, threading.get_ident()))
        return AIMessage(content=_SUMMARY)

    monkeypatch.setattr(CodexChatModel, "ainvoke", invoke)
    return calls


class _SummaryModel:
    """A built provider; only its summary call is observed."""

    _llm_type = "fixture"

    def __init__(self) -> None:
        self.ainvoke = AsyncMock(return_value=AIMessage(content=_SUMMARY))

    def with_config(self, **kwargs):
        return self


def _gateway_request():
    state = SimpleNamespace(checkpointer=InMemorySaver(), checkpoint_channel_mode="full", store=None, run_manager=RunManager())
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def _seeded_thread():
    """A finished thread bound to the default agent, plus its compaction accessor."""
    request = _gateway_request()
    accessor, config = build_checkpoint_state_mutation_accessor(request, thread_id=THREAD_ID, as_node="seed")
    config["metadata"] = {CHECKPOINT_AGENT_NAME_METADATA_KEY: DEFAULT_AGENT_NAME_METADATA_VALUE}
    messages = [HumanMessage(id="h1", content="Plan a trip."), AIMessage(id="a1", content="Here is a plan."), HumanMessage(id="h2", content="Book the hotel.")]
    await accessor.aupdate(config, {"messages": Overwrite(messages)}, as_node="seed")
    accessor, config = build_checkpoint_state_mutation_accessor(request, thread_id=THREAD_ID, as_node="manual_compaction")
    return request, accessor, config


@pytest.mark.parametrize(
    ("summarization", "summary_model"),
    [({}, "fixture-model"), ({"model_name": "fixture-summary"}, "fixture-summary-model")],
    ids=["run-model", "configured-summary-model"],
)
async def test_manual_compaction_builds_codex_models_off_loop(codex, summarization, summary_model):
    _, accessor, config = await _seeded_thread()

    result = await compact_thread_context(accessor, THREAD_ID, keep=_KEEP, app_config=_codex_config(**summarization))

    # On the loop, the gate rejects every credential read, no model can be
    # built, and compaction reports itself disabled (the route's 409).
    assert (result.compacted, result.removed_message_count, result.preserved_message_count) == (True, 2, 1)
    snapshot = await accessor.aget(config)
    assert [message.id for message in snapshot.values["messages"]] == ["h2"]
    assert snapshot.values["summary_text"] == _SUMMARY
    assert [(model.model, thread) for model, thread in codex] == [(summary_model, threading.get_ident())]


@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold-config", "cached-config"])
async def test_compact_route_reads_live_config_off_loop(tmp_path, monkeypatch, codex, warm_cache):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"

    def seed_files() -> None:
        config_path.write_text(_CONFIG_YAML, encoding="utf-8")
        extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    await asyncio.to_thread(seed_files)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()
    reset_extensions_config()
    request, _, _ = await _seeded_thread()
    try:
        if warm_cache:
            await asyncio.to_thread(get_app_config)
        # The route passes no app_config, so compaction resolves the live
        # config, which stats and hashes config.yaml even on a cache hit.
        response = await threads.compact_thread.__wrapped__(THREAD_ID, threads.ThreadCompactRequest(keep={"type": "messages", "value": 1}), request)
    finally:
        reset_app_config()
        reset_extensions_config()

    # On the loop, the gate rejects the config read and the route answers 500.
    assert (response.compacted, response.removed_message_count, response.preserved_message_count) == (True, 2, 1)
    assert [(model.model, thread) for model, thread in codex] == [("fixture-model", threading.get_ident())]


async def test_construction_preserves_context_and_keeps_default_pool_available(monkeypatch):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    started = asyncio.Event()
    release = threading.Event()
    observed = []
    model = _SummaryModel()

    def construct(**kwargs):
        observed.append((get_effective_user_id(), threading.get_ident()))
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=10):
            raise TimeoutError("test construction was not released")
        return model

    monkeypatch.setattr(summarization_middleware, "create_chat_model", construct)
    _, accessor, _ = await _seeded_thread()
    token = set_current_user(SimpleNamespace(id="request-owner"))
    task = asyncio.create_task(compact_thread_context(accessor, THREAD_ID, keep=_KEEP, app_config=_codex_config()))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not task.done()
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "unrelated work"), timeout=5) == "unrelated work"
    finally:
        release.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            reset_current_user(token)

    assert task.result().compacted is True
    assert observed == [("request-owner", observed[0][1])]
    assert observed[0][1] != threading.get_ident()
    model.ainvoke.assert_awaited_once()


async def test_cancelled_construction_does_not_start_inference_or_write(monkeypatch):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    model = _SummaryModel()

    def construct(**kwargs):
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(timeout=10):
                raise TimeoutError("test construction was not released")
            return model
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(summarization_middleware, "create_chat_model", construct)
    _, accessor, config = await _seeded_thread()
    before = await accessor.aget(config)
    task = asyncio.create_task(compact_thread_context(accessor, THREAD_ID, keep=_KEEP, app_config=_codex_config()))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)

    model.ainvoke.assert_not_awaited()
    after = await accessor.aget(config)
    assert after.config["configurable"]["checkpoint_id"] == before.config["configurable"]["checkpoint_id"]
    assert [message.id for message in after.values["messages"]] == ["h1", "a1", "h2"]


async def test_construction_failure_still_reports_compaction_disabled(monkeypatch):
    def construct(**kwargs):
        raise ValueError("fixture credential unavailable")

    monkeypatch.setattr(summarization_middleware, "create_chat_model", construct)
    _, accessor, config = await _seeded_thread()

    with pytest.raises(ContextCompactionDisabled):
        await compact_thread_context(accessor, THREAD_ID, keep=_KEEP, app_config=_codex_config())
    snapshot = await accessor.aget(config)
    assert [message.id for message in snapshot.values["messages"]] == ["h1", "a1", "h2"]
