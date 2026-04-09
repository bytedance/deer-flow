"""Regression test for issue #1602.

This exercises the real DeerFlow client/agent/stream pipeline with a local
fake ChatOpenAI implementation. The fake model only emits ``usage_metadata``
when ``stream_usage`` is enabled, so the test proves that the factory default
reaches the streaming path and that the client surfaces usage in events.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.client import DeerFlowClient
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


class FakeStreamingChatOpenAI(ChatOpenAI):
    """OpenAI-compatible test double that makes usage reporting observable."""

    captured_inits: ClassVar[list[dict[str, Any]]] = []
    stream_called: ClassVar[bool] = False

    def __init__(self, **kwargs):
        self.__class__.captured_inits.append(dict(kwargs))
        super().__init__(**kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="fake final answer"))], llm_output={})

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        self.__class__.stream_called = True
        usage = {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18} if getattr(self, "stream_usage", False) else None
        yield ChatGenerationChunk(message=AIMessageChunk(content="fake final answer", usage_metadata=usage))


def _make_config() -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="fake-openai-compatible",
                display_name="Fake OpenAI Compatible",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="fake-openai-compatible",
                base_url="https://example.invalid/v1",
                api_key="test-key",
                max_tokens=256,
                temperature=0.0,
                supports_thinking=False,
                supports_reasoning_effort=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _install_fake_model(monkeypatch) -> None:
    from deerflow.config import app_config as app_config_module
    from deerflow.config import memory_config as memory_config_module
    from deerflow.config import summarization_config as summarization_config_module
    from deerflow.config import title_config as title_config_module
    from deerflow.models import factory as factory_module

    monkeypatch.setattr(app_config_module, "_app_config", _make_config())
    monkeypatch.setattr(app_config_module, "_app_config_is_custom", True)
    monkeypatch.setattr(title_config_module, "_title_config", title_config_module.TitleConfig(enabled=False))
    monkeypatch.setattr(memory_config_module, "_memory_config", memory_config_module.MemoryConfig(enabled=False))
    monkeypatch.setattr(
        summarization_config_module,
        "_summarization_config",
        summarization_config_module.SummarizationConfig(enabled=False),
    )

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: FakeStreamingChatOpenAI)
    monkeypatch.setattr(factory_module, "ChatOpenAI", FakeStreamingChatOpenAI)


class _FakeAgent:
    def __init__(self, model):
        self.model = model

    def stream(self, state, config=None, context=None, stream_mode="values"):
        usage = None
        content_parts: list[str] = []

        for chunk in self.model.stream(state["messages"]):
            chunk_content = chunk.content if isinstance(chunk.content, str) else ""
            if chunk_content:
                content_parts.append(chunk_content)
            if getattr(chunk, "usage_metadata", None):
                usage = chunk.usage_metadata

        yield {
            "messages": [
                *state["messages"],
                AIMessage(content="".join(content_parts), usage_metadata=usage),
            ]
        }


def test_stream_usage_reaches_real_client_stream(monkeypatch):
    """A real DeerFlow stream should surface usage metadata for OpenAI-compatible models."""
    _install_fake_model(monkeypatch)

    monkeypatch.setattr("deerflow.client.create_agent", lambda **kwargs: _FakeAgent(kwargs["model"]))

    FakeStreamingChatOpenAI.captured_inits.clear()
    FakeStreamingChatOpenAI.stream_called = False
    client = DeerFlowClient(checkpointer=None, thinking_enabled=False)
    events = list(client.stream("Reply with exactly: hello", thread_id="issue-1602-verify"))

    ai_events = [event for event in events if event.type == "messages-tuple" and event.data.get("type") == "ai"]
    end_event = next((event for event in events if event.type == "end"), None)

    assert any(kwargs.get("stream_usage") is True for kwargs in FakeStreamingChatOpenAI.captured_inits)
    assert FakeStreamingChatOpenAI.stream_called is True
    assert any("usage_metadata" in event.data for event in ai_events)
    assert end_event is not None
    assert end_event.data.get("usage", {}).get("total_tokens", 0) > 0
