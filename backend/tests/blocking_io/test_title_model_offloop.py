"""Title generation must build its provider off the Gateway event loop.

Inside a graph run, ``aafter_model`` builds the configured title model inline.
``create_chat_model`` can read local CLI credentials (Codex ``auth.json``,
Claude Code credential files) while it is constructed, so every other request
on the shared loop waited for that read. The real Codex provider is built under
the strict gate; tracing and inference stay offline.
"""

import json
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares import title_middleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.models import factory
from deerflow.models.openai_codex_provider import CodexChatModel

pytestmark = pytest.mark.asyncio

_TITLE = "Deployment plan"


def _codex_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture-codex", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"}],
            "title": {"model_name": "fixture-codex"},
        }
    )


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """Real Codex construction (credential file IO included); offline tracing and inference."""
    credentials = tmp_path / "auth.json"
    credentials.write_text(json.dumps({"access_token": "fixture-token", "account_id": "fixture-account"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_AUTH_PATH", str(credentials))
    monkeypatch.setattr(factory, "build_tracing_callbacks", lambda **kwargs: [])
    state = SimpleNamespace(construction_thread=None, calls=[])

    async def invoke(model, messages, *, config):
        state.calls.append((model, threading.get_ident()))
        return AIMessage(content=_TITLE)

    monkeypatch.setattr(CodexChatModel, "ainvoke", invoke)
    return state


async def test_title_model_is_built_off_the_event_loop(codex, monkeypatch):
    middleware = TitleMiddleware(app_config=_codex_config())
    real_create = title_middleware.create_chat_model

    def recording_create(*args, **kwargs):
        codex.construction_thread = threading.get_ident()
        return real_create(*args, **kwargs)

    monkeypatch.setattr(title_middleware, "create_chat_model", recording_create)
    state = {
        "messages": [
            HumanMessage(content="Plan the eu-west-2 deployment.", id="user"),
            AIMessage(content="The plan is ready.", id="assistant"),
        ]
    }

    result = await middleware._agenerate_title_result(state)

    # On the loop the gate rejects the credential read, the broad fallback in
    # _agenerate_title_result swallows it, and the local title replaces the
    # configured model's title.
    assert result == {"title": _TITLE}
    assert len(codex.calls) == 1
    assert codex.construction_thread is not None
    assert codex.construction_thread != threading.get_ident()
    # Inference itself still awaits on the loop once the provider exists.
    assert codex.calls[0][1] == threading.get_ident()
