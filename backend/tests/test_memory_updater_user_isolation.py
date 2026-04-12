"""Tests for user_id propagation in memory updater."""
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.updater import get_memory_data, clear_memory_data, _save_memory_to_file


def test_get_memory_data_passes_user_id():
    mock_storage = MagicMock()
    mock_storage.load.return_value = {"version": "1.0"}
    with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
        get_memory_data(user_id="alice")
        mock_storage.load.assert_called_once_with(None, user_id="alice")


def test_save_memory_passes_user_id():
    mock_storage = MagicMock()
    mock_storage.save.return_value = True
    with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
        _save_memory_to_file({"version": "1.0"}, user_id="bob")
        mock_storage.save.assert_called_once_with({"version": "1.0"}, None, user_id="bob")


def test_clear_memory_data_passes_user_id():
    mock_storage = MagicMock()
    mock_storage.save.return_value = True
    with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
        clear_memory_data(user_id="charlie")
        # Verify save was called with user_id
        assert mock_storage.save.call_args.kwargs["user_id"] == "charlie"
