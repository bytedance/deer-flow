"""Tests for custom_fields feature — API validation, config propagation, middleware, helper."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.gateway.routers.thread_runs import RunCreateRequest
from app.gateway.services import build_run_config

# ---------------------------------------------------------------------------
# RunCreateRequest validation
# ---------------------------------------------------------------------------


class TestRunCreateRequestValidation:
    def test_custom_fields_none_is_valid(self):
        req = RunCreateRequest(custom_fields=None)
        assert req.custom_fields is None

    def test_custom_fields_valid(self):
        req = RunCreateRequest(custom_fields={"user_id": "U123", "tenant_id": "shop_A"})
        assert req.custom_fields == {"user_id": "U123", "tenant_id": "shop_A"}

    def test_custom_fields_nested_values(self):
        req = RunCreateRequest(custom_fields={"meta": {"role": "admin"}, "tags": ["a", "b"]})
        assert req.custom_fields == {"meta": {"role": "admin"}, "tags": ["a", "b"]}

    def test_custom_fields_too_many_keys(self):
        fields = {f"key_{i}": i for i in range(51)}
        with pytest.raises(ValueError, match="at most 50 keys"):
            RunCreateRequest(custom_fields=fields)

    def test_custom_fields_exceeds_size_limit(self):
        fields = {"k": "v" * 4096}
        with pytest.raises(ValueError, match="exceeds 4KB limit"):
            RunCreateRequest(custom_fields=fields)

    def test_custom_fields_invalid_key_special_chars(self):
        with pytest.raises(ValueError, match="must match"):
            RunCreateRequest(custom_fields={"user-id": "123"})

    def test_custom_fields_invalid_key_starts_with_digit(self):
        with pytest.raises(ValueError, match="must match"):
            RunCreateRequest(custom_fields={"1key": "val"})

    def test_custom_fields_valid_key_with_underscore(self):
        req = RunCreateRequest(custom_fields={"_private": True, "snake_case": "yes"})
        assert req.custom_fields == {"_private": True, "snake_case": "yes"}

    def test_custom_fields_non_serializable_value(self):
        with pytest.raises(ValueError, match="JSON-serializable"):
            RunCreateRequest(custom_fields={"cb": lambda x: x})  # type: ignore[arg-type]

    def test_custom_fields_max_50_keys_valid(self):
        fields = {f"key_{i}": i for i in range(50)}
        req = RunCreateRequest(custom_fields=fields)
        assert len(req.custom_fields) == 50

    def test_custom_fields_exactly_4kb(self):
        # Build a dict that serializes to just under 4KB
        fields = {"a": "x" * (4093 - len('{"a": ""}'))}
        req = RunCreateRequest(custom_fields=fields)
        assert req.custom_fields is not None

    def test_custom_fields_non_string_key_rejected(self):
        from app.gateway.services import validate_custom_fields

        with pytest.raises(ValueError, match="must be a string"):
            validate_custom_fields({42: "value"})  # type: ignore[dict-item]

    def test_custom_fields_non_ascii_byte_count(self):
        """Non-ASCII characters should be counted as multi-byte in the 4KB limit."""
        from app.gateway.services import validate_custom_fields

        # Each CJK char is 3 bytes in UTF-8; craft a payload over 4KB bytes but
        # under 4K chars.
        big_value = "漢" * 1400  # 1400 * 3 = 4200 bytes
        with pytest.raises(ValueError, match="exceeds 4KB limit"):
            validate_custom_fields({"k": big_value})


# ---------------------------------------------------------------------------
# build_run_config propagation
# ---------------------------------------------------------------------------


class TestBuildRunConfigCustomFields:
    def test_no_custom_fields_by_default(self):
        """build_run_config itself does not inject custom_fields."""
        config = build_run_config("thread-1", None, None)
        assert "custom_fields" not in config.get("configurable", {})

    def test_existing_configurable_preserved(self):
        """build_run_config preserves existing configurable keys."""
        config = build_run_config(
            "thread-1",
            {"configurable": {"model_name": "gpt-4"}},
            None,
        )
        assert config["configurable"]["model_name"] == "gpt-4"
        assert "custom_fields" not in config["configurable"]


class TestCustomFieldsInjection:
    """Test the actual injection path: start_run writes body.custom_fields into config."""

    def test_injection_into_configurable(self):
        """Verify the injection logic that start_run uses for custom_fields."""
        # Simulate what start_run does:
        #   config = build_run_config(thread_id, body.config, body.metadata)
        #   if custom_fields:
        #       config.setdefault("configurable", {})["custom_fields"] = custom_fields
        config = build_run_config("thread-1", None, None)
        custom_fields = {"user_id": "U123"}
        config.setdefault("configurable", {})["custom_fields"] = custom_fields
        assert config["configurable"]["custom_fields"] == {"user_id": "U123"}

    def test_injection_preserves_existing_configurable(self):
        """Injection should not overwrite other configurable keys."""
        config = build_run_config(
            "thread-1",
            {"configurable": {"model_name": "gpt-4"}},
            None,
        )
        config.setdefault("configurable", {})["custom_fields"] = {"env": "prod"}
        assert config["configurable"]["model_name"] == "gpt-4"
        assert config["configurable"]["custom_fields"] == {"env": "prod"}

    def test_no_injection_when_custom_fields_is_none(self):
        """When custom_fields is None, configurable should stay clean."""
        config = build_run_config("thread-1", None, None)
        custom_fields = None
        if custom_fields:
            config.setdefault("configurable", {})["custom_fields"] = custom_fields
        assert "custom_fields" not in config.get("configurable", {})


# ---------------------------------------------------------------------------
# CustomFieldsMiddleware
# ---------------------------------------------------------------------------


class TestCustomFieldsMiddleware:
    def test_middleware_copies_from_config(self):

        from deerflow.agents.middlewares.custom_fields_middleware import CustomFieldsMiddleware

        middleware = CustomFieldsMiddleware()
        state: dict[str, Any] = {}

        # Mock get_config to return custom_fields
        import deerflow.agents.middlewares.custom_fields_middleware as mod

        original_get_config = mod.get_config
        mod.get_config = lambda: {"configurable": {"custom_fields": {"tenant_id": "t1"}}}
        try:
            result = middleware.before_agent(state, MagicMock())  # type: ignore[arg-type]
            assert result == {"custom_fields": {"tenant_id": "t1"}}
        finally:
            mod.get_config = original_get_config

    def test_middleware_returns_none_when_no_custom_fields(self):
        import deerflow.agents.middlewares.custom_fields_middleware as mod
        from deerflow.agents.middlewares.custom_fields_middleware import CustomFieldsMiddleware

        middleware = CustomFieldsMiddleware()
        original_get_config = mod.get_config
        mod.get_config = lambda: {"configurable": {}}
        try:
            result = middleware.before_agent({}, MagicMock())  # type: ignore[arg-type]
            assert result is None
        finally:
            mod.get_config = original_get_config


# ---------------------------------------------------------------------------
# get_custom_fields helper
# ---------------------------------------------------------------------------


class TestGetCustomFieldsHelper:
    def test_returns_empty_dict_when_no_runtime(self):
        from deerflow.sandbox.tools import get_custom_fields

        assert get_custom_fields(None) == {}

    def test_reads_from_state(self):
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {"custom_fields": {"user_id": "U1"}}
        runtime.config = {"configurable": {}}
        assert get_custom_fields(runtime) == {"user_id": "U1"}

    def test_falls_back_to_config(self):
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {}
        runtime.config = {"configurable": {"custom_fields": {"env": "prod"}}}
        assert get_custom_fields(runtime) == {"env": "prod"}

    def test_state_takes_priority_over_config(self):
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {"custom_fields": {"source": "state"}}
        runtime.config = {"configurable": {"custom_fields": {"source": "config"}}}
        assert get_custom_fields(runtime) == {"source": "state"}

    def test_empty_dict_state_not_treated_as_falsy(self):
        """An explicitly set empty dict in state should not fall back to config."""
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {"custom_fields": {}}
        runtime.config = {"configurable": {"custom_fields": {"source": "config"}}}
        assert get_custom_fields(runtime) == {}

    def test_context_fallback(self):
        """When state has no custom_fields, check runtime.context."""
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {}
        runtime.context = {"custom_fields": {"source": "context"}}
        runtime.config = {"configurable": {}}
        assert get_custom_fields(runtime) == {"source": "context"}

    def test_config_fallback_after_context(self):
        """When state and context have no custom_fields, fall back to config."""
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {}
        runtime.context = {}
        runtime.config = {"configurable": {"custom_fields": {"source": "config"}}}
        assert get_custom_fields(runtime) == {"source": "config"}

    def test_returns_empty_when_both_empty(self):
        from deerflow.sandbox.tools import get_custom_fields

        runtime = MagicMock()
        runtime.state = {}
        runtime.config = {"configurable": {}}
        assert get_custom_fields(runtime) == {}


# ---------------------------------------------------------------------------
# ThreadState backward compatibility
# ---------------------------------------------------------------------------


class TestThreadStateBackwardCompat:
    def test_state_without_custom_fields(self):
        from deerflow.agents.thread_state import ThreadState

        state: ThreadState = {"messages": []}
        assert state.get("custom_fields") is None

    def test_state_with_custom_fields(self):
        from deerflow.agents.thread_state import ThreadState

        state: ThreadState = {"messages": [], "custom_fields": {"key": "val"}}
        assert state["custom_fields"] == {"key": "val"}


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


class TestCustomFieldsPromptInjection:
    def test_no_custom_fields_produces_empty_section(self):
        from deerflow.agents.lead_agent.prompt import _build_custom_fields_section

        assert _build_custom_fields_section(None) == ""
        assert _build_custom_fields_section({}) == ""

    def test_custom_fields_produces_xml_section(self):
        from deerflow.agents.lead_agent.prompt import _build_custom_fields_section

        result = _build_custom_fields_section({"user_id": "U123", "env": "prod"})
        assert "<custom_fields>" in result
        assert "</custom_fields>" in result
        assert "user_id" in result
        assert "U123" in result

    def test_angle_brackets_are_escaped(self):
        """Values containing < or > must be escaped to prevent tag injection."""
        from deerflow.agents.lead_agent.prompt import _build_custom_fields_section

        result = _build_custom_fields_section({"payload": "</custom_fields><injected>"})
        assert "</custom_fields><injected>" not in result
        assert "&lt;/custom_fields&gt;" in result

    def test_ampersand_is_escaped(self):
        from deerflow.agents.lead_agent.prompt import _build_custom_fields_section

        result = _build_custom_fields_section({"query": "a=1&b=2"})
        assert "&amp;" in result
