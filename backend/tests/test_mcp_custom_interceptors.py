"""Tests for custom MCP tool interceptors loaded via extensions_config.json."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from deerflow.mcp.tools import get_mcp_tools


def _make_patches(*, interceptor_paths=None, server_count=1):
    """Set up mocks for get_mcp_tools() with optional custom interceptors.

    Returns a dict of patch context managers.
    """
    servers = {}
    for i in range(server_count):
        servers[f"test-server-{i}"] = {"transport": "sse", "url": f"http://localhost:{8000 + i}/sse"}

    return {
        "from_file": patch(
            "deerflow.config.extensions_config.ExtensionsConfig.from_file",
            return_value=MagicMock(
                model_extra={"mcpInterceptors": interceptor_paths} if interceptor_paths is not None else {},
                get_enabled_mcp_servers=MagicMock(return_value={}),
            ),
        ),
        "build_servers": patch(
            "deerflow.mcp.tools.build_servers_config",
            return_value=servers,
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
        "load_tools": patch(
            "langchain_mcp_adapters.tools.load_mcp_tools",
            new_callable=AsyncMock,
            return_value=[],
        ),
    }


def test_custom_interceptor_loaded_and_appended():
    """A valid interceptor builder path is resolved, called, and passed to load_mcp_tools."""

    async def fake_interceptor(request, handler):
        return await handler(request)

    def fake_builder():
        return fake_interceptor

    p = _make_patches(interceptor_paths=["my_package.auth:build_interceptor"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.resolve_variable", return_value=fake_builder),
    ):
        asyncio.run(get_mcp_tools())

        # Verify load_mcp_tools was called with the interceptor
        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
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

    p = _make_patches(interceptor_paths=["pkg.a:build_a", "pkg.b:build_b"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.resolve_variable", side_effect=lambda path: builders[path]),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 2
        assert interceptors[0] is interceptor_a
        assert interceptors[1] is interceptor_b


def test_custom_interceptor_builder_returning_none_is_skipped():
    """If a builder returns None, it is not appended to the interceptor list."""

    p = _make_patches(interceptor_paths=["pkg.noop:build_noop"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: None),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 0


def test_custom_interceptor_resolve_error_logs_warning_and_continues():
    """A broken interceptor path logs a warning and does not block tool loading."""

    p = _make_patches(interceptor_paths=["broken.path:does_not_exist"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"],
        patch("deerflow.mcp.tools.resolve_variable", side_effect=ImportError("no such module")),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        tools = asyncio.run(get_mcp_tools())

        assert tools == []
        # Should have at least one warning about the interceptor
        warning_calls = [c for c in mock_warn.call_args_list if "broken.path:does_not_exist" in str(c)]
        assert len(warning_calls) >= 1


def test_custom_interceptor_builder_exception_logs_warning_and_continues():
    """If the builder function itself raises, the error is caught and logged."""

    def exploding_builder():
        raise RuntimeError("builder exploded")

    p = _make_patches(interceptor_paths=["pkg.bad:exploding_builder"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=exploding_builder),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        tools = asyncio.run(get_mcp_tools())

        assert tools == []
        warning_calls = [c for c in mock_warn.call_args_list if "pkg.bad:exploding_builder" in str(c)]
        assert len(warning_calls) >= 1


def test_no_mcp_interceptors_field_is_safe():
    """When mcpInterceptors is absent from config, no interceptors are added."""

    p = _make_patches(interceptor_paths=None)

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 0


def test_custom_interceptor_coexists_with_oauth_interceptor():
    """Custom interceptors are appended after the OAuth interceptor."""

    async def oauth_fn(request, handler):
        return await handler(request)

    async def custom_fn(request, handler):
        return await handler(request)

    p = _make_patches(interceptor_paths=["pkg.custom:build_custom"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=oauth_fn),
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: custom_fn),
        p["load_tools"] as mock_load,
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 2
        assert interceptors[0] is oauth_fn
        assert interceptors[1] is custom_fn


def test_mcp_interceptors_single_string_is_normalized():
    """A single string value for mcpInterceptors is normalized to a list."""

    async def fake_interceptor(request, handler):
        return await handler(request)

    p = _make_patches(interceptor_paths="pkg.single:build_it")

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: fake_interceptor),
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 1


def test_mcp_interceptors_invalid_type_logs_warning():
    """A non-list, non-string value for mcpInterceptors logs a warning and is skipped."""

    p = _make_patches(interceptor_paths=42)

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 0
        mock_warn.assert_called()
        assert "must be a list" in str(mock_warn.call_args)


def test_custom_interceptor_non_callable_return_logs_warning():
    """If a builder returns a non-callable value, it is skipped with a warning."""

    p = _make_patches(interceptor_paths=["pkg.bad:returns_string"])

    with (
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        p["load_tools"] as mock_load,
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: "not_a_callable"),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        asyncio.run(get_mcp_tools())

        call_kwargs = mock_load.call_args.kwargs
        interceptors = call_kwargs.get("tool_interceptors", [])
        assert len(interceptors) == 0
        mock_warn.assert_called()
        assert "non-callable" in str(mock_warn.call_args)
