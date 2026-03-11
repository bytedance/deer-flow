"""Test for issue #1016: checkpointer should not return None.

Updated for #1066: default checkpointer is now SqliteSaver (not InMemorySaver)
when langgraph-checkpoint-sqlite is installed.
"""

from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class TestCheckpointerNoneFix:
    """Tests that checkpointer context managers return a valid Checkpointer (not None)."""

    @pytest.mark.anyio
    async def test_async_make_checkpointer_returns_sqlite_when_not_configured(self):
        """make_checkpointer should default to AsyncSqliteSaver (#1066)."""
        from src.agents.checkpointer.async_provider import make_checkpointer

        # Mock get_app_config to return a config with checkpointer=None
        mock_config = MagicMock()
        mock_config.checkpointer = None

        with patch("src.agents.checkpointer.async_provider.get_app_config", return_value=mock_config):
            async with make_checkpointer() as checkpointer:
                # Should return AsyncSqliteSaver, not None
                assert checkpointer is not None
                assert isinstance(checkpointer, AsyncSqliteSaver)

                # Should be able to call alist() without AttributeError
                # This is what LangGraph does and what was failing in issue #1016
                result = []
                async for item in checkpointer.alist(config={"configurable": {"thread_id": "test"}}):
                    result.append(item)

                # Empty list is expected for a fresh checkpointer
                assert result == []

    def test_sync_checkpointer_context_returns_sqlite_when_not_configured(self):
        """checkpointer_context should default to SqliteSaver (#1066)."""
        from src.agents.checkpointer.provider import checkpointer_context

        # Mock get_app_config to return a config with checkpointer=None
        mock_config = MagicMock()
        mock_config.checkpointer = None

        with patch("src.agents.checkpointer.provider.get_app_config", return_value=mock_config):
            with checkpointer_context() as checkpointer:
                # Should return SqliteSaver, not None
                assert checkpointer is not None
                assert isinstance(checkpointer, SqliteSaver)

                # Should be able to call list() without AttributeError
                result = list(checkpointer.list(config={"configurable": {"thread_id": "test"}}))

                # Empty list is expected for a fresh checkpointer
                assert result == []
