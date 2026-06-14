"""Test configuration for the CLI test suite.

Pre-mocks external dependencies (DeerFlowClient, SqliteSaver) so that
engine.py can be imported without pulling in the full LangGraph runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make 'cli' package importable from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Pre-mock DeerFlowClient — each constructor call returns a fresh mock so
# per-session client identity checks work correctly.
# ---------------------------------------------------------------------------


def _make_deerflow_client(*args, **kwargs):
    client = MagicMock()
    client.stream.return_value = iter([])
    client.get_thread.return_value = {"checkpoints": []}
    client.list_models.return_value = {"models": []}
    client.list_skills.return_value = {"skills": []}
    client.upload_files.return_value = {"message": "ok"}
    client.list_uploads.return_value = {"count": 0, "files": []}
    client.delete_upload.return_value = {"message": "deleted"}
    client.get_memory.return_value = {"facts": []}
    client.clear_memory.return_value = None
    client.update_skill.return_value = None
    return client


_mock_client = MagicMock()
_mock_client.side_effect = _make_deerflow_client

sys.modules["deerflow.client"] = MagicMock(DeerFlowClient=_mock_client)

# ---------------------------------------------------------------------------
# Pre-mock SqliteSaver — each from_conn_string call returns a fresh context
# manager so per-session checkpointer identity works correctly.
# ---------------------------------------------------------------------------


def _make_sqlite_cm(conn_string=None):
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    return cm


_mock_sqlite_saver = MagicMock()
_mock_sqlite_saver.from_conn_string.side_effect = _make_sqlite_cm

sys.modules["langgraph.checkpoint.sqlite"] = MagicMock(SqliteSaver=_mock_sqlite_saver)
sys.modules["langgraph.checkpoint"] = MagicMock()
sys.modules["langgraph"] = MagicMock()
