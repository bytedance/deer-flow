"""F1 coverage for grouped, per-server MCP tool discovery."""

from __future__ import annotations

import asyncio
import builtins
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.tools import StructuredTool

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.oauth import get_initial_oauth_headers
from deerflow.mcp.session_pool import ServerBinding, StaleMCPBindingError, normalized_connection_fingerprint
from deerflow.mcp.tasks.runtime import McpTaskConfigurationError
from deerflow.mcp.tools import (
    ServerDiscoveryResult,
    _flatten_server_tool_groups,
    get_mcp_tools,
    get_mcp_tools_by_server,
)


def _tool(name: str) -> StructuredTool:
    async def _call() -> str:
        return name

    return StructuredTool.from_function(coroutine=_call, name=name, description=name)


def _config(servers: dict[str, dict]) -> ExtensionsConfig:
    return ExtensionsConfig.model_validate({"mcpServers": servers})


def _patch_common(monkeypatch, *, oauth_headers=None, interceptors=None):
    headers = oauth_headers or AsyncMock(return_value={})
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", headers)
    monkeypatch.setattr(
        "deerflow.mcp.tools.build_mcp_tool_interceptors",
        interceptors or (lambda *args, **kwargs: []),
    )
    return headers


def test_flatten_server_tool_groups_preserves_enabled_order_and_empty_success():
    a, b = _tool("a"), _tool("b")
    groups = {
        "A": ServerDiscoveryResult(tools=(a,)),
        "B": ServerDiscoveryResult(tools=(b,)),
        "EMPTY": ServerDiscoveryResult(tools=()),
    }

    flattened = _flatten_server_tool_groups(("B", "EMPTY", "A", "ABSENT"), groups)

    assert flattened == [b, a]
    assert flattened[0] is b
    assert flattened[1] is a
    assert "EMPTY" in groups
    assert groups["EMPTY"].tools == ()


def test_server_discovery_result_repr_hides_ownership_handles():
    pool = MagicMock()
    binding = ServerBinding(
        domain="deployment",
        server_name="A",
        epoch=7,
        fingerprint="secret-fingerprint",
    )

    rendered = repr(ServerDiscoveryResult(tools=(), pool=pool, binding=binding))

    assert "pool" not in rendered
    assert "binding" not in rendered
    assert "secret-fingerprint" not in rendered


@pytest.mark.asyncio
async def test_get_mcp_tools_config_load_errors_propagate(monkeypatch):
    from_file = MagicMock(side_effect=FileNotFoundError("missing config"))
    logger_error = MagicMock()
    monkeypatch.setattr("deerflow.mcp.tools.ExtensionsConfig.from_file", from_file)
    monkeypatch.setattr("deerflow.mcp.tools.logger.error", logger_error)

    with pytest.raises(FileNotFoundError, match="missing config"):
        await get_mcp_tools()

    from_file.assert_called_once()
    logger_error.assert_not_called()


@pytest.mark.asyncio
async def test_get_mcp_tools_missing_adapter_returns_before_side_effects(monkeypatch):
    from_file = MagicMock(side_effect=AssertionError("config must not load"))
    get_session_pool = MagicMock(side_effect=AssertionError("pool must not resolve"))
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("langchain_mcp_adapters"):
            raise ImportError("missing adapter")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("deerflow.mcp.tools.ExtensionsConfig.from_file", from_file)
    monkeypatch.setattr("deerflow.mcp.tools.get_session_pool", get_session_pool)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    tools = await get_mcp_tools()

    assert tools == []
    from_file.assert_not_called()
    get_session_pool.assert_not_called()


@pytest.mark.asyncio
async def test_wrap_failure_returns_empty_instead_of_partial_tools(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "stdio", "command": "a-server"},
            "B": {"enabled": True, "type": "stdio", "command": "b-server"},
        }
    )
    pool = MagicMock()
    pool.ensure_binding.side_effect = lambda name, *_args, **_kwargs: ServerBinding(
        domain="deployment",
        server_name=name,
        epoch=1,
        fingerprint=f"fp-{name}",
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return [_tool(f"{server_name}_search")]

    def fake_wrap(tool, server_name, *args, **kwargs):
        if server_name == "A":
            raise RuntimeError("wrap failed")
        return tool

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    _patch_common(monkeypatch)
    monkeypatch.setattr("deerflow.mcp.tools._make_session_pool_tool", fake_wrap)

    tools = await get_mcp_tools(config, session_pool=pool)

    assert tools == []


@pytest.mark.asyncio
async def test_task_configuration_error_waits_for_sibling_discovery(monkeypatch):
    config = _config(
        {
            "A": {
                "enabled": True,
                "type": "http",
                "url": "https://a.example/mcp",
                "task_toolsets": [
                    {
                        "name": "reports",
                        "submit_tool": "submit",
                        "status_tool": "status",
                        "cancel_tool": "cancel",
                    }
                ],
            },
            "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
        }
    )
    sibling_finished = asyncio.Event()

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            if server_name == "B":
                await asyncio.sleep(0.05)
                sibling_finished.set()
                return [_tool("B_search")]
            return []

    manager = MagicMock()
    manager.has_oauth_servers.return_value = False
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_task_oauth_token_manager", lambda config: manager)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])

    with pytest.raises(McpTaskConfigurationError, match="missing raw tool"):
        await get_mcp_tools_by_server(config, server_names={"A", "B"})

    assert sibling_finished.is_set()


@pytest.mark.asyncio
async def test_selected_stdio_isolation_builds_one_client_and_only_its_binding(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "stdio", "command": "a-server"},
            "B": {"enabled": True, "type": "stdio", "command": "b-server"},
        }
    )
    created: list[set[str]] = []
    wrapped: list[str] = []
    oauth_selection: list[set[str]] = []
    binding = ServerBinding(
        domain="deployment",
        server_name="A",
        epoch=1,
        fingerprint="fp-a",
    )
    pool = MagicMock()
    pool.ensure_binding.return_value = binding

    class FakeClient:
        def __init__(self, connections, **kwargs):
            created.append(set(connections))
            self.connections = connections
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            assert server_name in self.connections
            return [_tool(f"{server_name}_search")]

    async def fake_oauth_headers(_config, *, token_manager=None, server_names=None):
        oauth_selection.append(set(server_names or ()))
        return {}

    def fake_wrapper(tool, server_name, *args, **kwargs):
        wrapped.append(server_name)
        return tool

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", fake_oauth_headers)
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])
    monkeypatch.setattr("deerflow.mcp.tools._make_session_pool_tool", fake_wrapper)
    monkeypatch.setattr("deerflow.mcp.tools.get_session_pool", MagicMock(side_effect=AssertionError("caller pool must win")))

    result = await get_mcp_tools_by_server(
        config,
        server_names={"A"},
        session_pool=pool,
    )

    assert created == [{"A"}]
    assert list(result) == ["A"]
    assert [tool.name for tool in result["A"].tools] == ["A_search"]
    assert wrapped == ["A"]
    assert oauth_selection == [{"A"}]
    pool.ensure_binding.assert_called_once()
    assert pool.ensure_binding.call_args.args[0] == "A"
    assert pool.ensure_binding.call_args.args[1] == normalized_connection_fingerprint(
        {"transport": "stdio", "command": "a-server", "args": []},
    )
    assert pool.ensure_binding.call_args.kwargs == {"domain": "deployment"}
    assert result["A"].pool is pool
    assert result["A"].binding is binding


@pytest.mark.asyncio
async def test_each_selected_server_gets_its_own_single_server_client(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
            "C": {"enabled": True, "type": "http", "url": "https://c.example/mcp"},
        }
    )
    created: list[set[str]] = []

    class FakeClient:
        def __init__(self, connections, **kwargs):
            created.append(set(connections))
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return [_tool(f"{server_name}_search")]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    _patch_common(monkeypatch)

    result = await get_mcp_tools_by_server(config, server_names={"A", "B"})

    assert created == [{"A"}, {"B"}]
    assert list(result) == ["A", "B"]
    assert [tool.name for tool in result["A"].tools] == ["A_search"]
    assert [tool.name for tool in result["B"].tools] == ["B_search"]


@pytest.mark.asyncio
async def test_each_client_gets_interceptors_built_from_only_its_server(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
        }
    )
    clients: list[tuple[set[str], list[object]]] = []
    built_for: list[tuple[str, ...]] = []

    class FakeClient:
        def __init__(self, connections, **kwargs):
            interceptors = kwargs.get("tool_interceptors") or []
            clients.append((set(connections), interceptors))
            self.callbacks = None
            self.tool_interceptors = interceptors

        async def get_tools(self, *, server_name=None):
            return [_tool(f"{server_name}_search")]

    def fake_interceptors(server_config, *args, **kwargs):
        built_for.append(tuple(server_config.get_enabled_mcp_servers()))
        return [object()]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", fake_interceptors)

    result = await get_mcp_tools_by_server(config, server_names={"A", "B"})

    assert list(result) == ["A", "B"]
    assert [connections for connections, _ in clients] == [{"A"}, {"B"}]
    assert sorted(built_for) == [("A",), ("B",)]
    assert clients[0][1] is not clients[1][1]


@pytest.mark.asyncio
async def test_failed_discovery_is_absent_but_successful_empty_is_present(monkeypatch):
    config = _config(
        {
            "EMPTY": {"enabled": True, "type": "http", "url": "https://empty.example/mcp"},
            "FAIL": {"enabled": True, "type": "http", "url": "https://fail.example/mcp"},
        }
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            if server_name == "FAIL":
                raise RuntimeError("offline")
            return []

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    _patch_common(monkeypatch)

    result = await get_mcp_tools_by_server(config)

    assert "EMPTY" in result
    assert result["EMPTY"].tools == ()
    assert "FAIL" not in result


@pytest.mark.asyncio
async def test_initial_oauth_headers_only_fetch_selected_names(monkeypatch):
    config = _config(
        {
            "A": {
                "enabled": True,
                "type": "http",
                "url": "https://a.example/mcp",
                "oauth": {"enabled": True, "token_url": "https://auth.example/a"},
            },
            "B": {
                "enabled": True,
                "type": "http",
                "url": "https://b.example/mcp",
                "oauth": {"enabled": True, "token_url": "https://auth.example/b"},
            },
        }
    )
    manager = MagicMock()
    manager.has_oauth_servers.return_value = True
    manager.oauth_server_names.return_value = ["A", "B"]
    manager.get_authorization_header = AsyncMock(side_effect=lambda name: f"Bearer {name}")
    monkeypatch.setattr(
        "deerflow.mcp.oauth.OAuthTokenManager.from_extensions_config",
        lambda config: manager,
    )

    assert await get_initial_oauth_headers(config, server_names={"A"}) == {"A": "Bearer A"}
    manager.get_authorization_header.assert_awaited_once_with("A")

    manager.get_authorization_header.reset_mock()
    assert await get_initial_oauth_headers(config, server_names=set()) == {}
    manager.get_authorization_header.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_mcp_tools_flattens_grouped_discovery_in_enabled_order(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
        }
    )
    a, b = _tool("A_search"), _tool("B_search")
    calls: list[object] = []

    async def fake_grouped(_adapter_symbols, prepared):
        calls.append(prepared)
        return {
            "B": ServerDiscoveryResult(tools=(b,)),
            "A": ServerDiscoveryResult(tools=(a,)),
        }

    monkeypatch.setattr("deerflow.mcp.tools._discover_and_wrap_prepared", fake_grouped)

    tools = await get_mcp_tools(config)

    assert tools == [a, b]
    assert len(calls) == 1
    assert calls[0].config is config


@pytest.mark.asyncio
async def test_get_mcp_tools_full_discovery_preserves_name_order_and_loads_config_once(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
        }
    )

    a_first = _tool("A_first")
    b_first = _tool("B_first")
    b_second = _tool("B_second")

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            if server_name == "A":
                return [a_first]
            return [b_first, b_second]

    from_file = MagicMock(return_value=config)
    monkeypatch.setattr("deerflow.mcp.tools.ExtensionsConfig.from_file", from_file)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    _patch_common(monkeypatch)

    tools = await get_mcp_tools()

    assert [tool.name for tool in tools] == ["A_first", "B_first", "B_second"]
    assert tools == [a_first, b_first, b_second]
    assert tools[0] is a_first
    assert tools[1] is b_first
    assert tools[2] is b_second
    assert from_file.call_count == 1


@pytest.mark.asyncio
async def test_bindings_are_captured_before_the_first_discovery_await(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "stdio", "command": "a-server"},
        }
    )
    order: list[str] = []
    binding = ServerBinding(domain="deployment", server_name="A", epoch=1, fingerprint="fp-a")
    pool = MagicMock()

    def ensure_binding(*args, **kwargs):
        order.append("bind")
        return binding

    pool.ensure_binding.side_effect = ensure_binding

    async def fake_oauth_headers(*args, **kwargs):
        assert order == ["bind"]
        order.append("oauth")
        return {}

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            assert order == ["bind", "oauth"]
            order.append("discover")
            return []

    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", fake_oauth_headers)
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)

    result = await get_mcp_tools_by_server(config, session_pool=pool)

    assert result["A"].tools == ()
    assert result["A"].pool is pool
    assert result["A"].binding is binding
    assert order == ["bind", "oauth", "discover"]
    pool.ensure_binding.assert_called_once()


@pytest.mark.asyncio
async def test_personal_discovery_uses_personal_pool_domain_and_task_scope(monkeypatch):
    config = _config(
        {
            "A": {
                "enabled": True,
                "type": "stdio",
                "command": "a-server",
                "task_toolsets": [
                    {
                        "name": "reports",
                        "submit_tool": "submit",
                        "status_tool": "status",
                        "cancel_tool": "cancel",
                    }
                ],
            }
        }
    )
    pool = MagicMock()
    binding = ServerBinding(domain="personal", server_name="A", epoch=1, fingerprint="fp-a")
    pool.ensure_binding.return_value = binding
    ownership_domains: list[str] = []
    connection_scopes: list[str] = []
    deployment_manager = MagicMock(side_effect=AssertionError("deployment manager used for personal discovery"))
    personal_manager = MagicMock()
    personal_manager.has_oauth_servers.return_value = False

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return [_tool("A_submit")]

    def fake_wrapper(tool, server_name, *args, **kwargs):
        ownership_domains.append(kwargs["ownership_domain"])
        return tool

    def fake_configure(tools, *, server_name, server_config, tool_name_prefix, connection_scope="deployment"):
        connection_scopes.append(connection_scope)
        return tools

    monkeypatch.setattr("deerflow.mcp.user_config.load_user_mcp_config", lambda owner: config)
    monkeypatch.setattr(
        "deerflow.mcp.personal_access.authorized_personal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr("deerflow.mcp.tasks.runtime.is_mcp_task_runtime_available", lambda: True)
    monkeypatch.setattr("deerflow.mcp.tools.OAuthTokenManager.from_extensions_config", lambda config: personal_manager)
    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_task_oauth_token_manager", deployment_manager)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools._make_session_pool_tool", fake_wrapper)
    monkeypatch.setattr("deerflow.mcp.tools._configure_task_tools_for_server", fake_configure)

    result = await get_mcp_tools_by_server(
        config,
        personal_user_id="alice",
        session_pool=pool,
    )

    assert list(result) == ["A"]
    assert pool.ensure_binding.call_args.kwargs == {"domain": "personal"}
    assert ownership_domains == ["personal"]
    assert connection_scopes == ["personal"]
    deployment_manager.assert_not_called()


@pytest.mark.asyncio
async def test_stale_binding_propagates_before_any_client_is_built(monkeypatch):
    config = _config(
        {
            "A": {"enabled": True, "type": "stdio", "command": "a-server"},
        }
    )
    pool = MagicMock()
    pool.ensure_binding.side_effect = StaleMCPBindingError("A")
    clients: list[set[str]] = []

    class FakeClient:
        def __init__(self, connections, **kwargs):
            clients.append(set(connections))

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)

    with pytest.raises(StaleMCPBindingError):
        await get_mcp_tools_by_server(config, session_pool=pool)

    assert clients == []


@pytest.mark.asyncio
async def test_task_configuration_error_propagates_from_grouped_discovery(monkeypatch):
    config = _config(
        {
            "A": {
                "enabled": True,
                "type": "http",
                "url": "https://a.example/mcp",
                "task_toolsets": [
                    {
                        "name": "reports",
                        "submit_tool": "submit",
                        "status_tool": "status",
                        "cancel_tool": "cancel",
                    }
                ],
            }
        }
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return []

    manager = MagicMock()
    manager.has_oauth_servers.return_value = False
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_task_oauth_token_manager", lambda config: manager)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])

    with pytest.raises(McpTaskConfigurationError, match="missing raw tool"):
        await get_mcp_tools_by_server(config, server_names={"A"})


@pytest.mark.asyncio
async def test_selection_matching_only_unknown_or_disabled_names(monkeypatch, caplog):
    """A selection that matches nothing is not "nothing is configured"."""
    config = _config(
        {
            "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            "B": {"enabled": False, "type": "http", "url": "https://b.example/mcp"},
        }
    )
    client_calls: list = []
    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient",
        lambda *args, **kwargs: client_calls.append((args, kwargs)) or MagicMock(),
    )
    headers = AsyncMock(return_value={})
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", headers)

    with caplog.at_level(logging.INFO, logger="deerflow.mcp.tools"):
        assert await get_mcp_tools_by_server(config, server_names={"B", "UNKNOWN"}) == {}

    assert client_calls == []
    headers.assert_not_awaited()
    assert "No enabled MCP servers matched the requested selection" in caplog.text
    assert "No enabled MCP servers configured" not in caplog.text


@pytest.mark.asyncio
async def test_discovery_and_wrapper_use_the_same_session_init_timeout(monkeypatch):
    """Preparation derives the timeout once; discovery and wrapping share it."""
    config = _config(
        {
            "A": {
                "enabled": True,
                "type": "stdio",
                "command": "npx",
                "args": [],
                "session_init_timeout": 5,
            }
        }
    )
    observed: dict[str, float | None] = {}

    class FakeClient:
        def __init__(self, connections, **kwargs):
            pass

        async def get_tools(self, *, server_name=None):
            return [_tool("A_search")]

    real_wait_for = asyncio.wait_for

    async def spy_wait_for(awaitable, timeout):
        observed["discovery"] = timeout
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.asyncio.wait_for", spy_wait_for)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    real_make_tool = __import__("deerflow.mcp.tools", fromlist=["_make_session_pool_tool"])._make_session_pool_tool

    def spy_make_tool(*args, **kwargs):
        observed["wrapper"] = kwargs.get("session_init_timeout")
        return real_make_tool(*args, **kwargs)

    monkeypatch.setattr("deerflow.mcp.tools._make_session_pool_tool", spy_make_tool)

    groups = await get_mcp_tools_by_server(config, server_names={"A"})

    assert len(groups["A"].tools) == 1
    assert observed["discovery"] == 5.0
    assert observed["wrapper"] == observed["discovery"]


@pytest.mark.asyncio
async def test_per_server_discovery_failure_log_redacts_resolved_credentials(monkeypatch, caplog):
    """A failed per-server discovery must not log a credential-bearing URL."""
    from langchain_mcp_adapters import client as adapter_client

    secret = "s3cr3t-pass-123"
    config = _config({"A": {"enabled": True, "type": "http", "url": "https://alice@remote.test/mcp"}})
    _patch_common(monkeypatch)

    class FakeClient:
        def __init__(self, connections, **kwargs) -> None:
            self.callbacks = kwargs.get("callbacks") or []
            self.tool_interceptors = kwargs.get("tool_interceptors") or []
            self.tool_name_prefix = kwargs.get("tool_name_prefix", True)

        async def get_tools(self, *, server_name=None):
            request = httpx.Request("GET", f"https://alice:{secret}@remote.test/mcp")
            raise httpx.HTTPStatusError(
                f"Client error for url '{request.url}'",
                request=request,
                response=httpx.Response(401, request=request),
            )

    monkeypatch.setattr(adapter_client, "MultiServerMCPClient", FakeClient)

    with caplog.at_level("WARNING", logger="deerflow.mcp.tools"):
        result = await get_mcp_tools_by_server(config, server_names={"A"})

    assert result == {}
    assert secret not in caplog.text  # the resolved credential never reaches the log
    assert "server 'A'" in caplog.text  # the offending server name is retained
    assert "HTTPStatusError" in caplog.text  # exception type retained
