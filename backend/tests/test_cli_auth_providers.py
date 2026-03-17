"""Tests for ClaudeChatModel and CodexChatModel — CLI OAuth providers.

Tests cover model initialization, OAuth detection, message conversion,
tool formatting, response parsing, and factory integration.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models import factory as factory_module
from deerflow.models.credential_loader import is_oauth_token
from deerflow.models.openai_codex_provider import CodexChatModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(
    name: str = "test-codex",
    *,
    use: str = "deerflow.models.openai_codex_provider:CodexChatModel",
    supports_thinking: bool = True,
    supports_reasoning_effort: bool = False,
    when_thinking_enabled: dict | None = None,
    thinking: dict | None = None,
) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use=use,
        model=name,
        supports_thinking=supports_thinking,
        supports_reasoning_effort=supports_reasoning_effort,
        when_thinking_enabled=when_thinking_enabled,
        thinking=thinking,
        supports_vision=False,
    )


# ---------------------------------------------------------------------------
# OAuth token detection
# ---------------------------------------------------------------------------


class TestOAuthTokenDetection:
    def test_oauth_token_detected(self):
        assert is_oauth_token("sk-ant-oat01-abc") is True

    def test_standard_key_not_oauth(self):
        assert is_oauth_token("sk-ant-api03-abc") is False

    def test_empty_not_oauth(self):
        assert is_oauth_token("") is False


# ---------------------------------------------------------------------------
# CodexChatModel — message conversion
# ---------------------------------------------------------------------------


class TestCodexMessageConversion:
    def _make_model(self, monkeypatch=None) -> CodexChatModel:
        if monkeypatch:
            monkeypatch.setattr(
                CodexChatModel,
                "_load_codex_auth",
                lambda self: {"access_token": "test", "account_id": "acc"},
            )
        return CodexChatModel.model_construct(
            model="gpt-5.4",
            max_tokens=100,
            reasoning_effort="medium",
            retry_max_attempts=1,
            _access_token="test",
            _account_id="acc",
        )

    def test_system_message_becomes_instructions(self):
        model = self._make_model()
        instructions, items = model._convert_messages(
            [
                SystemMessage(content="Be helpful"),
                HumanMessage(content="Hi"),
            ]
        )
        assert instructions == "Be helpful"
        assert len(items) == 1
        assert items[0]["role"] == "user"

    def test_default_instructions_when_no_system(self):
        model = self._make_model()
        instructions, items = model._convert_messages([HumanMessage(content="Hi")])
        assert instructions == "You are a helpful assistant."
        assert len(items) == 1

    def test_ai_message_with_tool_calls(self):
        model = self._make_model()
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "get_weather", "args": {"location": "Seoul"}, "id": "call_1"}],
        )
        _, items = model._convert_messages([HumanMessage(content="Hi"), ai_msg])
        function_calls = [i for i in items if i.get("type") == "function_call"]
        assert len(function_calls) == 1
        assert function_calls[0]["name"] == "get_weather"
        assert function_calls[0]["call_id"] == "call_1"

    def test_tool_message_becomes_function_call_output(self):
        model = self._make_model()
        _, items = model._convert_messages(
            [
                HumanMessage(content="Hi"),
                ToolMessage(content="Sunny", tool_call_id="call_1"),
            ]
        )
        outputs = [i for i in items if i.get("type") == "function_call_output"]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_1"
        assert outputs[0]["output"] == "Sunny"


# ---------------------------------------------------------------------------
# CodexChatModel — tool conversion
# ---------------------------------------------------------------------------


class TestCodexToolConversion:
    def _make_model(self) -> CodexChatModel:
        return CodexChatModel.model_construct(model="gpt-5.4")

    def test_openai_function_format(self):
        model = self._make_model()
        tools = model._convert_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "Search the web",
                        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                    },
                }
            ]
        )
        assert len(tools) == 1
        assert tools[0]["name"] == "search"
        assert tools[0]["type"] == "function"

    def test_flat_tool_format(self):
        model = self._make_model()
        tools = model._convert_tools(
            [
                {
                    "name": "bash",
                    "description": "Run command",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        )
        assert len(tools) == 1
        assert tools[0]["name"] == "bash"


# ---------------------------------------------------------------------------
# CodexChatModel — response parsing
# ---------------------------------------------------------------------------


class TestCodexResponseParsing:
    def _make_model(self) -> CodexChatModel:
        return CodexChatModel.model_construct(model="gpt-5.4")

    def test_parses_text_response(self):
        model = self._make_model()
        response = {
            "model": "gpt-5.4",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello!"}], "role": "assistant"}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        result = model._parse_response(response)
        assert result.generations[0].message.content == "Hello!"

    def test_parses_tool_call_response(self):
        model = self._make_model()
        response = {
            "model": "gpt-5.4",
            "output": [{"type": "function_call", "name": "get_weather", "arguments": '{"location":"Tokyo"}', "call_id": "c1"}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        result = model._parse_response(response)
        msg = result.generations[0].message
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "get_weather"
        assert msg.tool_calls[0]["args"] == {"location": "Tokyo"}

    def test_parses_reasoning_summary(self):
        model = self._make_model()
        response = {
            "model": "gpt-5.4",
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Thinking about..."}]},
                {"type": "message", "content": [{"type": "output_text", "text": "Answer"}], "role": "assistant"},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        }
        result = model._parse_response(response)
        msg = result.generations[0].message
        assert msg.content == "Answer"
        assert msg.additional_kwargs["reasoning_content"] == "Thinking about..."

    def test_empty_reasoning_not_in_kwargs(self):
        model = self._make_model()
        response = {
            "model": "gpt-5.4",
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": "Hi"}], "role": "assistant"},
            ],
            "usage": {},
        }
        result = model._parse_response(response)
        assert "reasoning_content" not in result.generations[0].message.additional_kwargs

    def test_token_usage_in_llm_output(self):
        model = self._make_model()
        response = {
            "model": "gpt-5.4",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hi"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        result = model._parse_response(response)
        assert result.llm_output["token_usage"]["prompt_tokens"] == 10
        assert result.llm_output["token_usage"]["completion_tokens"] == 5


# ---------------------------------------------------------------------------
# Factory integration — Codex reasoning_effort mapping
# ---------------------------------------------------------------------------


class TestFactoryCodexReasoningEffort:
    def _patch_factory(self, monkeypatch, app_config: AppConfig):
        monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
        monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CodexChatModel)
        monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)
        # Mock Codex auth so model_post_init doesn't fail
        monkeypatch.setattr(
            "deerflow.models.openai_codex_provider.CodexChatModel._load_codex_auth",
            lambda self: {"access_token": "test", "account_id": "acc"},
        )

    def test_flash_mode_sets_none(self, monkeypatch):
        cfg = _make_app_config([_make_model()])
        self._patch_factory(monkeypatch, cfg)
        model = factory_module.create_chat_model("test-codex", thinking_enabled=False)
        assert model.reasoning_effort == "none"

    def test_thinking_mode_uses_config_default(self, monkeypatch):
        m = _make_model()
        cfg = _make_app_config([m])
        self._patch_factory(monkeypatch, cfg)
        model = factory_module.create_chat_model("test-codex", thinking_enabled=True)
        assert model.reasoning_effort == "medium"

    def test_explicit_effort_passed_through(self, monkeypatch):
        cfg = _make_app_config([_make_model()])
        self._patch_factory(monkeypatch, cfg)
        model = factory_module.create_chat_model("test-codex", thinking_enabled=True, reasoning_effort="high")
        assert model.reasoning_effort == "high"

    def test_xhigh_effort_accepted(self, monkeypatch):
        cfg = _make_app_config([_make_model()])
        self._patch_factory(monkeypatch, cfg)
        model = factory_module.create_chat_model("test-codex", thinking_enabled=True, reasoning_effort="xhigh")
        assert model.reasoning_effort == "xhigh"
