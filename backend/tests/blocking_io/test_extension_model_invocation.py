"""Provider construction may read credentials but must never block the host loop."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api import ModelInvocationRequest, ModelMessage
from langchain_core.messages import AIMessage

from deerflow.extensions import model_invocation
from deerflow.extensions.model_access import ModelInvocationBudget, ModelInvocationGrant


@pytest.mark.asyncio
async def test_provider_construction_runs_off_loop(tmp_path, monkeypatch):
    credentials = tmp_path / "provider.txt"
    await asyncio.to_thread(credentials.write_text, "test-only", encoding="utf-8")
    threads = []

    def factory(name, *, app_config):
        assert credentials.read_text(encoding="utf-8") == "test-only"
        threads.append(threading.get_ident())
        return SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="ok")))

    monkeypatch.setattr(model_invocation, "create_chat_model", factory)
    invoker = model_invocation.HostModelInvoker(
        "example:install",
        ModelInvocationGrant(roles={"default": "model"}),
        ModelInvocationBudget(1),
        SimpleNamespace(get_model_config=lambda _: object()),
    )
    result = await invoker.invoke(ModelInvocationRequest([ModelMessage("user", "hello")]))
    assert result.content == "ok"
    assert threads and threads[0] != threading.get_ident()
    invoker.close()


@pytest.mark.asyncio
async def test_schema_subprocess_io_runs_off_loop(monkeypatch):
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='{"label":"你好"}')))
    monkeypatch.setattr(model_invocation, "create_chat_model", lambda *args, **kwargs: model)
    invoker = model_invocation.HostModelInvoker(
        "example:install",
        ModelInvocationGrant(roles={"default": "model"}),
        ModelInvocationBudget(1),
        SimpleNamespace(get_model_config=lambda _: object()),
    )
    result = await invoker.invoke(
        ModelInvocationRequest(
            [ModelMessage("user", "hello")],
            response_schema={"type": "object", "properties": {"label": {"type": "string"}}},
        )
    )
    assert result.structured_output == {"label": "你好"}
    invoker.close()
