"""Unit tests for compose_memory_for_prompt()."""

from unittest.mock import Mock, patch

from deerflow.agents.memory.retrieval import compose_memory_for_prompt
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.session_memory_config import SessionMemoryConfig
from deerflow.config.domain_memory_config import DomainMemoryConfig


class TestComposeMemoryForPrompt:
    """Tests for compose_memory_for_prompt()."""

    def setup_method(self):
        from deerflow.agents.memory.retrieval import _session_cache
        _session_cache.clear()

    def test_returns_empty_when_both_disabled(self):
        """Returns empty string when both User and Session memory are disabled."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert result == ""

    def test_returns_user_memory_only_when_session_disabled(self):
        """Returns only User Memory context when Session Memory is disabled."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.get_memory_data", return_value={"user": {"workContext": {"summary": "Engineer"}}}),
            patch("deerflow.agents.memory.format_memory_for_injection", return_value="Work: Engineer"),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert "User context:" in result
        assert "Work: Engineer" in result
        assert "Session context:" not in result

    def test_returns_session_memory_only_when_user_disabled(self):
        """Returns only Session Memory context when User Memory is disabled."""
        mock_storage = Mock()
        mock_storage.load = Mock(return_value={
            "session_context": {"summary": "Debugging auth"},
            "facts": [],
        })

        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert "Session context:" in result
        assert "Debugging auth" in result
        assert "User context:" not in result

    def test_returns_both_when_both_enabled(self):
        """Returns both User and Session Memory when both are enabled."""
        mock_storage = Mock()
        mock_storage.load = Mock(return_value={
            "session_context": {"summary": "Working on API"},
            "facts": [],
        })

        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.get_memory_data", return_value={"user": {"workContext": {"summary": "Dev"}}}),
            patch("deerflow.agents.memory.format_memory_for_injection", return_value="Work: Dev"),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert "User context:" in result
        assert "Work: Dev" in result
        assert "Session context:" in result
        assert "Working on API" in result

    def test_respects_injection_enabled_flags(self):
        """Respects independent injection_enabled flags for User and Session."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=Mock(load=Mock(return_value={"session_context": {"summary": "Test"}, "facts": []}))),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert "User context:" not in result
        assert "Session context:" in result

    def test_returns_empty_when_both_empty(self):
        """Returns empty string when both memories are empty."""
        mock_storage = Mock()
        mock_storage.load = Mock(return_value={"session_context": {"summary": ""}, "facts": []})

        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.get_memory_data", return_value={}),
            patch("deerflow.agents.memory.format_memory_for_injection", return_value=""),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert result == ""

    def test_returns_all_three_layers_when_all_enabled(self):
        """Returns User, Session, and Domain memory when all enabled."""
        mock_session_storage = Mock()
        mock_session_storage.load = Mock(return_value={
            "session_context": {"summary": "Session summary"},
            "facts": [],
        })

        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.config.domain_memory_config.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.get_memory_data", return_value={"user": {"workContext": {"summary": "Dev"}}}),
            patch("deerflow.agents.memory.format_memory_for_injection", return_value="Work: Dev"),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_session_storage),
            patch("deerflow.agents.memory.domain_retrieval.get_domain_context", return_value="Domain context:\n- [equipment/pump_a] Pump A flow 500 GPM"),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1", domain_query="Pump A")

        assert "User context:" in result
        assert "Session context:" in result
        assert "Domain context:" in result
        assert "Pump A flow 500 GPM" in result

    def test_skips_domain_when_disabled(self):
        """Skips domain memory when domain memory is disabled."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.config.domain_memory_config.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=False)),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert result == ""

    def test_skips_domain_when_injection_disabled(self):
        """Skips domain memory when injection_enabled is False."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.config.domain_memory_config.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True, injection_enabled=False)),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1")

        assert result == ""

    def test_domain_only_when_user_and_session_disabled(self):
        """Returns only domain memory when user and session are disabled."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.config.domain_memory_config.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.domain_retrieval.get_domain_context", return_value="Domain context:\n- [equipment/pump_a] Test fact"),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1", domain_query="test")

        assert "User context:" not in result
        assert "Session context:" not in result
        assert "Domain context:" in result
        assert "Test fact" in result

    def test_uses_thread_id_as_domain_query_fallback(self):
        """Uses thread_id as domain query when domain_query not provided."""
        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=False)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.config.domain_memory_config.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.domain_retrieval.get_domain_context", return_value="Domain context:\n- Test") as mock_get_domain,
        ):
            compose_memory_for_prompt(thread_id="thread-xyz")

        mock_get_domain.assert_called_once()
        call_kwargs = mock_get_domain.call_args.kwargs
        assert call_kwargs["query"] == "thread-xyz"
