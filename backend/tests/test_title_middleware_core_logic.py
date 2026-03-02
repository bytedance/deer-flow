"""Core behavior tests for TitleMiddleware."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.title_middleware import TitleMiddleware
from src.config.title_config import TitleConfig, get_title_config, set_title_config


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

    def test_generate_title_trims_quotes_and_respects_max_chars(self, monkeypatch):
        _set_test_title_config(max_chars=12)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.invoke.return_value = MagicMock(content='"A very long generated title"')
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的，先确认需求"),
            ]
        }
        title = middleware._generate_title(state)

        assert '"' not in title
        assert "'" not in title
        assert len(title) == 12

    def test_generate_title_fallback_when_model_fails(self, monkeypatch):
        _set_test_title_config(max_chars=20)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.invoke.side_effect = RuntimeError("LLM unavailable")
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="这是一个非常长的问题描述，需要被截断以形成fallback标题"),
                AIMessage(content="收到"),
            ]
        }
        title = middleware._generate_title(state)

        # Assert behavior (truncated fallback + ellipsis) without overfitting exact text.
        assert title.endswith("...")
        assert title.startswith("这是一个非常长的问题描述")

    def test_after_agent_returns_title_only_when_needed(self, monkeypatch):
        middleware = TitleMiddleware()
        monkeypatch.setattr(middleware, "_should_generate_title", lambda state: True)
        monkeypatch.setattr(middleware, "_generate_title", lambda state: "核心逻辑回归")

        result = middleware.after_agent({"messages": []}, runtime=MagicMock())

        assert result == {"title": "核心逻辑回归"}

        monkeypatch.setattr(middleware, "_should_generate_title", lambda state: False)
        assert middleware.after_agent({"messages": []}, runtime=MagicMock()) is None
