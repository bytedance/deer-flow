"""Tests for thread title fallback to agent display_name."""

import pytest

from deerflow.config.agents_config import AgentConfig

_PATCH_LOAD = "deerflow.config.agents_config.load_agent_config"
_PATCH_THREAD_STORE = "app.gateway.deps.get_thread_store"


class TestResolveAgentDisplayName:
    """Test _resolve_agent_display_name helper in threads router."""

    def test_returns_agent_name_when_no_config(self):
        """When agent config doesn't exist, falls back to raw agent_name."""
        from unittest.mock import patch

        from app.gateway.routers.threads import _resolve_agent_display_name

        with patch(_PATCH_LOAD, return_value=None):
            result = _resolve_agent_display_name("nonexistent-agent-xyz")
        assert result == "nonexistent-agent-xyz"

    def test_returns_agent_name_when_no_display_name(self):
        """When agent config exists but has no display_name, returns agent_name."""
        from unittest.mock import patch

        from app.gateway.routers.threads import _resolve_agent_display_name

        mock_config = AgentConfig(name="test-agent")
        with patch(_PATCH_LOAD, return_value=mock_config) as mock_load:
            result = _resolve_agent_display_name("test-agent")
            assert result == "test-agent"
            mock_load.assert_called_once_with("test-agent")

    def test_returns_display_name_when_configured(self):
        """When agent config has display_name, returns it."""
        from unittest.mock import patch

        from app.gateway.routers.threads import _resolve_agent_display_name

        mock_config = AgentConfig(name="ai-report--daily", display_name="设备运行日报")
        with patch(_PATCH_LOAD, return_value=mock_config):
            result = _resolve_agent_display_name("ai-report--daily")
            assert result == "设备运行日报"

    def test_handles_load_exception_gracefully(self):
        """When load_agent_config raises, falls back to agent_name."""
        from unittest.mock import patch

        from app.gateway.routers.threads import _resolve_agent_display_name

        with patch(_PATCH_LOAD, side_effect=Exception("boom")):
            result = _resolve_agent_display_name("test-agent")
            assert result == "test-agent"


class TestSearchThreadsTitleFallback:
    """Test that search_threads falls back to agent display_name for title."""

    @pytest.mark.asyncio
    async def test_uses_agent_display_name_when_no_title(self):
        """When thread has no title/display_name, uses agent's display_name."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.gateway.routers.threads import ThreadSearchRequest, search_threads

        mock_thread_store = AsyncMock()
        mock_thread_store.search = AsyncMock(
            return_value=[
                {
                    "thread_id": "t1",
                    "status": "idle",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "metadata": {"agent_name": "ai-report--daily"},
                    "values": {},
                    "display_name": None,
                }
            ]
        )

        mock_request = MagicMock()
        mock_config = AgentConfig(name="ai-report--daily", display_name="设备运行日报")

        with (
            patch(_PATCH_THREAD_STORE, return_value=mock_thread_store),
            patch(_PATCH_LOAD, return_value=mock_config),
        ):
            body = ThreadSearchRequest()
            results = await search_threads(body, mock_request)

        assert len(results) == 1
        assert results[0].values.get("title") == "设备运行日报"

    @pytest.mark.asyncio
    async def test_prefers_display_name_over_agent_fallback(self):
        """When thread has display_name set, uses it instead of agent fallback."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.gateway.routers.threads import ThreadSearchRequest, search_threads

        mock_thread_store = AsyncMock()
        mock_thread_store.search = AsyncMock(
            return_value=[
                {
                    "thread_id": "t1",
                    "status": "idle",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "metadata": {"agent_name": "ai-report--daily"},
                    "values": {},
                    "display_name": "已同步的标题",
                }
            ]
        )

        mock_request = MagicMock()

        with (
            patch(_PATCH_THREAD_STORE, return_value=mock_thread_store),
        ):
            body = ThreadSearchRequest()
            results = await search_threads(body, mock_request)

        assert len(results) == 1
        assert results[0].values.get("title") == "已同步的标题"

    @pytest.mark.asyncio
    async def test_no_title_when_no_agent_name(self):
        """When thread has no agent_name and no title, values.title stays empty."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.gateway.routers.threads import ThreadSearchRequest, search_threads

        mock_thread_store = AsyncMock()
        mock_thread_store.search = AsyncMock(
            return_value=[
                {
                    "thread_id": "t1",
                    "status": "idle",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "metadata": {},
                    "values": {},
                    "display_name": None,
                }
            ]
        )

        mock_request = MagicMock()

        with (
            patch(_PATCH_THREAD_STORE, return_value=mock_thread_store),
        ):
            body = ThreadSearchRequest()
            results = await search_threads(body, mock_request)

        assert len(results) == 1
        assert results[0].values.get("title") is None
