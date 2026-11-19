"""One-shot model construction must not read credentials on the Gateway loop."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage

from deerflow.config.app_config import AppConfig
from deerflow.models import factory
from deerflow.models.openai_codex_provider import CodexChatModel
from deerflow.runtime.user_context import get_effective_user_id, reset_current_user, set_current_user
from deerflow.utils import oneshot_llm


def _request(app_config):
    return dict(system_instruction="Rewrite the draft.", user_content="hello", run_name="input_polish", app_config=app_config)


@pytest.mark.asyncio
@pytest.mark.parametrize("detailed", [False, True])
async def test_real_codex_credentials_are_loaded_off_loop(tmp_path, monkeypatch, detailed):
    credentials = tmp_path / "auth.json"
    await asyncio.to_thread(credentials.write_text, json.dumps({"access_token": "fixture-token", "account_id": "fixture-account"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_AUTH_PATH", str(credentials))
    # Keep tracing and inference offline; provider construction and credential IO
    # are real and remain inside the strict blocking-IO detector.
    monkeypatch.setattr(factory, "build_tracing_callbacks", lambda **kwargs: [])
    monkeypatch.setattr(oneshot_llm, "inject_langfuse_metadata", lambda *args, **kwargs: None)
    response = AIMessage(content=[{"type": "text", "text": "Rewritten draft"}], response_metadata={"fixture": True})
    loop_thread = threading.get_ident()
    calls = []

    async def invoke(model, messages, *, config):
        calls.append((model, messages, config, threading.get_ident()))
        return response

    monkeypatch.setattr(CodexChatModel, "ainvoke", invoke)
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture-codex", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"}],
        }
    )
    helper = oneshot_llm.run_oneshot_llm_detailed if detailed else oneshot_llm.run_oneshot_llm
    result = await helper(**_request(config))

    assert (result.text if detailed else result) == "Rewritten draft"
    if detailed:
        assert result.message is response
    assert len(calls) == 1
    assert isinstance(calls[0][0], CodexChatModel)
    assert [message.content for message in calls[0][1]] == ["Rewrite the draft.", "hello"]
    assert calls[0][2] == {"run_name": "input_polish"}
    assert calls[0][3] == loop_thread


@pytest.mark.asyncio
async def test_construction_preserves_context_and_keeps_default_pool_available(monkeypatch):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    started = asyncio.Event()
    release = threading.Event()
    observed = []
    response = AIMessage(content="ok")
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
    config = object()

    def construct(**kwargs):
        observed.append((get_effective_user_id(), threading.get_ident(), kwargs))
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=10):
            raise TimeoutError("test construction was not released")
        return model

    metadata = []
    monkeypatch.setattr(oneshot_llm, "create_chat_model", construct)
    monkeypatch.setattr(oneshot_llm, "inject_langfuse_metadata", lambda *args, **kwargs: metadata.append(kwargs))
    token = set_current_user(SimpleNamespace(id="request-owner"))
    task = asyncio.create_task(oneshot_llm.run_oneshot_llm_detailed(**_request(config), model_name="polish-model", thread_id="thread-1", model_overrides={"temperature": 0.2}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not task.done()
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "unrelated work"), timeout=5) == "unrelated work"
    finally:
        release.set()
        try:
            result = await asyncio.wait_for(task, timeout=5)
        finally:
            reset_current_user(token)

    assert result.message is response
    assert observed == [("request-owner", observed[0][1], {"name": "polish-model", "thinking_enabled": False, "app_config": config, "model_overrides": {"temperature": 0.2}})]
    assert observed[0][1] != threading.get_ident()
    assert metadata[0]["user_id"] == "request-owner"
    assert metadata[0]["thread_id"] == "thread-1"
    model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_construction_failure_prevents_inference(monkeypatch):
    failure = ValueError("fixture credential unavailable")
    metadata = Mock()

    def construct(**kwargs):
        raise failure

    monkeypatch.setattr(oneshot_llm, "create_chat_model", construct)
    monkeypatch.setattr(oneshot_llm, "inject_langfuse_metadata", metadata)
    with pytest.raises(ValueError, match="fixture credential unavailable") as caught:
        await oneshot_llm.run_oneshot_llm(**_request(object()))
    assert caught.value is failure
    metadata.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_construction_does_not_start_inference(monkeypatch):
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

    monkeypatch.setattr(oneshot_llm, "create_chat_model", construct)
    task = asyncio.create_task(oneshot_llm.run_oneshot_llm(**_request(object())))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
    model.ainvoke.assert_not_awaited()
