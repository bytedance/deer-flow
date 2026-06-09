"""Tests for tiktoken encoding cache and _count_tokens fallback.

Verifies:
- Module-level cache avoids repeated ``get_encoding`` calls.
- ``_count_tokens`` falls back to character estimation when tiktoken is
  unavailable or the encoding fails to load.
- ``warm_tiktoken_cache`` populates the cache on success.
"""

from __future__ import annotations

from unittest import mock

from deerflow.agents.memory.prompt import (
    _count_tokens,
    _get_tiktoken_encoding,
    _tiktoken_encoding_cache,
    warm_tiktoken_cache,
)

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

    def test_returns_none_and_warns_on_get_encoding_failure(self, monkeypatch):
        _tiktoken_encoding_cache.pop("bogus_encoding", None)
        import tiktoken

        monkeypatch.setattr(tiktoken, "get_encoding", mock.Mock(side_effect=OSError("download failed")))
        result = _get_tiktoken_encoding("bogus_encoding")
        assert result is None
        assert "bogus_encoding" not in _tiktoken_encoding_cache


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
