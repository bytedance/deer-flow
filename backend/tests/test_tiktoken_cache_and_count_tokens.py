"""Tests for tiktoken encoding cache and _count_tokens fallback.

Verifies:
- Module-level cache avoids repeated ``get_encoding`` calls.
- ``_count_tokens`` falls back to character estimation when tiktoken is
  unavailable or the encoding fails to load.
- ``warm_tiktoken_cache`` populates the cache on success.
- An in-flight tiktoken load prevents duplicate blocking downloads.
"""

from __future__ import annotations

import threading
from unittest import mock

from deerflow.agents.memory.prompt import (
    _count_tokens,
    _get_tiktoken_encoding,
    _tiktoken_encoding_cache,
    format_memory_for_injection,
    warm_tiktoken_cache,
)
from deerflow.config.memory_config import MemoryConfig

# ---------------------------------------------------------------------------
# _get_tiktoken_encoding
# ---------------------------------------------------------------------------


class TestGetTiktokenEncoding:
    """Tests for _get_tiktoken_encoding caching and fallback."""

    def test_returns_none_when_tiktoken_unavailable(self, monkeypatch):
        monkeypatch.setattr("deerflow.agents.memory.prompt.TIKTOKEN_AVAILABLE", False)
        assert _get_tiktoken_encoding("cl100k_base") is None

    def test_returns_encoding_on_success(self, monkeypatch):
        # Clear cache to ensure a fresh call
        _tiktoken_encoding_cache.pop("cl100k_base", None)

        fake_enc = mock.Mock()
        monkeypatch.setattr("deerflow.agents.memory.prompt.tiktoken.get_encoding", mock.Mock(return_value=fake_enc))

        enc = _get_tiktoken_encoding("cl100k_base")
        assert enc is fake_enc

    def test_populates_cache_on_success(self, monkeypatch):
        _tiktoken_encoding_cache.pop("cl100k_base", None)

        fake_enc = mock.Mock()
        monkeypatch.setattr("deerflow.agents.memory.prompt.tiktoken.get_encoding", mock.Mock(return_value=fake_enc))

        _get_tiktoken_encoding("cl100k_base")
        assert _tiktoken_encoding_cache["cl100k_base"] is fake_enc

    def test_returns_cached_encoding_without_calling_get_encoding(self, monkeypatch):
        fake_enc = mock.Mock()
        monkeypatch.setitem(_tiktoken_encoding_cache, "cl100k_base", fake_enc)

        # Now patch tiktoken.get_encoding to raise if called
        import tiktoken

        monkeypatch.setattr(tiktoken, "get_encoding", mock.Mock(side_effect=RuntimeError("should not be called")))
        # Cached path — should NOT call get_encoding
        enc = _get_tiktoken_encoding("cl100k_base")
        assert enc is fake_enc
        tiktoken.get_encoding.assert_not_called()

    def test_returns_none_and_caches_failure_sentinel(self, monkeypatch):
        """A failed load is cached (with a timestamp) so it is not re-attempted (no repeated network download)."""
        _tiktoken_encoding_cache.pop("bogus_encoding", None)
        import tiktoken

        get_encoding = mock.Mock(side_effect=OSError("download failed"))
        monkeypatch.setattr(tiktoken, "get_encoding", get_encoding)

        result = _get_tiktoken_encoding("bogus_encoding")
        assert result is None
        # The failure is remembered as a (None, timestamp) tuple.
        assert "bogus_encoding" in _tiktoken_encoding_cache
        cached = _tiktoken_encoding_cache["bogus_encoding"]
        assert isinstance(cached, tuple)
        assert cached[0] is None

        # A second call must NOT re-attempt get_encoding (avoids re-blocking on
        # the network download in restricted environments — see #3429).
        result2 = _get_tiktoken_encoding("bogus_encoding")
        assert result2 is None
        assert get_encoding.call_count == 1

        # Cleanup module-level cache to avoid cross-test leakage.
        _tiktoken_encoding_cache.pop("bogus_encoding", None)

    def test_failure_self_heals_after_cooldown(self, monkeypatch):
        """After the retry cooldown expires, a transient failure is re-attempted and can recover."""
        _tiktoken_encoding_cache.pop("flaky_encoding", None)
        import tiktoken

        fake_enc = mock.Mock()
        # First call fails, second call (after cooldown) succeeds.
        get_encoding = mock.Mock(side_effect=[OSError("transient outage"), fake_enc])
        monkeypatch.setattr(tiktoken, "get_encoding", get_encoding)

        # Initial failure is cached.
        assert _get_tiktoken_encoding("flaky_encoding") is None
        assert get_encoding.call_count == 1

        # Within the cooldown window: no retry, immediate fallback.
        assert _get_tiktoken_encoding("flaky_encoding") is None
        assert get_encoding.call_count == 1

        # Simulate the cooldown having elapsed by ageing the cached timestamp.
        from deerflow.agents.memory import prompt as prompt_module

        _, _failed_at = _tiktoken_encoding_cache["flaky_encoding"]
        _tiktoken_encoding_cache["flaky_encoding"] = (
            None,
            _failed_at - prompt_module._TIKTOKEN_RETRY_COOLDOWN_S - 1,
        )

        # Now the load is retried and recovers to accurate counting.
        assert _get_tiktoken_encoding("flaky_encoding") is fake_enc
        assert get_encoding.call_count == 2

        _tiktoken_encoding_cache.pop("flaky_encoding", None)

    def test_in_flight_load_returns_none_without_duplicate_get_encoding(self, monkeypatch):
        """Concurrent callers must not start duplicate blocking BPE downloads."""
        _tiktoken_encoding_cache.pop("slow_encoding", None)
        import tiktoken

        started = threading.Event()
        release = threading.Event()
        fake_enc = mock.Mock()

        def slow_get_encoding(_name):
            started.set()
            assert release.wait(timeout=2), "test timed out waiting to release slow get_encoding"
            return fake_enc

        get_encoding = mock.Mock(side_effect=slow_get_encoding)
        monkeypatch.setattr(tiktoken, "get_encoding", get_encoding)

        result: dict[str, object | None] = {}

        def load_encoding():
            result["encoding"] = _get_tiktoken_encoding("slow_encoding")

        thread = threading.Thread(target=load_encoding)
        thread.start()
        try:
            assert started.wait(timeout=1), "slow get_encoding did not start"

            # While the first call is still blocked, a second call should see
            # the in-flight sentinel and fall back immediately instead of
            # starting another potentially long network download.
            assert _get_tiktoken_encoding("slow_encoding") is None
            assert get_encoding.call_count == 1
        finally:
            release.set()
            thread.join(timeout=2)
            _tiktoken_encoding_cache.pop("slow_encoding", None)

        assert result["encoding"] is fake_enc
        assert get_encoding.call_count == 1


# ---------------------------------------------------------------------------
# _count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    """Tests for _count_tokens fallback behaviour."""

    def test_returns_character_estimate_when_tiktoken_unavailable(self, monkeypatch):
        monkeypatch.setattr("deerflow.agents.memory.prompt.TIKTOKEN_AVAILABLE", False)
        text = "Hello, world! This is a test."
        result = _count_tokens(text)
        assert result == len(text) // 4

    def test_returns_character_estimate_when_encoding_fails(self, monkeypatch):
        monkeypatch.setattr(
            "deerflow.agents.memory.prompt._get_tiktoken_encoding",
            lambda _name=None: None,
        )
        text = "Some text to count"
        result = _count_tokens(text)
        assert result == len(text) // 4

    def test_returns_token_count_on_success(self, monkeypatch):
        fake_enc = mock.Mock()
        fake_enc.encode.return_value = [0, 1, 2, 3]
        monkeypatch.setattr("deerflow.agents.memory.prompt._get_tiktoken_encoding", mock.Mock(return_value=fake_enc))

        text = "Hello, world!"
        result = _count_tokens(text)
        assert result == 4
        assert result <= len(text)

    def test_falls_back_on_encode_exception(self, monkeypatch):
        # Cache an encoding whose .encode raises
        fake_enc = mock.Mock()
        fake_enc.encode.side_effect = RuntimeError("encode failed")
        monkeypatch.setitem(_tiktoken_encoding_cache, "test_enc", fake_enc)

        text = "Fallback test"
        result = _count_tokens(text, encoding_name="test_enc")
        assert result == len(text) // 4

    def test_use_tiktoken_false_returns_char_estimate_without_touching_tiktoken(self, monkeypatch):
        """use_tiktoken=False must never call tiktoken (guarantees no BPE download)."""
        # Spy on both the encoding loader and tiktoken.get_encoding directly.
        get_encoding_spy = mock.Mock(side_effect=AssertionError("get_encoding must not be called"))
        loader_spy = mock.Mock(side_effect=AssertionError("_get_tiktoken_encoding must not be called"))
        monkeypatch.setattr("deerflow.agents.memory.prompt.tiktoken.get_encoding", get_encoding_spy)
        monkeypatch.setattr("deerflow.agents.memory.prompt._get_tiktoken_encoding", loader_spy)

        text = "Hello, world! This is a network-free count."
        result = _count_tokens(text, use_tiktoken=False)
        assert result == len(text) // 4
        get_encoding_spy.assert_not_called()
        loader_spy.assert_not_called()

    def test_cjk_estimate_is_denser_than_plain_quarter(self, monkeypatch):
        """CJK text should estimate more tokens than the plain len // 4 heuristic.

        CJK characters are ~2 chars/token, so the char-based estimate must not
        under-fill the budget the way ``len(text) // 4`` would.
        """
        monkeypatch.setattr("deerflow.agents.memory.prompt.TIKTOKEN_AVAILABLE", False)
        # "User prefers concise answers" rendered in CJK (Chinese) characters.
        text = "\u7528\u6237\u504f\u597d\u7b80\u6d01\u7684\u4e2d\u6587\u56de\u7b54\u5e76\u5173\u6ce8\u91d1\u878d\u9886\u57df"
        result = _count_tokens(text)
        # Each CJK char counts as ~1/2 token (vs 1/4 for the plain heuristic).
        assert result == len(text) // 2
        assert result > len(text) // 4

    def test_cjk_estimate_combines_cjk_and_non_cjk_characters(self, monkeypatch):
        """Mixed-language text should apply the CJK density only to CJK chars."""
        monkeypatch.setattr("deerflow.agents.memory.prompt.TIKTOKEN_AVAILABLE", False)
        # ASCII words mixed with CJK (Chinese) characters: "User" + "likes" + "Python and data analysis".
        text = "User\u559c\u6b22Python\u548c\u6570\u636e\u5206\u6790"
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")

        result = _count_tokens(text)

        assert result == (len(text) - cjk) // 4 + cjk // 2


# ---------------------------------------------------------------------------
# warm_tiktoken_cache
# ---------------------------------------------------------------------------


class TestWarmTiktokenCache:
    """Tests for warm_tiktoken_cache startup helper."""

    def test_returns_true_on_success(self, monkeypatch):
        _tiktoken_encoding_cache.pop("cl100k_base", None)

        fake_enc = mock.Mock()
        monkeypatch.setattr("deerflow.agents.memory.prompt.tiktoken.get_encoding", mock.Mock(return_value=fake_enc))

        assert warm_tiktoken_cache() is True
        assert _tiktoken_encoding_cache["cl100k_base"] is fake_enc

    def test_returns_true_if_already_cached(self, monkeypatch):
        fake_enc = mock.Mock()
        monkeypatch.setitem(_tiktoken_encoding_cache, "cl100k_base", fake_enc)

        import tiktoken

        monkeypatch.setattr(tiktoken, "get_encoding", mock.Mock(side_effect=RuntimeError("should not be called")))
        assert warm_tiktoken_cache() is True
        tiktoken.get_encoding.assert_not_called()

    def test_returns_false_when_tiktoken_unavailable(self, monkeypatch):
        monkeypatch.setattr("deerflow.agents.memory.prompt.TIKTOKEN_AVAILABLE", False)
        assert warm_tiktoken_cache() is False


# ---------------------------------------------------------------------------
# format_memory_for_injection token_counting strategy
# ---------------------------------------------------------------------------


class TestFormatMemoryForInjectionTokenCounting:
    """Verify the use_tiktoken flag is honoured end-to-end."""

    @staticmethod
    def _sample_memory() -> dict:
        return {
            "facts": [
                {"content": "User prefers concise answers.", "category": "preference", "confidence": 0.9},
                {"content": "User works in the finance domain.", "category": "context", "confidence": 0.8},
            ],
        }

    def test_use_tiktoken_false_never_touches_tiktoken(self, monkeypatch):
        """With use_tiktoken=False, formatting must not call tiktoken at all."""
        get_encoding_spy = mock.Mock(side_effect=AssertionError("get_encoding must not be called"))
        monkeypatch.setattr("deerflow.agents.memory.prompt.tiktoken.get_encoding", get_encoding_spy)

        result = format_memory_for_injection(self._sample_memory(), max_tokens=2000, use_tiktoken=False)
        assert "User prefers concise answers." in result
        get_encoding_spy.assert_not_called()

    def test_use_tiktoken_true_uses_encoding(self, monkeypatch):
        """With use_tiktoken=True (default), the cached encoding is used for counting."""
        fake_enc = mock.Mock()
        fake_enc.encode.side_effect = lambda text: list(range(len(text)))
        monkeypatch.setattr(
            "deerflow.agents.memory.prompt._get_tiktoken_encoding",
            mock.Mock(return_value=fake_enc),
        )

        result = format_memory_for_injection(self._sample_memory(), max_tokens=2000, use_tiktoken=True)
        assert "User prefers concise answers." in result
        assert fake_enc.encode.called

    def test_empty_memory_returns_empty(self):
        assert format_memory_for_injection({}, max_tokens=2000, use_tiktoken=False) == ""


# ---------------------------------------------------------------------------
# MemoryConfig.token_counting
# ---------------------------------------------------------------------------


class TestMemoryConfigTokenCounting:
    """Verify the new config field defaults and validation."""

    def test_default_is_tiktoken(self):
        """Default must remain tiktoken so existing deployments are unaffected."""
        assert MemoryConfig().token_counting == "tiktoken"

    def test_accepts_char(self):
        assert MemoryConfig(token_counting="char").token_counting == "char"

    def test_rejects_invalid_value(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MemoryConfig(token_counting="invalid")
