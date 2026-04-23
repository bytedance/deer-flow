"""Tests for custom MCP tool interceptors loaded via extensions_config.json."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from deerflow.mcp.tools import get_mcp_tools


def _make_mock_env(*, interceptor_paths=None):
    """Set up mocks for get_mcp_tools() with optional custom interceptors.

    Returns a dict of patch contexts and captured state.
    """
    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[])

    extra = {}
    if interceptor_paths is not None:
        extra["mcpInterceptors"] = interceptor_paths

    patches = {
        "client_cls": patch(
            "langchain_mcp_adapters.client.MultiServerMCPClient",
            return_value=mock_client,
        ),
        "from_file": patch(
            "deerflow.config.extensions_config.ExtensionsConfig.from_file",
            return_value=MagicMock(
                model_extra=extra,
                get_enabled_mcp_servers=MagicMock(return_value={}),
            ),
        ),
        "build_servers": patch(
            "deerflow.mcp.tools.build_servers_config",
            return_value={"test-server": {}},
        ),
        "oauth_headers": patch(
            "deerflow.mcp.tools.get_initial_oauth_headers",
            new_callable=AsyncMock,
            return_value={},
        ),
        "oauth_interceptor": patch(
            "deerflow.mcp.tools.build_oauth_tool_interceptor",
            return_value=None,
        ),
    }
    return patches, mock_client


def test_custom_interceptor_loaded_and_appended():
    """A valid interceptor builder path is resolved, called, and appended to tool_interceptors."""

    async def fake_interceptor(request, handler):
        return await handler(request)

    def fake_builder():
        return fake_interceptor

    patches, mock_client = _make_mock_env(
        interceptor_paths=["my_package.auth:build_interceptor"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
        patch("deerflow.reflection.resolve_variable", return_value=fake_builder),
    ):
        asyncio.run(get_mcp_tools())

        # Verify MultiServerMCPClient received the interceptor
        call_kwargs = mock_cls.call_args
        interceptors = call_kwargs.kwargs.get("tool_interceptors") or call_kwargs[1].get("tool_interceptors", [])
        assert len(interceptors) == 1
        assert interceptors[0] is fake_interceptor


def test_multiple_custom_interceptors():
    """Multiple interceptor paths are all loaded in order."""

    async def interceptor_a(request, handler):
        return await handler(request)

    async def interceptor_b(request, handler):
        return await handler(request)

    builders = {
        "pkg.a:build_a": lambda: interceptor_a,
        "pkg.b:build_b": lambda: interceptor_b,
    }

    patches, mock_client = _make_mock_env(
        interceptor_paths=["pkg.a:build_a", "pkg.b:build_b"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
        patch("deerflow.reflection.resolve_variable", side_effect=lambda path: builders[path]),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_cls.call_args
        interceptors = call_kwargs.kwargs.get("tool_interceptors") or call_kwargs[1].get("tool_interceptors", [])
        assert len(interceptors) == 2
        assert interceptors[0] is interceptor_a
        assert interceptors[1] is interceptor_b


def test_custom_interceptor_builder_returning_none_is_skipped():
    """If a builder returns None, it is not appended to the interceptor list."""
    patches, mock_client = _make_mock_env(
        interceptor_paths=["pkg.noop:build_noop"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
        patch("deerflow.reflection.resolve_variable", return_value=lambda: None),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_cls.call_args
        interceptors = call_kwargs.kwargs.get("tool_interceptors") or call_kwargs[1].get("tool_interceptors", [])
        assert len(interceptors) == 0


def test_custom_interceptor_resolve_error_logs_warning_and_continues():
    """A broken interceptor path logs a warning and does not block tool loading."""
    patches, mock_client = _make_mock_env(
        interceptor_paths=["broken.path:does_not_exist"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
        patch("deerflow.reflection.resolve_variable", side_effect=ImportError("no such module")),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        # Should not raise
        tools = asyncio.run(get_mcp_tools())

        # Tools still loaded successfully (empty in this mock)
        assert tools == []

        # Warning logged with the broken path
        mock_warn.assert_called_once()
        assert "broken.path:does_not_exist" in mock_warn.call_args[0][0]


def test_custom_interceptor_builder_exception_logs_warning_and_continues():
    """If the builder function itself raises, the error is caught and logged."""

    def exploding_builder():
        raise RuntimeError("builder exploded")

    patches, mock_client = _make_mock_env(
        interceptor_paths=["pkg.bad:exploding_builder"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
        patch("deerflow.reflection.resolve_variable", return_value=exploding_builder),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        tools = asyncio.run(get_mcp_tools())

        assert tools == []
        mock_warn.assert_called_once()
        assert "pkg.bad:exploding_builder" in mock_warn.call_args[0][0]


def test_no_mcp_interceptors_field_is_safe():
    """When mcpInterceptors is absent from config, no interceptors are added."""
    patches, mock_client = _make_mock_env(interceptor_paths=None)

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patches["oauth_interceptor"],
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_cls.call_args
        interceptors = call_kwargs.kwargs.get("tool_interceptors") or call_kwargs[1].get("tool_interceptors", [])
        assert len(interceptors) == 0


def test_custom_interceptor_coexists_with_oauth_interceptor():
    """Custom interceptors are appended after the OAuth interceptor."""

    async def oauth_fn(request, handler):
        return await handler(request)

    async def custom_fn(request, handler):
        return await handler(request)

    patches, mock_client = _make_mock_env(
        interceptor_paths=["pkg.custom:build_custom"],
    )

    with (
        patches["client_cls"] as mock_cls,
        patches["from_file"],
        patches["build_servers"],
        patches["oauth_headers"],
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=oauth_fn),
        patch("deerflow.reflection.resolve_variable", return_value=lambda: custom_fn),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_cls.call_args
        interceptors = call_kwargs.kwargs.get("tool_interceptors") or call_kwargs[1].get("tool_interceptors", [])
        assert len(interceptors) == 2
        assert interceptors[0] is oauth_fn
        assert interceptors[1] is custom_fn
