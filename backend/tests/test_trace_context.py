"""Unit tests for ``deerflow.trace_context`` validation helpers.

The middleware-level end-to-end coverage lives in ``test_trace_middleware.py``;
this file pins the character-set invariants of ``normalize_trace_id`` directly
so that a future relaxation of the check trips a targeted failure.
"""

from __future__ import annotations

import pytest

from deerflow.trace_context import _MAX_TRACE_ID_LENGTH, normalize_trace_id


class TestNormalizeTraceIdAcceptsPrintableAscii:
    def test_accepts_uuid_hex(self) -> None:
        assert normalize_trace_id("0123456789abcdef0123456789abcdef") == "0123456789abcdef0123456789abcdef"

    def test_accepts_alphanumerics_and_punctuation(self) -> None:
        assert normalize_trace_id("abc-123_XYZ.foo:bar/baz") == "abc-123_XYZ.foo:bar/baz"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_trace_id("  trace-1  ") == "trace-1"

    def test_accepts_boundary_low(self) -> None:
        assert normalize_trace_id("\x20abc") == "abc"

    def test_accepts_boundary_high(self) -> None:
        assert normalize_trace_id("abc\x7e") == "abc\x7e"

    def test_accepts_maximum_length(self) -> None:
        value = "a" * _MAX_TRACE_ID_LENGTH
        assert normalize_trace_id(value) == value


class TestNormalizeTraceIdRejectsUnsafeInput:
    def test_rejects_non_string(self) -> None:
        assert normalize_trace_id(None) is None
        assert normalize_trace_id(12345) is None
        assert normalize_trace_id(b"abc") is None

    def test_rejects_empty_and_whitespace_only(self) -> None:
        assert normalize_trace_id("") is None
        assert normalize_trace_id("   \t  ") is None

    def test_rejects_over_max_length(self) -> None:
        assert normalize_trace_id("a" * (_MAX_TRACE_ID_LENGTH + 1)) is None

    @pytest.mark.parametrize(
        "value",
        [
            "trace\x00id",  # NUL
            "trace\x1fid",  # last C0 control
            "trace\tid",  # embedded tab
            "trace\nid",  # LF — the classic log-injection / CRLF pivot
            "trace\rid",  # CR
        ],
    )
    def test_rejects_c0_controls(self, value: str) -> None:
        assert normalize_trace_id(value) is None

    def test_rejects_del(self) -> None:
        assert normalize_trace_id("trace\x7fid") is None

    @pytest.mark.parametrize("value", ["trace\x80id", "trace\x9fid"])
    def test_rejects_c1_controls_in_latin1_range(self, value: str) -> None:
        """C1 controls latin-1-encode successfully but are stripped or
        rejected by hardened intermediaries (nginx / envoy / cloudfront),
        silently breaking the response. Reject at validation time."""
        assert normalize_trace_id(value) is None

    def test_rejects_latin1_supplement_characters(self) -> None:
        assert normalize_trace_id("caf\xe9") is None  # é = 0xE9

    def test_rejects_cjk_characters(self) -> None:
        """Codepoints > 0xFF raise UnicodeEncodeError inside
        ``MutableHeaders.__setitem__`` before ``send`` is dispatched, forcing
        a 500 on any endpoint. This is the exact case from the review."""
        assert normalize_trace_id("请求-1") is None
        assert normalize_trace_id("トレース") is None

    def test_rejects_emoji(self) -> None:
        assert normalize_trace_id("trace-\U0001f680") is None  # 🚀

    def test_rejects_surrogate_pair_pieces(self) -> None:
        assert normalize_trace_id("trace-\ud83d") is None
