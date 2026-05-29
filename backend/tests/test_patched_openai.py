"""Tests for issue #1515: PatchedChatOpenAI strips unsupported extra_body keys.

Google's official OpenAI-compatible Gemini endpoint returns HTTP 400 when the
``thinking`` key is present in ``extra_body`` because that key is only valid on
the native Gemini SDK path.  ``PatchedChatOpenAI`` must strip it before the
request is sent while leaving all other extra_body content intact.
"""

from __future__ import annotations

from deerflow.models.patched_openai import _strip_unsupported_extra_body

# ---------------------------------------------------------------------------
# _strip_unsupported_extra_body
# ---------------------------------------------------------------------------


def test_strip_removes_thinking_from_extra_body():
    """'thinking' inside extra_body is stripped to prevent HTTP 400."""
    payload = {
        "model": "gemini-3.1-pro-preview",
        "messages": [],
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    result = _strip_unsupported_extra_body(payload)
    assert "extra_body" not in result


def test_strip_removes_thinking_but_keeps_other_extra_body_keys():
    """Only 'thinking' is removed; other extra_body entries are preserved."""
    payload = {
        "model": "gemini-3.1-pro-preview",
        "messages": [],
        "extra_body": {"thinking": {"type": "enabled"}, "safe_prompt": True},
    }
    result = _strip_unsupported_extra_body(payload)
    assert "thinking" not in result["extra_body"]
    assert result["extra_body"]["safe_prompt"] is True


def test_strip_noop_when_no_extra_body():
    """Payload without extra_body is returned unchanged."""
    payload = {"model": "gemini-3.1-pro-preview", "messages": []}
    result = _strip_unsupported_extra_body(payload)
    assert result == payload


def test_strip_noop_when_extra_body_has_no_thinking():
    """extra_body without 'thinking' is returned unchanged."""
    payload = {
        "model": "gemini-3.1-pro-preview",
        "messages": [],
        "extra_body": {"safe_prompt": True},
    }
    result = _strip_unsupported_extra_body(payload)
    assert result["extra_body"] == {"safe_prompt": True}


def test_strip_does_not_mutate_original_payload():
    """The original payload dict is never mutated — a new dict is returned."""
    original_extra = {"thinking": {"type": "enabled"}}
    payload = {"messages": [], "extra_body": original_extra}

    result = _strip_unsupported_extra_body(payload)

    assert payload["extra_body"] is original_extra
    assert "thinking" in payload["extra_body"]
    assert original_extra == {"thinking": {"type": "enabled"}}

    assert result is not payload
    assert "extra_body" not in result


def test_strip_noop_when_extra_body_is_not_a_dict():
    """Non-dict extra_body values are left untouched."""
    payload = {"messages": [], "extra_body": "some-string"}
    result = _strip_unsupported_extra_body(payload)
    assert result["extra_body"] == "some-string"


def test_strip_empty_extra_body_after_removal_deletes_key():
    """When all extra_body keys are removed, the key itself is deleted."""
    payload = {"messages": [], "extra_body": {"thinking": {"type": "enabled"}}}
    result = _strip_unsupported_extra_body(payload)
    assert "extra_body" not in result
