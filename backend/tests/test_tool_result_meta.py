"""Tests for tool_result_meta normalization logic."""

from __future__ import annotations

import json
import os

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_result_meta import (
    TOOL_META_KEY,
    TOOL_RESULT_ERROR_TYPES,
    ToolResultMeta,
    normalize_tool_message,
    normalize_tool_result,
    stamp_exception_meta,
)


def _make_msg(content: str, *, status: str = "success", kwargs: dict[str, object] | None = None) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id="tc-1",
        name="test_tool",
        status=status,
        additional_kwargs=kwargs or {},
    )


def _meta(msg: ToolMessage) -> dict[str, object]:
    return msg.additional_kwargs[TOOL_META_KEY]


# ---------------------------------------------------------------------------
# Already-stamped messages are not overwritten


def test_existing_meta_is_preserved():
    existing = {"status": "success", "source": "custom"}
    msg = _make_msg("hello", kwargs={TOOL_META_KEY: existing})
    result = normalize_tool_message(msg)
    assert result.additional_kwargs[TOOL_META_KEY] is existing


@pytest.mark.parametrize("name", ["bash", "bash_tool"])
@pytest.mark.parametrize("content", ["\nExit Code: 1", "12 passed, 1 error\nExit Code: 7", "Command exited with code 3", "partial output\nExit Code: -9", "Command timed out\nExit Code: 124"])
def test_bash_nonzero_exit_marker_is_a_recoverable_error(name, content):
    msg = ToolMessage(content=content, tool_call_id="bash-1", name=name)
    normalize_tool_message(msg)
    assert _meta(msg) == {
        "status": "error",
        "error_type": "unknown",
        "recoverable_by_model": True,
        "recommended_next_action": "try_alternative",
        "source": "content_analysis",
    }


def test_bash_nonzero_exit_repairs_legacy_analysis_success_without_changing_producer_meta():
    legacy = {"status": "success", "source": "content_analysis"}
    msg = ToolMessage(content="\nExit Code: 1", tool_call_id="bash-1", name="bash", additional_kwargs={TOOL_META_KEY: legacy, "deerflow_tool_receipt": {"status": "success"}})
    normalize_tool_message(msg)
    assert _meta(msg)["status"] == "error"
    assert legacy == {"status": "success", "source": "content_analysis"}
    assert msg.additional_kwargs["deerflow_tool_receipt"]["status"] == "success"


@pytest.mark.parametrize("source", ["tool_return", "exception", "progress_middleware", "custom"])
def test_bash_nonzero_exit_preserves_explicit_producer_meta(source):
    existing = {"status": "success", "source": source}
    msg = ToolMessage(content="\nExit Code: 1", tool_call_id="bash-1", name="bash", additional_kwargs={TOOL_META_KEY: existing})
    assert _meta(normalize_tool_message(msg)) is existing


@pytest.mark.parametrize(
    "name,content",
    [
        ("bash", "ok\nExit Code: 0"),
        ("bash", "Command exited with code 0"),
        ("bash", "Exit Code: 1\nordinary final output"),
        ("bash", "validating error path: Command exited with code 3\n5 passed"),
        ("bash", "A document says Exit Code: 1"),
        ("read_file", "\nExit Code: 1"),
        ("web_fetch", "Command exited with code 3"),
    ],
)
def test_bash_exit_marker_does_not_classify_other_tool_content_or_prose(name, content):
    msg = ToolMessage(content=content, tool_call_id="call-1", name=name)
    assert _meta(normalize_tool_message(msg))["status"] == "success"


def test_bash_exit_status_does_not_classify_arbitrary_stdout_as_an_auth_error():
    msg = ToolMessage(content="Processed row 403\nExit Code: 1", tool_call_id="bash-1", name="bash")
    assert _meta(normalize_tool_message(msg))["error_type"] == "unknown"


@pytest.mark.skipif(os.name == "nt", reason="POSIX inert shell command")
@pytest.mark.parametrize(
    "command,output,status",
    [
        (": attempt-0; exit 1", "\nExit Code: 1", "error"),
        ("printf 'x\\n' | grep z", "\nExit Code: 1", "error"),
        ("printf 'x\\n' | grep z || true", "(no output)", "success"),
    ],
)
def test_native_bash_exit_is_stamped_before_receipt(monkeypatch, command, output, status):
    from types import SimpleNamespace

    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
    from deerflow.sandbox.local import local_sandbox

    monkeypatch.setattr(local_sandbox, "build_sandbox_env", lambda _injected: {"PATH": os.defpath})
    actual = local_sandbox.LocalSandbox("exit-status-probe").execute_command(command, timeout=5)
    assert actual == output
    request = SimpleNamespace(tool_call={"id": "bash-1", "name": "bash", "args": {"command": command}})
    errors = ToolErrorHandlingMiddleware()
    result = ToolReceiptMiddleware().wrap_tool_call(request, lambda req: errors.wrap_tool_call(req, lambda _: ToolMessage(content=actual, tool_call_id="bash-1", name="bash")))
    assert _meta(result)["status"] == status
    assert _meta(result)["recoverable_by_model"] is True
    assert result.additional_kwargs["deerflow_tool_receipt"]["status"] == status


# ---------------------------------------------------------------------------
# Error prefix (tool_return path)


@pytest.mark.parametrize(
    "snippet,expected_type",
    [
        ("Error: 401 unauthorized", "auth"),
        ("Error: permission denied for path", "permission"),
        ("Error: 429 rate limit exceeded", "rate_limited"),
        ("Error: connection timeout", "transient"),
        ("Error: tool not configured", "config"),
        ("Error: no results found for query", "no_results"),
        ("Error: file not found", "not_found"),
        ("Error: internal error 500", "internal"),
        ("Error: something completely unexpected happened", "unknown"),
    ],
)
def test_error_prefix_classification(snippet: str, expected_type: str):
    msg = _make_msg(snippet, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == expected_type
    assert m["error_type"] in TOOL_RESULT_ERROR_TYPES
    assert m["source"] == "tool_return"


def test_auth_error_is_unrecoverable_and_stop():
    msg = _make_msg("Error: invalid api key", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["recoverable_by_model"] is False
    assert m["recommended_next_action"] == "stop"


def test_no_api_key_is_config_not_auth():
    # Distinguish "missing key" (config) from "wrong key" (auth):
    # - auth rule keyword: "invalid api key"  (key provided but rejected)
    # - config rule keyword: "no api key"      (key not set at all)
    # The two phrases do not overlap, so rule order does not affect this particular
    # case.  This test documents the semantic distinction — a missing API key is a
    # configuration issue, not an authentication failure.
    msg = _make_msg("Error: no api key configured", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["error_type"] == "config", "missing API key is a config issue, not auth"
    assert m["recommended_next_action"] == "stop"
    assert m["recoverable_by_model"] is False


def test_rate_limited_error_suggests_summarize():
    msg = _make_msg("Error: rate limited", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["recommended_next_action"] == "summarize"
    assert m["recoverable_by_model"] is False


def test_no_results_suggests_rewrite_query():
    msg = _make_msg("Error: no results found", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["recoverable_by_model"] is True
    assert m["recommended_next_action"] == "rewrite_query"


# ---------------------------------------------------------------------------
# Non-standard error path (status="error", no "Error:" prefix)


def test_nonstd_error_status_classifies_from_content():
    # Tools that return status="error" without the "Error:" prefix are tool_return, not exception.
    # Actual exceptions are pre-stamped by stamp_exception_meta and exit normalize_tool_message early.
    msg = _make_msg("ConnectionError: connection refused", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["source"] == "tool_return"
    assert m["error_type"] == "transient"


def test_nonstd_error_status_timeout_content():
    msg = _make_msg("timeout occurred", status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["source"] == "tool_return"
    assert m["error_type"] == "transient"


def test_nonstd_error_status_json_classifies_from_error_field():
    # When status="error" and content is JSON, classification must use only the "error"
    # field value — not keywords that appear in other fields like "query".
    content = '{"error": "api limit exceeded", "query": "connection test timeout"}'
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["source"] == "tool_return"
    # "connection" and "timeout" in query must not trigger transient; the error field
    # "api limit exceeded" doesn't match any rule → unknown.
    assert m["error_type"] == "unknown"


def test_nonstd_error_status_json_no_error_key_is_unknown():
    # JSON with no 'error' key must NOT be classified from other field values.
    # Previously, {"message": "connection refused"} would be passed to _classify_error_text
    # and match the transient rule via "connection"; now the full JSON is treated as unknown.
    content = '{"message": "connection refused"}'
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "unknown", "JSON dict with no 'error' key must resolve to unknown"


def test_nonstd_error_status_json_no_error_key_with_dangerous_field_is_unknown():
    # {"user_id": 401} previously triggered auth stop; must now be unknown.
    content = '{"user_id": 401, "action": "login"}'
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "unknown"
    assert m["recommended_next_action"] != "stop", "spurious 401 in non-error field must not trigger stop"


def test_nonstd_error_status_non_json_content_still_classified():
    # Plain text (not JSON) with status="error" must still be classified from content.
    content = "connection refused: remote host unreachable"
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "transient"


def test_json_error_field_dict_is_serialized_not_repr():
    # FastAPI-style: {"error": [{"loc": ["body"], "msg": "missing required field"}]}
    # str() would produce Python repr containing 'missing required' → config → stop.
    # json.dumps produces a clean JSON string that should not spuriously match.
    import json as _json

    error_val = [{"loc": ["body"], "msg": "missing required field"}]
    content = _json.dumps({"error": error_val})
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    # The JSON-serialized error list contains "missing required field" which IS in the config rule.
    # This is correct classification (the validation error IS a config-class problem).
    # The key requirement is that we're classifying from the error field value, not repr noise.
    assert m["error_type"] == "config"


def test_no_results_success_response_is_partial_success():
    # Tools that return status="success" with "no results found" content must be treated as
    # partial_success so ToolProgressMiddleware can detect stagnation.
    for phrase in ("no results found", "No Content Found here", "no images found for query"):
        msg = _make_msg(phrase, status="success")
        result = normalize_tool_message(msg)
        m = _meta(result)
        assert m["status"] == "partial_success", f"expected partial_success for: {phrase!r}"
        assert m["recommended_next_action"] == "rewrite_query"


# ---------------------------------------------------------------------------
# Partial success detection


def test_partial_markers_detected():
    for marker in ("partial results available", "limited results returned", "truncated output", "results may be incomplete"):
        msg = _make_msg(f"Here are some {marker} from the search.", status="success")
        result = normalize_tool_message(msg)
        m = _meta(result)
        assert m["status"] == "partial_success", f"expected partial_success for: {marker}"
        assert m["recommended_next_action"] == "rewrite_query"


def test_short_terse_success_is_not_partial():
    # "Ok." is a valid, complete success response from mutation tools like write_file/str_replace.
    # partial_success is now gated only on _PARTIAL_MARKERS, not content length.
    msg = _make_msg("Ok.", status="success")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "success"
    assert m["source"] == "content_analysis"


def test_empty_content_is_not_partial():
    # Empty content has no partial markers, so it falls through to success.
    msg = _make_msg("", status="success")
    result = normalize_tool_message(msg)
    m = _meta(result)
    # Empty content falls through to success (no partial markers)
    assert m["status"] == "success"


# ---------------------------------------------------------------------------
# Success path


def test_substantial_content_is_success():
    content = "A" * 200
    msg = _make_msg(content, status="success")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "success"
    assert m["source"] == "content_analysis"
    assert m["recommended_next_action"] == "continue"
    assert m["error_type"] is None


# ---------------------------------------------------------------------------
# ToolResultMeta dataclass round-trip


def test_tool_result_meta_from_dict():
    msg = _make_msg("A" * 200)
    result = normalize_tool_message(msg)
    meta_dict = _meta(result)
    meta = ToolResultMeta(**meta_dict)
    assert meta.status == "success"
    assert meta.error_type is None
    assert meta.recommended_next_action == "continue"


# ---------------------------------------------------------------------------
# stamp_exception_meta


def test_stamp_exception_meta_classifies_from_exc_info_not_content():
    # Content says "no results" but exc_info says "connection refused" —
    # stamp_exception_meta must use exc_info, producing transient, not no_results.
    msg = _make_msg("Error: no results found", status="error")
    result = stamp_exception_meta(msg, "ConnectionError: connection refused")
    m = _meta(result)
    assert m["source"] == "exception"
    assert m["error_type"] == "transient"


def test_stamp_exception_meta_overwrites_existing_meta():
    pre_existing = {TOOL_META_KEY: {"source": "tool_return", "error_type": "unknown"}}
    msg = _make_msg("Error: no results found", status="error", kwargs=pre_existing)
    result = stamp_exception_meta(msg, "PermissionError: access denied")
    m = _meta(result)
    assert m["source"] == "exception"
    assert m["error_type"] == "permission"


def test_stamp_exception_meta_preserves_other_additional_kwargs():
    msg = _make_msg("irrelevant", status="error", kwargs={"subagent_status": "running"})
    result = stamp_exception_meta(msg, "TimeoutError: timed out")
    assert result.additional_kwargs["subagent_status"] == "running"
    assert TOOL_META_KEY in result.additional_kwargs


# ---------------------------------------------------------------------------
# normalize_tool_result handles Command wrappers


def test_normalize_tool_result_passthrough_command():
    cmd = Command(goto="next_node")
    result = normalize_tool_result(cmd)
    assert result is cmd


def test_normalize_tool_result_stamps_tool_message():
    msg = _make_msg("A" * 200)
    result = normalize_tool_result(msg)
    assert isinstance(result, ToolMessage)
    assert TOOL_META_KEY in result.additional_kwargs


# ---------------------------------------------------------------------------
# JSON-wrapped error detection


def test_normalize_json_error_config_classified_as_error():
    content = '{"error": "BRAVE_SEARCH_API_KEY is not configured", "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "config"
    assert m["source"] == "tool_return"


def test_normalize_json_error_no_results_classified_correctly():
    content = '{"error": "No results found", "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "no_results"
    assert m["recoverable_by_model"] is True


def test_normalize_json_null_error_not_treated_as_error():
    content = '{"error": null, "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] != "error"


def test_normalize_json_no_error_key_not_treated_as_error():
    content = '{"results": [{"title": "page one", "url": "https://example.com/one", "content": "summary one"}], "total": 1}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "success"


def test_normalize_malformed_json_not_treated_as_error():
    content = '{"error": "broken json'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] != "error"


def test_normalize_json_error_with_leading_whitespace():
    content = '  {"error": "No results found", "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "no_results"


def test_normalize_json_numeric_error_classified_correctly():
    content = '{"error": 404, "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "not_found"


def test_normalize_json_zero_error_not_treated_as_error():
    content = '{"error": 0, "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] != "error"


def test_normalize_json_false_error_not_treated_as_error():
    content = '{"error": false, "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] != "error"


def test_normalize_json_boolean_true_error_classified_as_unknown():
    """Boolean True in the error field means 'an error occurred' and must be classified.

    str(True) = "True" which matches no keyword rule, so the result is error/unknown.
    This is intentional: a boolean True error is a real error with no further detail.
    """
    content = '{"error": true, "query": "test"}'
    msg = _make_msg(content)
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == "unknown"  # str(True)="True" matches no keyword rule
    assert m["recoverable_by_model"] is True
    assert m["recommended_next_action"] == "try_alternative"


# ---------------------------------------------------------------------------
# M2 regression: semantic-zero error strings must NOT be treated as errors


@pytest.mark.parametrize(
    "error_value",
    ["none", "None", "NONE", "null", "Null", "false", "False", "no", "ok", "success", "n/a", ""],
)
def test_normalize_json_semantic_zero_error_string_not_treated_as_error(error_value: str):
    """M2 regression: error field containing a conventional 'no-error' string must not trigger misclassification.

    Tools sometimes return {"error": "none", "results": [...]} on success.
    The string "none" is truthy in Python, so without this guard the message
    would have been classified as error (unknown), inflating stagnation counters.

    Note: the empty-string case ("") is handled by the falsy guard (`if not error: return None`)
    in _extract_json_error_text rather than by _SEMANTIC_ZERO_ERROR_STRINGS.  Both paths produce
    the same outcome (no misclassification), but the mechanism differs from the other cases here.
    """
    content = json.dumps({"error": error_value, "results": ["item1", "item2", "item3"]})
    msg = _make_msg(content, status="success")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] != "error", f'error="{error_value}" should not be treated as an error; got status={m["status"]!r}'


# ---------------------------------------------------------------------------
# Numeric keyword word-boundary matching (_match_keyword)


@pytest.mark.parametrize(
    "content, expected_error_type",
    [
        # Positive: numeric code at a word boundary → correct classification
        ("Error: HTTP 500 Internal Server Error", "internal"),
        ("Error: returned status 500", "internal"),
        ("Error: 401 Unauthorized", "auth"),
        ("Error: 404 Not Found", "not_found"),
        # Negative: numeric code embedded inside a longer token → must resolve to "unknown".
        # Use exact "unknown" assertions so any future rule additions that accidentally
        # absorb these strings are caught (a broad exclusion list would miss new matches).
        ("Error: took 500ms to respond", "unknown"),
        ("Error: query returned 4010 rows", "unknown"),
        ("Error: batch 401A failed", "unknown"),
        ("Error: response contained 5000 items", "unknown"),
    ],
)
def test_numeric_keyword_word_boundary(content: str, expected_error_type: str):
    """Numeric HTTP codes must match only at word boundaries to avoid false positives.

    '500ms', '4010', '401A', '5000' must not trigger internal/auth/not_found rules.
    Negative cases assert exactly 'unknown' so future rule additions that accidentally
    absorb these strings are caught — a broad exclusion-list assertion would not be.
    """
    msg = _make_msg(content, status="error")
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["error_type"] == expected_error_type, f"{content!r} → expected {expected_error_type!r}, got {m['error_type']!r}"


# ---------------------------------------------------------------------------
# Structured subagent_status failures (delegated task Command results)
#


@pytest.mark.parametrize(
    "subagent_status",
    ["failed", "cancelled", "timed_out", "polling_timed_out"],
)
def test_subagent_failure_statuses_stamp_error(subagent_status: str):
    """Task failures leave ToolMessage.status=success and no Error: prefix."""
    msg = _make_msg(
        f"Task {subagent_status.replace('_', ' ')}. Result: boom",
        status="success",
        kwargs={"subagent_status": subagent_status, "subagent_error": "connection timeout"},
    )
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "error"
    assert m["source"] == "tool_return"
    assert m["error_type"] == "transient"
    assert result.additional_kwargs["subagent_status"] == subagent_status


def test_subagent_completed_still_content_analyzed():
    msg = _make_msg(
        "Task Succeeded. Result: ok",
        status="success",
        kwargs={"subagent_status": "completed"},
    )
    result = normalize_tool_message(msg)
    m = _meta(result)
    assert m["status"] == "success"


@pytest.mark.parametrize(
    "subagent_status",
    ["failed", "cancelled", "timed_out", "polling_timed_out"],
)
def test_normalize_tool_result_command_task_failures(subagent_status: str):
    msg = _make_msg(
        f"Task {subagent_status}. detail",
        status="success",
        kwargs={"subagent_status": subagent_status, "subagent_error": "Task failed"},
    )
    cmd = Command(update={"messages": [msg]})
    result = normalize_tool_result(cmd, tool_call_id="tc-1")
    assert isinstance(result, Command)
    stamped = result.update["messages"][0]
    assert _meta(stamped)["status"] == "error"
