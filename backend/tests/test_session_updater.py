"""Unit tests for session memory updater."""

import json
from unittest.mock import Mock, patch

from deerflow.agents.memory.session_storage import create_empty_session_memory
from deerflow.agents.memory.updater import (
    MemoryUpdater,
    update_session_from_conversation,
)
from deerflow.config.session_memory_config import SessionMemoryConfig


class TestSessionMemoryUpdater:
    """Tests for session memory update methods in MemoryUpdater."""

    def setup_method(self):
        """Reset config before each test."""
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=True))

    def test_prepare_session_update_prompt_returns_none_when_disabled(self):
        """_prepare_session_update_prompt() returns None when session memory is disabled."""
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=False))

        updater = MemoryUpdater()
        messages = [Mock(type="human", content="Hello")]

        result = updater._prepare_session_update_prompt(
            messages=messages,
            thread_id="thread_123",
            correction_detected=False,
            reinforcement_detected=False,
        )

        assert result is None

    def test_prepare_session_update_prompt_returns_none_when_no_messages(self):
        """_prepare_session_update_prompt() returns None when messages list is empty."""
        updater = MemoryUpdater()

        result = updater._prepare_session_update_prompt(
            messages=[],
            thread_id="thread_123",
            correction_detected=False,
            reinforcement_detected=False,
        )

        assert result is None

    def test_prepare_session_update_prompt_returns_none_when_storage_unavailable(self):
        """_prepare_session_update_prompt() returns None when session storage is not available."""
        updater = MemoryUpdater()
        messages = [Mock(type="human", content="Hello")]

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=None):
            result = updater._prepare_session_update_prompt(
                messages=messages,
                thread_id="thread_123",
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is None

    def test_prepare_session_update_prompt_builds_prompt(self):
        """_prepare_session_update_prompt() builds prompt with session memory and conversation."""
        updater = MemoryUpdater()
        messages = [
            Mock(type="human", content="I'm debugging the auth issue"),
            Mock(type="ai", content="I'll help you investigate"),
        ]

        mock_storage = Mock()
        mock_storage.load = Mock(return_value=create_empty_session_memory())

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            result = updater._prepare_session_update_prompt(
                messages=messages,
                thread_id="thread_123",
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        current_memory, prompt = result
        assert "session_context" in current_memory
        assert "facts" in current_memory
        assert "debugging" in prompt.lower() or "auth" in prompt.lower()

    def test_apply_session_updates_updates_context(self):
        """_apply_session_updates() updates session_context when shouldUpdate is true."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        update_data = {
            "sessionContext": {
                "summary": "Debugging JWT token expiration issue",
                "shouldUpdate": True,
            },
            "newFacts": [],
            "factsToRemove": [],
        }

        result = updater._apply_session_updates(current_memory, update_data, "thread_123")

        assert result["session_context"]["summary"] == "Debugging JWT token expiration issue"
        assert result["session_context"]["updatedAt"].endswith("Z")

    def test_apply_session_updates_skips_context_when_not_needed(self):
        """_apply_session_updates() skips session_context update when shouldUpdate is false."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        current_memory["session_context"]["summary"] = "Original summary"
        update_data = {
            "sessionContext": {
                "summary": "New summary",
                "shouldUpdate": False,
            },
            "newFacts": [],
            "factsToRemove": [],
        }

        result = updater._apply_session_updates(current_memory, update_data, "thread_123")

        assert result["session_context"]["summary"] == "Original summary"

    def test_apply_session_updates_adds_facts(self):
        """_apply_session_updates() adds new facts with confidence above threshold."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        update_data = {
            "sessionContext": {"shouldUpdate": False},
            "newFacts": [
                {"content": "JWT token expires after 1 hour", "category": "context", "confidence": 0.9},
                {"content": "Low confidence fact", "category": "context", "confidence": 0.3},
            ],
            "factsToRemove": [],
        }

        result = updater._apply_session_updates(current_memory, update_data, "thread_123")

        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "JWT token expires after 1 hour"
        assert result["facts"][0]["confidence"] == 0.9
        assert result["facts"][0]["source"] == "thread_123"

    def test_apply_session_updates_removes_facts(self):
        """_apply_session_updates() removes facts specified in factsToRemove."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        current_memory["facts"] = [
            {"id": "fact_1", "content": "Old fact", "confidence": 0.8},
            {"id": "fact_2", "content": "Another fact", "confidence": 0.7},
        ]
        update_data = {
            "sessionContext": {"shouldUpdate": False},
            "newFacts": [],
            "factsToRemove": ["fact_1"],
        }

        result = updater._apply_session_updates(current_memory, update_data, "thread_123")

        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_2"

    def test_apply_session_updates_enforces_max_facts(self):
        """_apply_session_updates() enforces max_facts limit by keeping highest confidence facts."""
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=True, max_facts=10))

        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        current_memory["facts"] = [
            {"id": f"fact_{i}", "content": f"Fact {i}", "confidence": 0.5 + i * 0.01}
            for i in range(10)
        ]
        update_data = {
            "sessionContext": {"shouldUpdate": False},
            "newFacts": [
                {"content": "High confidence", "category": "context", "confidence": 0.99},
            ],
            "factsToRemove": [],
        }

        result = updater._apply_session_updates(current_memory, update_data, "thread_123")

        assert len(result["facts"]) == 10
        confidences = [f["confidence"] for f in result["facts"]]
        assert 0.99 in confidences
        assert 0.5 not in confidences

    def test_finalize_session_update_saves_to_storage(self):
        """_finalize_session_update() parses LLM response and saves to session storage."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        response_content = json.dumps({
            "sessionContext": {
                "summary": "Updated session context",
                "shouldUpdate": True,
            },
            "newFacts": [
                {"content": "New fact", "category": "context", "confidence": 0.85},
            ],
            "factsToRemove": [],
        })

        mock_storage = Mock()
        mock_storage.save = Mock(return_value=True)

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            result = updater._finalize_session_update(
                current_memory=current_memory,
                response_content=response_content,
                thread_id="thread_123",
                user_id="user_xyz",
            )

        assert result is True
        mock_storage.save.assert_called_once()
        saved_data = mock_storage.save.call_args[0][0]
        assert saved_data["session_context"]["summary"] == "Updated session context"
        assert len(saved_data["facts"]) == 1

    def test_finalize_session_update_handles_markdown_code_blocks(self):
        """_finalize_session_update() strips markdown code blocks from LLM response."""
        updater = MemoryUpdater()
        current_memory = create_empty_session_memory()
        response_content = "```json\n" + json.dumps({
            "sessionContext": {"shouldUpdate": False},
            "newFacts": [],
            "factsToRemove": [],
        }) + "\n```"

        mock_storage = Mock()
        mock_storage.save = Mock(return_value=True)

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            result = updater._finalize_session_update(
                current_memory=current_memory,
                response_content=response_content,
                thread_id="thread_123",
            )

        assert result is True

    def test_update_session_memory_success(self):
        """update_session_memory() successfully updates session memory."""
        updater = MemoryUpdater()
        messages = [
            Mock(type="human", content="I'm working on the budget report"),
            Mock(type="ai", content="I'll help you with that"),
        ]

        mock_storage = Mock()
        mock_storage.load = Mock(return_value=create_empty_session_memory())
        mock_storage.save = Mock(return_value=True)

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "sessionContext": {
                "summary": "Working on Q3 budget report",
                "shouldUpdate": True,
            },
            "newFacts": [
                {"content": "Working on Q3 budget report", "category": "context", "confidence": 0.9},
            ],
            "factsToRemove": [],
        })))

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            with patch.object(updater, '_get_model', return_value=mock_model):
                result = updater.update_session_memory(
                    messages=messages,
                    thread_id="thread_123",
                    user_id="user_xyz",
                )

        assert result is True
        mock_storage.save.assert_called_once()

    def test_update_session_memory_returns_false_when_prepare_fails(self):
        """update_session_memory() returns False when prompt preparation fails."""
        from deerflow.config.session_memory_config import set_session_memory_config
        set_session_memory_config(SessionMemoryConfig(enabled=False))

        updater = MemoryUpdater()
        messages = [Mock(type="human", content="Hello")]

        result = updater.update_session_memory(
            messages=messages,
            thread_id="thread_123",
        )

        assert result is False

    def test_update_session_memory_handles_json_decode_error(self):
        """update_session_memory() returns False when LLM response is invalid JSON."""
        updater = MemoryUpdater()
        messages = [Mock(type="human", content="Hello")]

        mock_storage = Mock()
        mock_storage.load = Mock(return_value=create_empty_session_memory())

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content="Invalid JSON response"))

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            with patch.object(updater, '_get_model', return_value=mock_model):
                result = updater.update_session_memory(
                    messages=messages,
                    thread_id="thread_123",
                )

        assert result is False

    def test_update_session_memory_handles_storage_error(self):
        """update_session_memory() returns False when storage save fails."""
        updater = MemoryUpdater()
        messages = [Mock(type="human", content="Hello")]

        mock_storage = Mock()
        mock_storage.load = Mock(return_value=create_empty_session_memory())
        mock_storage.save = Mock(return_value=False)

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "sessionContext": {"shouldUpdate": False},
            "newFacts": [],
            "factsToRemove": [],
        })))

        with patch('deerflow.agents.memory.updater.get_session_storage', return_value=mock_storage):
            with patch.object(updater, '_get_model', return_value=mock_model):
                result = updater.update_session_memory(
                    messages=messages,
                    thread_id="thread_123",
                )

        assert result is False


class TestUpdateSessionFromConversation:
    """Tests for update_session_from_conversation() convenience function."""

    def test_delegates_to_updater(self):
        """update_session_from_conversation() delegates to MemoryUpdater.update_session_memory()."""
        messages = [Mock(type="human", content="Hello")]

        with patch('deerflow.agents.memory.updater.MemoryUpdater') as MockUpdater:
            mock_instance = Mock()
            mock_instance.update_session_memory = Mock(return_value=True)
            MockUpdater.return_value = mock_instance

            result = update_session_from_conversation(
                messages=messages,
                thread_id="thread_123",
                correction_detected=True,
                reinforcement_detected=False,
                user_id="user_xyz",
            )

        assert result is True
        mock_instance.update_session_memory.assert_called_once_with(
            messages,
            "thread_123",
            True,
            False,
            user_id="user_xyz",
        )
