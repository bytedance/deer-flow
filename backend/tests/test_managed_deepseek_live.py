"""Opt-in verification of the same managed DeepSeek path before/after a fix.

From backend/ (test credentials are read only from the process environment):
    DEER_FLOW_RUN_LIVE_TESTS=1 uv run --no-sync pytest \
        tests/test_managed_deepseek_live.py -q -s

Set DEEPSEEK_TEST_API_KEY separately; optional DEEPSEEK_TEST_MODEL defaults to
"deepseek-flash". This sends a few short requests to api.deepseek.com and may
incur charges. It never starts an agent or modifies the real managed catalog.
"""

import os
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel
from deerflow.models.factory import create_chat_model

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1" or not os.getenv("DEEPSEEK_TEST_API_KEY") or bool(os.getenv("CI")),
        reason="Requires explicit live opt-in and DEEPSEEK_TEST_API_KEY; never runs in CI",
    ),
]


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    return ManagedModel(name="deepseek-live", model=os.getenv("DEEPSEEK_TEST_MODEL", "deepseek-flash"), base_url="https://api.deepseek.com", api_key=os.environ["DEEPSEEK_TEST_API_KEY"], max_tokens=512)


@pytest.mark.asyncio
async def test_managed_deepseek_connection_probe_live(profile, tmp_path):
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    result = await router.test_model(request, router.SaveModelRequest(config=profile))
    assert result == {"ok": True, "message": "success"}
    assert not (tmp_path / "managed-models").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_managed_deepseek_tool_round_trip_live(profile, thinking, tmp_path):
    config = AppConfig.model_validate({"sandbox": {"use": "test"}, "models": [profile.runtime_config().model_dump(exclude_none=True)]})
    model = create_chat_model(profile.name, thinking_enabled=thinking, app_config=config, attach_tracing=False, timeout=30, max_retries=0)
    tool = {"type": "function", "function": {"name": "connection_check", "description": "Check the connection", "parameters": {"type": "object", "properties": {}}}}
    bound = model.bind_tools([tool])
    history = [HumanMessage(content="Call connection_check exactly once. After its result, reply only OK.")]
    first = None
    async for chunk in bound.astream(history, config={"callbacks": []}):
        first = chunk if first is None else first + chunk
    assert first is not None and first.tool_calls
    history.append(first)
    history.extend(ToolMessage(content="Connection is healthy.", tool_call_id=call["id"]) for call in first.tool_calls)
    payload = model._get_request_payload(history, **bound.kwargs)
    assert payload["max_tokens"] == 512
    assert "max_completion_tokens" not in payload
    assert payload["extra_body"]["thinking"]["type"] == ("enabled" if thinking else "disabled")
    assistant = payload["messages"][1]
    assert assistant["content"] is not None
    if thinking:
        # Reasoning can be empty. Verify faithful replay, not model verbosity.
        assert assistant["reasoning_content"] == first.additional_kwargs.get("reasoning_content", "")
    final = None
    async for chunk in bound.astream(history, config={"callbacks": []}):
        final = chunk if final is None else final + chunk
    assert final is not None and final.content and not final.tool_calls
    assert not (tmp_path / "managed-models").exists()
