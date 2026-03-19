"""Test for 问题 #1016: checkpointer should not 返回 None."""

from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver


class TestCheckpointerNoneFix:
    """Tests that checkpointer context managers 返回 InMemorySaver instead of None."""

    @pytest.mark.anyio
    async def test_async_make_checkpointer_returns_in_memory_saver_when_not_configured(self):
        """make_checkpointer should 返回 InMemorySaver when 配置.checkpointer is None."""
        from deerflow.agents.checkpointer.async_provider import make_checkpointer

        #    Mock get_app_config to 返回 a 配置 with checkpointer=None


        mock_config = MagicMock()
        mock_config.checkpointer = None

        with patch("deerflow.agents.checkpointer.async_provider.get_app_config", return_value=mock_config):
            async with make_checkpointer() as checkpointer:
                #    Should 返回 InMemorySaver, not None


                assert checkpointer is not None
                assert isinstance(checkpointer, InMemorySaver)

                #    Should be able to call alist() without AttributeError


                #    This is what LangGraph does and what was failing in 问题 #1016


                result = []
                async for item in checkpointer.alist(config={"configurable": {"thread_id": "test"}}):
                    result.append(item)

                #    Empty 列表 is expected 对于 a fresh checkpointer


                assert result == []

    def test_sync_checkpointer_context_returns_in_memory_saver_when_not_configured(self):
        """checkpointer_context should 返回 InMemorySaver when 配置.checkpointer is None."""
        from deerflow.agents.checkpointer.provider import checkpointer_context

        #    Mock get_app_config to 返回 a 配置 with checkpointer=None


        mock_config = MagicMock()
        mock_config.checkpointer = None

        with patch("deerflow.agents.checkpointer.provider.get_app_config", return_value=mock_config):
            with checkpointer_context() as checkpointer:
                #    Should 返回 InMemorySaver, not None


                assert checkpointer is not None
                assert isinstance(checkpointer, InMemorySaver)

                #    Should be able to call 列表() without AttributeError


                result = list(checkpointer.list(config={"configurable": {"thread_id": "test"}}))

                #    Empty 列表 is expected 对于 a fresh checkpointer


                assert result == []
