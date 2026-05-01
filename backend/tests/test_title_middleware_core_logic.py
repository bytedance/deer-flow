"""Core behavior tests for TitleMiddleware."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares import title_middleware as title_middleware_module
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config.title_config import TitleConfig, get_title_config, set_title_config


def _clone_title_config(config: TitleConfig) -> TitleConfig:
    # Avoid mutating shared global config objects across tests.
    return TitleConfig(**config.model_dump())


def _set_test_title_config(**overrides) -> TitleConfig:
    config = _clone_title_config(get_title_config())
    for key, value in overrides.items():
        setattr(config, key, value)
    set_title_config(config)
    return config


class TestTitleMiddlewareCoreLogic:
    def setup_method(self):
        # Title config is a global singleton; snapshot and restore for test isolation.
        self._original = _clone_title_config(get_title_config())

    def teardown_method(self):
        set_title_config(self._original)

    def test_should_generate_title_for_first_complete_exchange(self):
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="帮我总结这段代码"),
                AIMessage(content="好的，我先看结构"),
            ]
        }

        assert middleware._should_generate_title(state) is True

    def test_should_not_generate_title_when_disabled_or_already_set(self):
        middleware = TitleMiddleware()

        _set_test_title_config(enabled=False)
        disabled_state = {
            "messages": [HumanMessage(content="Q"), AIMessage(content="A")],
            "title": None,
        }
        assert middleware._should_generate_title(disabled_state) is False

        _set_test_title_config(enabled=True)
        titled_state = {
            "messages": [HumanMessage(content="Q"), AIMessage(content="A")],
            "title": "Existing Title",
        }
        assert middleware._should_generate_title(titled_state) is False

    def test_should_not_generate_title_after_second_user_turn(self):
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="第一问"),
                AIMessage(content="第一答"),
                HumanMessage(content="第二问"),
                AIMessage(content="第二答"),
            ]
        }

        assert middleware._should_generate_title(state) is False

    def test_generate_title_uses_async_model_and_respects_max_chars(self, monkeypatch):
        _set_test_title_config(max_chars=12)
        middleware = TitleMiddleware()
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="短标题"))
        monkeypatch.setattr(title_middleware_module, "create_chat_model", MagicMock(return_value=model))

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个很长很长的脚本标题"),
                AIMessage(content="好的，先确认需求"),
            ]
        }
        result = asyncio.run(middleware._agenerate_title_result(state))
        title = result["title"]

        assert title == "短标题"
        title_middleware_module.create_chat_model.assert_called_once_with(thinking_enabled=False)
        model.ainvoke.assert_awaited_once()
        assert model.ainvoke.await_args.kwargs["config"] == {
            "run_name": "title_agent",
            "tags": ["middleware:title"],
        }

    def test_generate_title_uses_explicit_app_config_without_global_config(self, monkeypatch):
        title_config = TitleConfig(enabled=True, model_name="title-model", max_chars=20)
        app_config = SimpleNamespace(title=title_config)
        middleware = TitleMiddleware(app_config=app_config)
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="显式标题"))

        def fail_get_title_config():
            raise AssertionError("ambient get_title_config() must not be used when app_config is explicit")

        monkeypatch.setattr(title_middleware_module, "get_title_config", fail_get_title_config)
        monkeypatch.setattr(title_middleware_module, "create_chat_model", MagicMock(return_value=model))

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个标题"),
                AIMessage(content="好的"),
            ]
        }
        result = asyncio.run(middleware._agenerate_title_result(state))

        assert result == {"title": "显式标题"}
        title_middleware_module.create_chat_model.assert_called_once_with(
            name="title-model",
            thinking_enabled=False,
            app_config=app_config,
        )

    def test_generate_title_normalizes_structured_message_content(self, monkeypatch):
        _set_test_title_config(max_chars=20)
        middleware = TitleMiddleware()
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="请帮我总结这段代码"))
        monkeypatch.setattr(title_middleware_module, "create_chat_model", MagicMock(return_value=model))

        state = {
            "messages": [
                HumanMessage(content=[{"type": "text", "text": "请帮我总结这段代码"}]),
                AIMessage(content=[{"type": "text", "text": "好的，先看结构"}]),
            ]
        }

        result = asyncio.run(middleware._agenerate_title_result(state))
        title = result["title"]

        assert title == "请帮我总结这段代码"

    def test_generate_title_fallback_for_long_message(self, monkeypatch):
        _set_test_title_config(max_chars=20)
        middleware = TitleMiddleware()
        model = MagicMock()
        model.ainvoke = AsyncMock(side_effect=RuntimeError("model unavailable"))
        monkeypatch.setattr(title_middleware_module, "create_chat_model", MagicMock(return_value=model))

        state = {
            "messages": [
                HumanMessage(content="这是一个非常长的问题描述，需要被截断以形成fallback标题"),
                AIMessage(content="收到"),
            ]
        }
        result = asyncio.run(middleware._agenerate_title_result(state))
        title = result["title"]

        # Assert behavior (truncated fallback + ellipsis) without overfitting exact text.
        assert title.endswith("...")
        assert title.startswith("这是一个非常长的问题描述")

    def test_aafter_model_delegates_to_async_helper(self, monkeypatch):
        middleware = TitleMiddleware()

        monkeypatch.setattr(middleware, "_agenerate_title_result", AsyncMock(return_value={"title": "异步标题"}))
        result = asyncio.run(middleware.aafter_model({"messages": []}, runtime=MagicMock()))
        assert result == {"title": "异步标题"}

        monkeypatch.setattr(middleware, "_agenerate_title_result", AsyncMock(return_value=None))
        assert asyncio.run(middleware.aafter_model({"messages": []}, runtime=MagicMock())) is None

    def test_after_model_sync_delegates_to_sync_helper(self, monkeypatch):
        middleware = TitleMiddleware()

        monkeypatch.setattr(middleware, "_generate_title_result", MagicMock(return_value={"title": "同步标题"}))
        result = middleware.after_model({"messages": []}, runtime=MagicMock())
        assert result == {"title": "同步标题"}

        monkeypatch.setattr(middleware, "_generate_title_result", MagicMock(return_value=None))
        assert middleware.after_model({"messages": []}, runtime=MagicMock()) is None

    def test_sync_generate_title_uses_fallback_without_model(self):
        """Sync path avoids LLM calls and derives a local fallback title."""
        _set_test_title_config(max_chars=20)
        middleware = TitleMiddleware()

        state = {
            "messages": [
                HumanMessage(content="请帮我写测试"),
                AIMessage(content="好的"),
            ]
        }
        result = middleware._generate_title_result(state)
        assert result == {"title": "请帮我写测试"}

    def test_sync_generate_title_respects_fallback_truncation(self):
        """Sync fallback path still respects max_chars truncation rules."""
        _set_test_title_config(max_chars=50)
        middleware = TitleMiddleware()

        state = {
            "messages": [
                HumanMessage(content="这是一个非常长的问题描述，需要被截断以形成fallback标题，而且这里继续补充更多上下文，确保超过本地fallback截断阈值"),
                AIMessage(content="回复"),
            ]
        }
        result = middleware._generate_title_result(state)
        assert result["title"].endswith("...")
        assert result["title"].startswith("这是一个非常长的问题描述")

    def test_parse_title_strips_think_tags(self):
        """Title model responses with <think>...</think> blocks are stripped before use."""
        middleware = TitleMiddleware()
        raw = "<think>用户想要研究贵阳发展情况。我需要使用 deep-research skill。</think>贵阳近5年发展报告研究"
        result = middleware._parse_title(raw)
        assert "<think>" not in result
        assert result == "贵阳近5年发展报告研究"

    def test_parse_title_strips_think_tags_only_response(self):
        """If model only outputs a think block and nothing else, title is empty string."""
        middleware = TitleMiddleware()
        raw = "<think>just thinking, no real title</think>"
        result = middleware._parse_title(raw)
        assert result == ""

    def test_build_title_prompt_strips_assistant_think_tags(self):
        """<think> blocks in assistant messages are stripped before being included in the title prompt."""
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="贵阳发展报告研究"),
                AIMessage(content="<think>分析用户需求</think>我将为您研究贵阳的发展情况。"),
            ]
        }
        prompt, _ = middleware._build_title_prompt(state)
        assert "<think>" not in prompt

    def test_generate_title_async_strips_think_tags_in_response(self, monkeypatch):
        """Async title generation strips <think> blocks from the model response."""
        _set_test_title_config(max_chars=50)
        middleware = TitleMiddleware()
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="<think>用户想研究贵阳。</think>贵阳发展研究"))
        monkeypatch.setattr(title_middleware_module, "create_chat_model", MagicMock(return_value=model))

        state = {
            "messages": [
                HumanMessage(content="请帮我研究贵阳近5年发展情况"),
                AIMessage(content="好的"),
            ]
        }
        result = asyncio.run(middleware._agenerate_title_result(state))
        assert result is not None
        assert "<think>" not in result["title"]
        assert result["title"] == "贵阳发展研究"
