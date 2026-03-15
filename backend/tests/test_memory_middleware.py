"""Tests for MemoryMiddleware and message filtering logic."""

from unittest.mock import MagicMock, patch

from src.agents.middlewares.memory_middleware import MemoryMiddleware, _filter_messages_for_memory


class FakeMessage:
    """Lightweight message stub for testing."""

    def __init__(self, type: str, content: str = "", tool_calls=None):
        self.type = type
        self.content = content
        self.tool_calls = tool_calls or []


class TestFilterMessagesForMemory:
    def test_keeps_human_and_final_ai(self):
        messages = [
            FakeMessage("human", "Hello"),
            FakeMessage("ai", "Hi there"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 2
        assert result[0].type == "human"
        assert result[1].type == "ai"

    def test_filters_tool_messages(self):
        messages = [
            FakeMessage("human", "Hello"),
            FakeMessage("ai", "", tool_calls=[{"name": "search"}]),
            FakeMessage("tool", "result"),
            FakeMessage("ai", "Here's what I found"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 2
        assert result[0].type == "human"
        assert result[1].type == "ai"
        assert result[1].content == "Here's what I found"

    def test_strips_uploaded_files_block(self):
        human_content = "<uploaded_files>\n- file.pdf\n</uploaded_files>\nWhat is this about?"
        messages = [
            FakeMessage("human", human_content),
            FakeMessage("ai", "It's a document about X"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 2
        assert "<uploaded_files>" not in result[0].content
        assert "What is this about?" in result[0].content

    def test_upload_only_message_skipped(self):
        """A human message that contains only the upload block should be skipped."""
        messages = [
            FakeMessage("human", "<uploaded_files>\n- file.pdf\n</uploaded_files>"),
            FakeMessage("ai", "I received your file"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 0

    def test_empty_messages(self):
        result = _filter_messages_for_memory([])
        assert result == []

    def test_multiple_turns(self):
        messages = [
            FakeMessage("human", "Q1"),
            FakeMessage("ai", "A1"),
            FakeMessage("human", "Q2"),
            FakeMessage("ai", "", tool_calls=[{"name": "calc"}]),
            FakeMessage("tool", "42"),
            FakeMessage("ai", "The answer is 42"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 4
        types = [m.type for m in result]
        assert types == ["human", "ai", "human", "ai"]


class TestMemoryMiddleware:
    def test_skips_when_disabled(self):
        middleware = MemoryMiddleware()
        state = {"messages": [FakeMessage("human", "hello"), FakeMessage("ai", "hi")]}
        runtime = MagicMock()

        with patch("src.agents.middlewares.memory_middleware.get_memory_config") as mock_config:
            mock_config.return_value = MagicMock(enabled=False)
            result = middleware.after_agent(state, runtime)
            assert result is None

    def test_skips_when_no_thread_id(self):
        middleware = MemoryMiddleware()
        state = {"messages": [FakeMessage("human", "hello"), FakeMessage("ai", "hi")]}
        runtime = MagicMock()

        with (
            patch("src.agents.middlewares.memory_middleware.get_memory_config") as mock_config,
            patch("src.agents.middlewares.memory_middleware.get_thread_id_from_runtime", return_value=None),
        ):
            mock_config.return_value = MagicMock(enabled=True)
            result = middleware.after_agent(state, runtime)
            assert result is None

    def test_skips_when_no_messages(self):
        middleware = MemoryMiddleware()
        state = {"messages": []}
        runtime = MagicMock()

        with (
            patch("src.agents.middlewares.memory_middleware.get_memory_config") as mock_config,
            patch("src.agents.middlewares.memory_middleware.get_thread_id_from_runtime", return_value="t1"),
        ):
            mock_config.return_value = MagicMock(enabled=True)
            result = middleware.after_agent(state, runtime)
            assert result is None

    def test_queues_when_valid(self):
        middleware = MemoryMiddleware()
        state = {"messages": [FakeMessage("human", "hello"), FakeMessage("ai", "hi")]}
        runtime = MagicMock()
        mock_queue = MagicMock()

        with (
            patch("src.agents.middlewares.memory_middleware.get_memory_config") as mock_config,
            patch("src.agents.middlewares.memory_middleware.get_thread_id_from_runtime", return_value="t1"),
            patch("src.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_queue),
        ):
            mock_config.return_value = MagicMock(enabled=True)
            result = middleware.after_agent(state, runtime)
            assert result is None
            mock_queue.add.assert_called_once()
            call_kwargs = mock_queue.add.call_args
            assert call_kwargs.kwargs.get("thread_id") == "t1" or call_kwargs[1].get("thread_id") == "t1"
