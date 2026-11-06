"""Skill-moderation and goal-evaluator models must not read credentials on the loop.

Both sites build a provider right before a standalone model call: the skill
security scan behind the Gateway skill routes, the installer and the in-graph
``skill_manage`` tool, and the goal evaluator that runs after Gateway runs.
Provider construction can read local credentials (Codex CLI ``auth.json``);
the real Codex provider is built here so that IO stays inside the strict gate,
while tracing and inference stay offline.
"""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

# evaluate_goal_completion imports these lazily. A Gateway run has loaded them
# long before its goal is evaluated, so a cold import here would only time the
# import itself inside the strict gate.
import deerflow.agents.middlewares.memory_middleware  # noqa: F401
import deerflow.agents.middlewares.pii_redaction_middleware  # noqa: F401
import deerflow.tools.skill_manage_tool as skill_manage_module
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config
from deerflow.models import factory
from deerflow.models.openai_codex_provider import CodexChatModel
from deerflow.runtime import goal
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.runs import worker
from deerflow.runtime.user_context import get_effective_user_id, reset_current_user, set_current_user
from deerflow.skills import security_scanner

pytestmark = pytest.mark.asyncio

_SCAN_VERDICT = '{"decision": "allow", "reason": "clean"}'
_GOAL_VERDICT = json.dumps({"satisfied": True, "blocker": "none", "reason": "Reported.", "evidence_summary": "The report was sent."})
_CONFIG_YAML = """\
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
models:
  - name: fixture-codex
    model: fixture-model
    use: deerflow.models.openai_codex_provider:CodexChatModel
"""


def _codex_config(**overrides) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture-codex", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"}],
            **overrides,
        }
    )


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """Real Codex construction (credential file IO included); offline tracing and inference."""
    credentials = tmp_path / "auth.json"
    credentials.write_text(json.dumps({"access_token": "fixture-token", "account_id": "fixture-account"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_AUTH_PATH", str(credentials))
    monkeypatch.setattr(factory, "build_tracing_callbacks", lambda **kwargs: [])
    state = SimpleNamespace(reply="", calls=[])

    async def invoke(model, messages, *, config):
        state.calls.append((model, threading.get_ident()))
        return AIMessage(content=state.reply)

    monkeypatch.setattr(CodexChatModel, "ainvoke", invoke)
    return state


def _scan(config):
    return security_scanner.scan_skill_content("# Fixture skill", app_config=config)


def _evaluate(config):
    return goal.evaluate_goal_completion(goal.build_goal_state("Report"), [HumanMessage(content="Report"), AIMessage(content="Done.")], model_name="fixture-codex", app_config=config)


_SITES = [
    pytest.param(SimpleNamespace(module=security_scanner, call=_scan, verdict=_SCAN_VERDICT), id="skill-moderation"),
    pytest.param(SimpleNamespace(module=goal, call=_evaluate, verdict=_GOAL_VERDICT), id="goal-evaluator"),
]


@pytest.mark.parametrize("moderation_model_name", ["fixture-codex", None], ids=["named-model", "default-model"])
async def test_skill_scan_builds_codex_model_off_loop(codex, moderation_model_name):
    codex.reply = _SCAN_VERDICT

    result = await _scan(_codex_config(skill_evolution={"moderation_model_name": moderation_model_name}))

    # On the loop, the gate rejects the credential read and the scan falls back
    # to its fail-closed "unavailable" block instead of the model's verdict.
    assert (result.decision, result.reason, result.available) == ("allow", "clean", True)
    assert len(codex.calls) == 1
    assert isinstance(codex.calls[0][0], CodexChatModel)
    assert codex.calls[0][1] == threading.get_ident()


@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold-config", "cached-config"])
async def test_in_graph_skill_scan_reads_live_config_off_loop(tmp_path, monkeypatch, codex, warm_cache):
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
    codex.reply = _SCAN_VERDICT
    try:
        if warm_cache:
            await asyncio.to_thread(get_app_config)
        # skill_manage's in-graph scan passes no app_config, so the scanner
        # resolves the live config, which stats and hashes config.yaml.
        verdict = await skill_manage_module._scan_or_raise("# Fixture skill", executable=False, location="fixture-skill/SKILL.md")
    finally:
        reset_app_config()
        reset_extensions_config()

    assert verdict == {"decision": "allow", "reason": "clean"}
    assert len(codex.calls) == 1
    assert codex.calls[0][1] == threading.get_ident()


async def test_unreadable_live_config_fails_closed_without_a_loop_read(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    reset_app_config()
    reads = []

    def read_live_config():
        reads.append(threading.get_ident())
        return get_app_config()

    monkeypatch.setattr(security_scanner, "get_app_config", read_live_config)
    try:
        result = await security_scanner.scan_skill_content("# Fixture skill", attach_tracing=False)
    finally:
        reset_app_config()

    assert (result.decision, result.available) == ("block", False)
    assert result.reason == "Security scan unavailable for skill content; manual review required."
    # One read, in the assembly pool: the fail-closed fallback does not retry it on the loop.
    assert len(reads) == 1
    assert reads[0] != threading.get_ident()


async def test_goal_evaluator_builds_codex_model_off_loop(codex):
    codex.reply = _GOAL_VERDICT

    evaluation = await _evaluate(_codex_config())

    assert evaluation["satisfied"] is True
    assert evaluation["reason"] == "Reported."
    assert len(codex.calls) == 1
    assert isinstance(codex.calls[0][0], CodexChatModel)
    assert codex.calls[0][1] == threading.get_ident()


class _Bridge:
    async def publish(self, _run_id, _event, _payload):
        pass


async def test_worker_builds_goal_evaluator_off_loop(codex):
    codex.reply = _GOAL_VERDICT
    config = _codex_config()
    checkpointer = InMemorySaver()
    thread_id = "goal-thread"
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": [HumanMessage(content="Send the report."), AIMessage(content="The report was sent.")]}
    checkpoint["channel_versions"] = {"messages": 1}
    checkpointer.put({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, {"step": 1}, {"messages": 1})
    await goal.write_thread_goal(checkpointer, thread_id, goal.build_goal_state("Send the report"))
    factory_threads = []

    def build_evaluator():
        # Mirrors run_agent's cached factory around create_goal_evaluator_model.
        factory_threads.append(threading.get_ident())
        return goal.create_goal_evaluator_model(model_name="fixture-codex", app_config=config)

    candidate = await worker._prepare_goal_continuation_input(
        accessor=CheckpointStateAccessor.bind(build_state_mutation_graph("goal_evaluator", "full"), checkpointer, mode="full"),
        bridge=_Bridge(),
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        model_name="fixture-codex",
        app_config=config,
        evaluator_model_factory=build_evaluator,
    )

    # On the loop, the gate rejects the factory's credential read and the goal
    # stands down as "evaluator_failed" without a verdict.
    assert isinstance(candidate, worker._GoalCompletionCandidate)
    assert candidate.evaluation["satisfied"] is True
    assert len(factory_threads) == 1
    assert factory_threads[0] != threading.get_ident()
    assert len(codex.calls) == 1
    assert codex.calls[0][1] == threading.get_ident()


@pytest.mark.parametrize("site", _SITES)
async def test_construction_preserves_context_and_keeps_default_pool_available(monkeypatch, site):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    started = asyncio.Event()
    release = threading.Event()
    observed = []
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=site.verdict)))

    def construct(**kwargs):
        observed.append((get_effective_user_id(), threading.get_ident()))
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=10):
            raise TimeoutError("test construction was not released")
        return model

    monkeypatch.setattr(site.module, "create_chat_model", construct)
    token = set_current_user(SimpleNamespace(id="request-owner"))
    task = asyncio.create_task(site.call(_codex_config()))
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

    assert observed == [("request-owner", observed[0][1])]
    assert observed[0][1] != threading.get_ident()
    model.ainvoke.assert_awaited_once()


@pytest.mark.parametrize("site", _SITES)
async def test_cancelled_construction_does_not_start_inference(monkeypatch, site):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    model = SimpleNamespace(ainvoke=AsyncMock())

    def construct(**kwargs):
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(timeout=10):
                raise TimeoutError("test construction was not released")
            return model
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(site.module, "create_chat_model", construct)
    task = asyncio.create_task(site.call(_codex_config()))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
    model.ainvoke.assert_not_awaited()


async def test_moderation_construction_failure_still_fails_closed(monkeypatch):
    def construct(**kwargs):
        raise ValueError("fixture credential unavailable")

    monkeypatch.setattr(security_scanner, "create_chat_model", construct)

    result = await _scan(_codex_config())

    assert (result.decision, result.available) == ("block", False)
    assert result.reason == "Security scan unavailable for skill content; manual review required."


async def test_evaluator_construction_failure_propagates(monkeypatch):
    failure = ValueError("fixture credential unavailable")

    def construct(**kwargs):
        raise failure

    monkeypatch.setattr(goal, "create_chat_model", construct)

    with pytest.raises(ValueError) as caught:
        await _evaluate(_codex_config())
    assert caught.value is failure
