"""Tests for deerflow.utils.runtime.get_thread_id."""

from types import SimpleNamespace
from unittest.mock import patch

from deerflow.utils.runtime import get_thread_id


class TestGetThreadId:
    """Tests for get_thread_id() with various runtime shapes."""

    def test_returns_none_when_runtime_is_none(self):
        assert get_thread_id(None) is None

    def test_returns_thread_id_from_context(self):
        runtime = SimpleNamespace(context={"thread_id": "t-1"}, config={})
        assert get_thread_id(runtime) == "t-1"

    def test_returns_none_from_empty_context(self):
        runtime = SimpleNamespace(context={}, config={})
        assert get_thread_id(runtime) is None

    def test_returns_none_from_none_context(self):
        runtime = SimpleNamespace(context=None, config={})
        assert get_thread_id(runtime) is None

    def test_falls_back_to_runtime_config(self):
        runtime = SimpleNamespace(
            context=None,
            config={"configurable": {"thread_id": "t-from-config"}},
        )
        assert get_thread_id(runtime) == "t-from-config"

    def test_context_takes_precedence_over_config(self):
        runtime = SimpleNamespace(
            context={"thread_id": "t-from-context"},
            config={"configurable": {"thread_id": "t-from-config"}},
        )
        assert get_thread_id(runtime) == "t-from-context"

    def test_falls_back_to_get_config(self):
        runtime = SimpleNamespace(context=None, config={})
        with patch("langgraph.config.get_config", return_value={"configurable": {"thread_id": "t-from-lg"}}):
            assert get_thread_id(runtime) == "t-from-lg"

    def test_returns_none_when_get_config_raises_runtime_error(self):
        runtime = SimpleNamespace(context=None, config={})
        with patch("langgraph.config.get_config", side_effect=RuntimeError):
            assert get_thread_id(runtime) is None

    def test_handles_object_without_context_or_config(self):
        runtime = SimpleNamespace()
        assert get_thread_id(runtime) is None

    def test_handles_context_not_dict(self):
        runtime = SimpleNamespace(context="not-a-dict", config={})
        assert get_thread_id(runtime) is None

    def test_config_without_configurable(self):
        runtime = SimpleNamespace(context=None, config={"other_key": "value"})
        assert get_thread_id(runtime) is None

    def test_empty_string_thread_id_treated_as_missing(self):
        runtime = SimpleNamespace(context={"thread_id": ""}, config={})
        assert get_thread_id(runtime) is None

    def test_full_cascade_with_all_levels_failing(self):
        runtime = SimpleNamespace(context=None, config={})
        with patch("langgraph.config.get_config", return_value={"configurable": {}}):
            assert get_thread_id(runtime) is None
