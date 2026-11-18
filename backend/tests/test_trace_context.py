"""Unit tests for ``deerflow.trace_context`` validation helpers.

The middleware-level end-to-end coverage lives in ``test_trace_middleware.py``;
this file pins the character-set invariants of ``normalize_trace_id`` directly
so that a future relaxation of the check trips a targeted failure.
"""

from __future__ import annotations

import pytest

from deerflow.trace_context import (
    _MAX_TRACE_ID_LENGTH,
    bind_trace_id,
    ensure_trace_context,
    ensure_trace_id,
    get_current_trace_id,
    normalize_trace_id,
    request_trace_context,
    reset_trace_id,
    resolve_trace_id,
)


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


class TestEnsureTraceId:
    """The non-nullable accessor that lets consumers drop presence guards."""

    def test_returns_the_bound_id(self) -> None:
        with request_trace_context("bound-1"):
            assert ensure_trace_id() == "bound-1"

    def test_mints_and_binds_when_unset(self) -> None:
        assert get_current_trace_id() is None
        trace_id = ensure_trace_id()
        assert trace_id
        # Binding is what makes repeated reads inside one context agree.
        assert get_current_trace_id() == trace_id
        assert ensure_trace_id() == trace_id


class TestResolveTraceId:
    """Carrier fallback: the one place that knows the order."""

    def test_first_usable_carrier_wins(self) -> None:
        with request_trace_context("ambient"):
            assert resolve_trace_id("runtime-ctx", "config-metadata") == "runtime-ctx"

    def test_falls_through_absent_and_malformed_carriers_alike(self) -> None:
        with request_trace_context("ambient"):
            assert resolve_trace_id(None, "trace\nid", "config-metadata") == "config-metadata"

    def test_falls_back_to_ambient_trace(self) -> None:
        with request_trace_context("ambient"):
            assert resolve_trace_id(None, None) == "ambient"

    def test_never_returns_none_without_any_binding(self) -> None:
        assert get_current_trace_id() is None
        assert resolve_trace_id(None)


class TestBindTraceId:
    """Low-level pair for callers that cannot use the context managers."""

    def test_binds_and_restores(self) -> None:
        token = bind_trace_id("step-1")
        try:
            assert get_current_trace_id() == "step-1"
        finally:
            reset_trace_id(token)
        assert get_current_trace_id() is None

    def test_none_clears_the_binding(self) -> None:
        """How a test harness restores an unbound baseline — see the autouse
        ``_isolate_trace_context`` fixture in conftest."""
        with request_trace_context("outer"):
            token = bind_trace_id(None)
            try:
                assert get_current_trace_id() is None
            finally:
                reset_trace_id(token)
            assert get_current_trace_id() == "outer"


class TestRequestTraceContext:
    def test_generates_when_no_inbound_id(self) -> None:
        with request_trace_context() as trace_id:
            assert trace_id
            assert get_current_trace_id() == trace_id
        assert get_current_trace_id() is None

    def test_never_inherits_an_ambient_id(self) -> None:
        """A crafted header must not silently fall back to the id of whatever
        request ran before it on the same task."""
        with request_trace_context("outer"):
            with request_trace_context("trace\nid") as inner:
                assert inner != "outer"
            assert get_current_trace_id() == "outer"


class TestEnsureTraceContext:
    def test_rebinds_a_propagated_id_across_a_boundary(self) -> None:
        with ensure_trace_context("carried-over") as trace_id:
            assert trace_id == "carried-over"
            assert get_current_trace_id() == "carried-over"
        assert get_current_trace_id() is None

    def test_inherits_rather_than_minting_when_no_id_is_carried(self) -> None:
        """A non-HTTP launch reached from inside a request stays on the
        caller's trace instead of minting a competing id."""
        with request_trace_context("gateway-request-1"):
            with ensure_trace_context() as trace_id:
                assert trace_id == "gateway-request-1"

    def test_mints_a_scoped_id_for_a_non_http_entry_point(self) -> None:
        """A long-lived worker task must not leak one unit of work's id into
        the next, so the minted id is unbound on exit."""
        with ensure_trace_context() as first:
            assert first
        assert get_current_trace_id() is None
        with ensure_trace_context() as second:
            assert second != first

    def test_keeps_the_ambient_binding_when_the_id_already_matches(self) -> None:
        with request_trace_context("outer"):
            with ensure_trace_context("outer") as trace_id:
                assert trace_id == "outer"
            assert get_current_trace_id() == "outer"
