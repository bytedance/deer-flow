"""Unit tests for session memory retrieval."""

from unittest.mock import Mock, patch

from deerflow.agents.memory.retrieval import (
    _cache_key,
    _format_session_context,
    get_session_context,
    invalidate_session_cache,
)
from deerflow.agents.memory.session_storage import create_empty_session_memory
from deerflow.config.session_memory_config import SessionMemoryConfig


class TestFormatSessionContext:
    """Tests for _format_session_context()."""

    def test_empty_data_returns_empty_string(self):
        assert _format_session_context({}, max_tokens=2000) == ""
        assert _format_session_context(None, max_tokens=2000) == ""

    def test_empty_session_memory_returns_empty_string(self):
        data = create_empty_session_memory()
        assert _format_session_context(data, max_tokens=2000) == ""

    def test_formats_summary_only(self):
        data = {
            "session_context": {"summary": "Debugging auth issue"},
            "facts": [],
        }
        result = _format_session_context(data, max_tokens=2000)
        assert "Thread summary: Debugging auth issue" in result

    def test_formats_facts_only(self):
        data = {
            "session_context": {"summary": ""},
            "facts": [
                {"content": "JWT token expires after 1 hour", "category": "context", "confidence": 0.9},
            ],
        }
        result = _format_session_context(data, max_tokens=2000)
        assert "Session facts:" in result
        assert "JWT token expires after 1 hour" in result
        assert "[context | 0.90]" in result

    def test_formats_summary_and_facts(self):
        data = {
            "session_context": {"summary": "Working on budget report"},
            "facts": [
                {"content": "Q3 deadline is Friday", "category": "decision", "confidence": 0.95},
            ],
        }
        result = _format_session_context(data, max_tokens=2000)
        assert "Thread summary: Working on budget report" in result
        assert "Q3 deadline is Friday" in result

    def test_facts_sorted_by_confidence(self):
        data = {
            "session_context": {"summary": ""},
            "facts": [
                {"content": "Low", "category": "context", "confidence": 0.5},
                {"content": "High", "category": "context", "confidence": 0.95},
                {"content": "Medium", "category": "context", "confidence": 0.7},
            ],
        }
        result = _format_session_context(data, max_tokens=2000)
        lines = [line for line in result.split("\n") if line.startswith("- [")]
        assert len(lines) == 3
        assert "High" in lines[0]
        assert "Medium" in lines[1]
        assert "Low" in lines[2]

    def test_correction_fact_includes_source_error(self):
        data = {
            "session_context": {"summary": ""},
            "facts": [
                {
                    "content": "Use JWT for auth",
                    "category": "correction",
                    "confidence": 0.95,
                    "sourceError": "Tried session-based auth",
                },
            ],
        }
        result = _format_session_context(data, max_tokens=2000)
        assert "Use JWT for auth" in result
        assert "(avoid: Tried session-based auth)" in result

    def test_truncates_to_max_tokens(self):
        data = {
            "session_context": {"summary": "A" * 10000},
            "facts": [],
        }
        result = _format_session_context(data, max_tokens=100)
        assert result.endswith("\n...")
        assert len(result) < 10000


class TestGetSessionContext:
    """Tests for get_session_context()."""

    def setup_method(self):
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=True))

    def test_returns_empty_when_disabled(self):
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=False))

        result = get_session_context("thread-123")
        assert result == ""

    def test_returns_empty_when_injection_disabled(self):
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=True, injection_enabled=False))

        result = get_session_context("thread-123")
        assert result == ""

    def test_returns_empty_when_storage_unavailable(self):
        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=None):
            result = get_session_context("thread-123")
        assert result == ""

    def test_loads_and_formats_session_context(self):
        mock_storage = Mock()
        mock_storage.load = Mock(return_value={
            "session_context": {"summary": "Debugging auth"},
            "facts": [
                {"content": "JWT expired", "category": "context", "confidence": 0.9},
            ],
        })

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            result = get_session_context("thread-123", user_id="user-1")

        assert result.startswith("Session context:")
        assert "Debugging auth" in result
        assert "JWT expired" in result

    def test_returns_empty_when_session_data_empty(self):
        mock_storage = Mock()
        mock_storage.load = Mock(return_value=create_empty_session_memory())

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            result = get_session_context("thread-123")

        assert result == ""

    def test_uses_cache_on_second_call(self):
        session_data = {
            "session_context": {"summary": "Cached context"},
            "facts": [],
        }
        mock_storage = Mock()
        mock_storage.load = Mock(return_value=session_data)

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            result1 = get_session_context("thread-cache", user_id="user-1")
            result2 = get_session_context("thread-cache", user_id="user-1")

        assert result1 == result2
        assert mock_storage.load.call_count == 1

    def test_cache_invalidated_after_save(self):
        session_data = {
            "session_context": {"summary": "Old context"},
            "facts": [],
        }
        mock_storage = Mock()
        mock_storage.load = Mock(return_value=session_data)

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            get_session_context("thread-inv", user_id="user-1")
            invalidate_session_cache("thread-inv", user_id="user-1")
            get_session_context("thread-inv", user_id="user-1")

        assert mock_storage.load.call_count == 2

    def test_uses_config_max_tokens_by_default(self):
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=True, max_injection_tokens=500))

        mock_storage = Mock()
        mock_storage.load = Mock(return_value={
            "session_context": {"summary": "X" * 5000},
            "facts": [],
        })

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            result = get_session_context("thread-tokens")

        assert len(result) < 5000


class TestCacheKey:
    """Tests for _cache_key()."""

    def test_basic_key(self):
        key = _cache_key("tenant-1", "user-1", "thread-1")
        assert key == ("tenant-1", "user-1", "thread-1")

    def test_none_user_becomes_empty_string(self):
        key = _cache_key("tenant-1", None, "thread-1")
        assert key == ("tenant-1", "", "thread-1")
