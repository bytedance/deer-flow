"""A deeply nested JSON argument string must degrade, not abort the turn.

The three parsers below hand model-supplied JSON strings to ``json.loads``.
CPython raises :class:`RecursionError` — not ``ValueError`` — once the nesting
passes the interpreter's recursion limit, and none of the call sites wraps the
call, so an unguarded parse takes the whole turn down from a ``before_model``
hook instead of degrading to "unparsable".

``tool_result_meta`` already handles exactly this for tool *results* (#7679);
these are the *argument* parsers.
"""

from __future__ import annotations

import pytest

from deerflow.agents.middlewares import dangling_tool_call_middleware, loop_detection_middleware
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

# Well past sys.getrecursionlimit(); json.loads raises RecursionError on it.
DEEP_ARRAY = "[" * 20000 + "]" * 20000


@pytest.fixture
def middleware() -> ClarificationMiddleware:
    return ClarificationMiddleware()


class TestClarificationOptionsDepth:
    def test_deeply_nested_options_string_is_not_an_exception(self, middleware):
        """The option string becomes one unparsed value, like malformed JSON."""
        options = middleware._normalize_options(DEEP_ARRAY)

        assert isinstance(options, list)
        assert options, "the raw string is kept so the caller can drop it on length"
        assert options[0] == DEEP_ARRAY

    def test_malformed_options_string_takes_the_same_path(self, middleware):
        """Control: the existing degradation is unchanged."""
        assert middleware._normalize_options('[{"a": 1}') == ['[{"a": 1}']

    def test_native_options_still_parse(self, middleware):
        assert middleware._normalize_options('["dev", "prod"]') == ["dev", "prod"]


class TestClarificationFieldsDepth:
    def test_deeply_nested_fields_string_yields_no_form(self, middleware):
        assert middleware._normalize_fields(DEEP_ARRAY) == []


class TestLoopDetectionArgsDepth:
    def test_deeply_nested_args_stay_a_fallback_key(self):
        """Parse failure keeps the raw string as the stable fallback key."""
        args, fallback = loop_detection_middleware._normalize_tool_call_args(DEEP_ARRAY)

        assert args == {}
        assert fallback == DEEP_ARRAY

    def test_native_dict_args_pass_through(self):
        args, fallback = loop_detection_middleware._normalize_tool_call_args({"q": "x"})

        assert args == {"q": "x"}
        assert fallback is None

    def test_json_object_string_parses(self):
        args, fallback = loop_detection_middleware._normalize_tool_call_args('{"q": "x"}')

        assert args == {"q": "x"}
        assert fallback is None


class TestDanglingToolArgumentDepth:
    def test_deeply_nested_arguments_are_not_an_object(self):
        assert dangling_tool_call_middleware._parse_json_object(DEEP_ARRAY) is None

    def test_deeply_nested_arguments_become_an_empty_replay_object(self):
        """The replay value must stay a JSON object, never the raw string."""
        assert dangling_tool_call_middleware._normalize_tool_arguments(DEEP_ARRAY) == "{}"

    def test_shallow_object_still_parses(self):
        assert dangling_tool_call_middleware._normalize_tool_arguments('{"a": 1}') == '{"a": 1}'
