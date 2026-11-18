"""Auto-compaction must build the summary provider off the Gateway event loop.

Compaction runs from ``abefore_model``/``aafter_model`` on the shared loop, and
``create_chat_model`` can read local CLI credentials while it is constructed
(Codex ``auth.json``, Claude Code credential files). The real Codex provider is
built here under the strict gate; tracing and inference stay offline.
"""

import json
import threading
from types import SimpleNamespace

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.models import factory
from deerflow.models.openai_codex_provider import CodexChatModel

pytestmark = pytest.mark.asyncio

_SUMMARY = "Configured summary."


class AnchorModel(BaseChatModel):
    """The run model; used here only to prove the fallback was not reached."""

    calls: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "summarization-offloop-anchor"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append("anchor")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Anchor summary."))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _codex_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture-codex", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"}],
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

    async def invoke(model, messages, config=None, **kwargs):
        state.calls.append((model, threading.get_ident()))
        return AIMessage(content=_SUMMARY)

    monkeypatch.setattr(CodexChatModel, "ainvoke", invoke)
    return state


def _middleware(anchor):
    return DeerFlowSummarizationMiddleware(
        model=anchor,
        trigger=("messages", 100),
        keep=("messages", 1),
        trim_tokens_to_summarize=4096,
        summary_prompt="{messages}",
        app_config=_codex_config(),
        configured_model_name="fixture-codex",
        run_model_name="fixture-codex",
        anchor_model_name="offline",
    )


async def test_auto_compaction_builds_summary_model_off_loop(codex, monkeypatch):
    anchor = AnchorModel()
    middleware = _middleware(anchor)
    real_build = DeerFlowSummarizationMiddleware._build_model

    def recording_build(self, name):
        codex.construction_thread = threading.get_ident()
        return real_build(self, name)

    monkeypatch.setattr(DeerFlowSummarizationMiddleware, "_build_model", recording_build)

    summary = await middleware._asummarize_with([HumanMessage(content="old question", id="user"), AIMessage(content="old answer", id="assistant")])

    # On the loop the gate rejects the credential read, the candidate is cached
    # as unavailable, and compaction returns no summary at all.
    assert summary == _SUMMARY
    assert len(codex.calls) == 1
    assert codex.construction_thread is not None
    assert codex.construction_thread != threading.get_ident()
    # Inference itself still awaits on the loop once the provider exists.
    assert codex.calls[0][1] == threading.get_ident()
    # The configured model was usable, so the run-model anchor never ran.
    assert anchor.calls == []
