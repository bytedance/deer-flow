"""Literal think tags inside JSON values must survive structured parsing."""

from app.gateway.routers.suggestions import _parse_json_string_list
from deerflow.runtime.goal import parse_goal_evaluation_response
from deerflow.utils.llm_text import strip_think_blocks_outside_json_strings


def test_suggestions_keep_a_complete_literal_tag_inside_a_string():
    assert _parse_json_string_list('["Explain <think>example</think>"]') == ["Explain <think>example</think>"]


def test_suggestions_keep_an_unclosed_literal_tag_inside_a_string():
    assert _parse_json_string_list('["Explain <think>"]') == ["Explain <think>"]


def test_suggestions_strip_reasoning_before_the_list():
    raw = '<think>maybe ["wrong"]</think>\n```json\n["right"]\n```'

    assert _parse_json_string_list(raw) == ["right"]


def test_suggestions_do_not_take_a_json_example_inside_reasoning():
    raw = '<think>["wrong"]</think>["right"]'

    assert _parse_json_string_list(raw) == ["right"]


def test_goal_keeps_a_complete_literal_tag_in_the_reason():
    evaluation = parse_goal_evaluation_response('{"satisfied": true, "reason": "Found <think>example</think>"}')

    assert evaluation["reason"] == "Found <think>example</think>"


def test_goal_keeps_an_unclosed_literal_tag_in_the_reason():
    evaluation = parse_goal_evaluation_response('{"satisfied": false, "reason": "Found <think>"}')

    assert evaluation["reason"] == "Found <think>"


def test_goal_strips_reasoning_before_the_object():
    evaluation = parse_goal_evaluation_response('<think>maybe {"satisfied": false}</think>{"satisfied": true, "reason": "ok"}')

    assert evaluation["satisfied"] is True
    assert evaluation["reason"] == "ok"


def test_helper_keeps_tags_inside_strings_and_strips_them_outside():
    payload = '{"a": "<think>x</think>", "b": "<think>"}'

    assert strip_think_blocks_outside_json_strings(payload) == payload
    assert strip_think_blocks_outside_json_strings('<think>reasoning</think>{"a": 1}') == '{"a": 1}'


def test_goal_strips_a_reasoning_block_that_follows_prose():
    evaluation = parse_goal_evaluation_response('Hmm. <think>{"satisfied": false}</think>{"satisfied": true, "reason": "ok"}')

    assert evaluation["satisfied"] is True
    assert evaluation["reason"] == "ok"


def test_suggestions_strip_a_reasoning_block_that_follows_prose():
    assert _parse_json_string_list('Okay. <think>["wrong"]</think>["right"]') == ["right"]


def test_suggestions_drop_trailing_prose_after_an_unclosed_block():
    # The old whole-text stripper truncated here; keep that so a trailing ']'
    # cannot become the parsers' rfind target.
    assert _parse_json_string_list('["Q1"] <think>tail mentioning ]') == ["Q1"]


def test_goal_drops_trailing_prose_after_an_unclosed_block():
    evaluation = parse_goal_evaluation_response('{"satisfied": true, "reason": "ok"} <think>tail mentioning }')

    assert evaluation["satisfied"] is True
    assert evaluation["reason"] == "ok"


def test_trailing_stray_quote_cannot_mask_a_later_reasoning_block():
    assert _parse_json_string_list('["Q1"] stray " quote <think>tail ]') == ["Q1"]
