import asyncio
from types import SimpleNamespace

import pytest
from deerflow_extension_api import ModelInvocationFailed, ModelInvocationRequest, ModelInvocationUnauthorized, ModelInvocationUnavailable, ModelMessage
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from app.gateway import plugin_chat_models
from app.gateway.plugin_chat_models import PluginChatModelRuntime


def _config():
    models = [SimpleNamespace(name="GLM-5-3"), SimpleNamespace(name="GLM-5-2")]
    return SimpleNamespace(models=models, get_model_config=lambda name: next((model for model in models if model.name == name), None))


def test_uses_chat_models_without_plugin_role_grants(monkeypatch):
    calls, authorized = [], []
    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", lambda user, name, **kw: authorized.append((user.id, name, kw["is_internal"])))

    class Model:
        async def ainvoke(self, messages, **kwargs):
            return AIMessage(content="draft")

    def create(name, **kwargs):
        calls.append(name)
        return Model()

    monkeypatch.setattr("deerflow.extensions.model_invocation.create_chat_model", create)

    async def scenario():
        runtime = PluginChatModelRuntime()
        invoker = runtime.for_user(SimpleNamespace(id="user-1"), "community.check", _config())
        for model in [None, "GLM-5-2"]:
            result = await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")], model_name=model))
            assert result.content == "draft"
        runtime.close()

    asyncio.run(scenario())
    assert calls == ["GLM-5-3", "GLM-5-2"]
    assert authorized == [("user-1", "GLM-5-3", False), ("user-1", "GLM-5-2", False)]


def test_chat_model_permissions_still_apply(monkeypatch):
    def deny(*args, **kwargs):
        raise HTTPException(403, "private policy detail")

    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", deny)
    monkeypatch.setattr("deerflow.extensions.model_invocation.create_chat_model", lambda *a, **kw: pytest.fail("Denied model must not be constructed"))

    async def scenario():
        runtime = PluginChatModelRuntime()
        invoker = runtime.for_user(SimpleNamespace(id="user-1"), "community.check", _config())
        with pytest.raises(ModelInvocationUnauthorized) as error:
            await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")], model_name="GLM-5-2"))
        assert "private policy detail" not in str(error.value)
        runtime.close()

    asyncio.run(scenario())


def test_unknown_models_roles_and_closed_runtime_are_rejected(monkeypatch):
    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", lambda *a, **kw: None)

    async def scenario():
        runtime = PluginChatModelRuntime()
        invoker = runtime.for_user(SimpleNamespace(id="user-1"), "community.check", _config())
        with pytest.raises(ModelInvocationUnavailable):
            await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")], model_name="not-configured"))
        with pytest.raises(ModelInvocationFailed):
            await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")], model_role="privileged-role"))
        runtime.close()
        with pytest.raises(ModelInvocationUnavailable):
            await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")]))

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["internal", "pat", None])
def test_non_browser_callers_receive_no_chat_handle(source):
    request = SimpleNamespace(state=SimpleNamespace(auth_source=source))
    assert asyncio.run(PluginChatModelRuntime().bind(request, "community.check")) is None


def test_budget_is_shared_across_handles_and_users(monkeypatch):
    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", lambda *a, **kw: None)
    started = []

    async def scenario():
        release = asyncio.Event()

        class Model:
            async def ainvoke(self, *args, **kwargs):
                started.append(1)
                await release.wait()
                return AIMessage(content="draft")

        monkeypatch.setattr("deerflow.extensions.model_invocation.create_chat_model", lambda *a, **kw: Model())
        runtime = PluginChatModelRuntime()
        handles = [runtime.for_user(SimpleNamespace(id=f"user-{i}"), "community.check", _config()) for i in range(3)]
        tasks = [asyncio.create_task(handle.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")]))) for handle in handles]
        for _ in range(100):
            if len(started) == 2:
                break
            await asyncio.sleep(0.001)
        assert len(started) == 2
        release.set()
        await asyncio.gather(*tasks)
        runtime.close()

    asyncio.run(scenario())
    assert len(started) == 3


def test_shutdown_cancels_calls_waiting_for_user_authorization(monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()

    def authorize(*args, **kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", authorize)

    async def scenario():
        runtime = PluginChatModelRuntime()
        invoker = runtime.for_user(SimpleNamespace(id="user-1"), "community.check", _config())
        task = asyncio.create_task(invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")])))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            runtime.close()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()

    asyncio.run(scenario())


def test_deadline_includes_user_authorization(monkeypatch):
    import threading

    release = threading.Event()
    monkeypatch.setattr(plugin_chat_models, "authorize_model_use", lambda *a, **kw: release.wait(timeout=2))

    async def scenario():
        runtime = PluginChatModelRuntime()
        invoker = runtime.for_user(SimpleNamespace(id="user-1"), "community.check", _config())
        try:
            with pytest.raises(ModelInvocationFailed, match="timed out"):
                await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "draft")], timeout_seconds=0.01))
        finally:
            release.set()
            runtime.close()

    asyncio.run(scenario())
