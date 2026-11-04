"""Tool-call argument normalization must tolerate deeply nested JSON.

A model (or a replayed history) can hand the middlewares a JSON string or a
Python structure nested beyond the interpreter's recursion limit. These
payloads are unusable for loop detection or replay repair, but they must not
abort the graph with ``RecursionError``; the parsers fall back to the same
"opaque" path they use for any unparsable input.
"""

from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.dangling_tool_call_middleware import (
    _normalize_tool_arguments,
    _parse_json_object,
)
from deerflow.agents.middlewares.loop_detection_middleware import (
    _hash_tool_calls,
    _normalize_tool_call_args,
)

# Above the JSON C parser's recursion limit on CPython 3.12 for the platforms this
# repository builds on (Linux/macOS 64-bit allow roughly 8,000 levels).
DEEP_DEPTH = 20_000
DEEP_ARRAY = "[" * DEEP_DEPTH + "]" * DEEP_DEPTH


def _deep_dict(depth: int = DEEP_DEPTH) -> dict:
    root: dict = {}
    node = root
    for _ in range(depth):
        child: dict = {}
        node["x"] = child
        node = child
    return root


def _deep_list(depth: int = DEEP_DEPTH) -> list:
    root: list = []
    node = root
    for _ in range(depth):
        child: list = []
        node.append(child)
        node = child
    return root


def test_loop_detection_keeps_a_deep_json_string_as_opaque_args():
    assert _normalize_tool_call_args(DEEP_ARRAY) == ({}, DEEP_ARRAY)


def test_loop_detection_keeps_deep_structures_as_opaque_args():
    assert _normalize_tool_call_args(_deep_list()) == ({}, None)


def test_loop_detection_hash_keeps_deep_dict_args_serializable():
    assert _hash_tool_calls([{"name": "bash", "args": _deep_dict()}]) is not None


def test_clarification_options_keep_a_deep_json_string_as_one_option():
    assert ClarificationMiddleware._normalize_options(None, DEEP_ARRAY) == [DEEP_ARRAY]


def test_clarification_native_deep_options_are_skipped():
    assert ClarificationMiddleware._normalize_options(None, [_deep_list()]) == []


def test_clarification_dict_options_flatten_without_recursion():
    assert ClarificationMiddleware._flatten_dict_option_values(_deep_dict()) == []


def test_loop_detection_read_file_key_tolerates_a_deep_path():
    assert _hash_tool_calls([{"name": "read_file", "args": {"path": _deep_list()}}]) is not None


def test_dangling_parser_rejects_a_deep_json_string():
    assert _parse_json_object(DEEP_ARRAY) is None


def test_dangling_arguments_repair_falls_back_to_empty_object():
    assert _normalize_tool_arguments(DEEP_ARRAY) == "{}"
    assert _normalize_tool_arguments(_deep_dict()) == "{}"
