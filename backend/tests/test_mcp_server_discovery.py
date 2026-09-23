import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool

from deerflow.mcp.tools import ServerDiscoveryResult, _flatten_server_tool_groups


def _tool(name: str) -> StructuredTool:
    async def _call() -> str:
        return name

    return StructuredTool.from_function(coroutine=_call, name=name, description=name)


def test_flatten_order_preserves_tool_identity_and_empty_success():
    a, b = _tool("a"), _tool("b")
    grouped = {
        "A": ServerDiscoveryResult(tools=(a,)),
        "B": ServerDiscoveryResult(tools=(b,)),
        "EMPTY": ServerDiscoveryResult(tools=()),
    }
    flattened = _flatten_server_tool_groups(("B", "EMPTY", "A"), grouped)
    assert flattened == [b, a]
    assert flattened[0] is b and flattened[1] is a
    assert "EMPTY" in grouped and grouped["EMPTY"].tools == ()


@pytest.mark.asyncio
async def test_selected_discovery_never_builds_an_unselected_client(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
                "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
            }
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
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    result = await get_mcp_tools_by_server(config, server_names={"A"})

    assert created == [{"A"}]
    assert list(result) == ["A"]
    assert [t.name for t in result["A"].tools] == ["A_search"]


@pytest.mark.asyncio
async def test_removed_server_does_not_leak_credentials_into_reused_server_client(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    first_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://a.example/mcp",
                    "headers": {"X-Token": "A-secret"},
                    "oauth": {"enabled": True, "token_url": "https://auth.example/a"},
                },
                "B": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://b.example/mcp",
                    "headers": {"X-Token": "B-secret"},
                    "oauth": {"enabled": True, "token_url": "https://auth.example/b"},
                },
            }
        }
    )
    second_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "B": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://b.example/mcp",
                    "headers": {"X-Token": "B-secret"},
                    "oauth": {"enabled": True, "token_url": "https://auth.example/b"},
                },
            }
        }
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.connections = connections
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            async def observe_connections():
                return {name: dict(connection) for name, connection in self.connections.items()}

            return [
                StructuredTool.from_function(
                    coroutine=observe_connections,
                    name=f"{server_name}_observe",
                    description="observe client connections",
                )
            ]

    async def fake_oauth_headers(_config, *, server_names=None):
        return {name: f"Bearer {name}-token" for name in (server_names or ())}

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", fake_oauth_headers)
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    first = await get_mcp_tools_by_server(first_config)
    first_observed = await first["B"].tools[0].ainvoke({})
    assert set(first_observed) == {"B"}

    second = await get_mcp_tools_by_server(second_config)
    second_observed = await second["B"].tools[0].ainvoke({})

    assert set(second_observed) == {"B"}
    assert "A" not in second_observed
    assert second_observed["B"]["headers"]["Authorization"] == "Bearer B-token"
    assert "A-secret" not in repr(second_observed)
    assert "Bearer A-token" not in repr(second_observed)


@pytest.mark.asyncio
async def test_selected_empty_set_builds_no_client(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
            }
        }
    )
    client = AsyncMock()
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", client)

    assert await get_mcp_tools_by_server(config, server_names=set()) == {}
    client.assert_not_called()


@pytest.mark.asyncio
async def test_one_server_discovery_failure_does_not_hide_successful_sibling(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "GOOD": {"enabled": True, "type": "http", "url": "https://good.example/mcp"},
                "FAIL": {"enabled": True, "type": "http", "url": "https://fail.example/mcp"},
            }
        }
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            if server_name == "FAIL":
                raise RuntimeError("offline")
            return [_tool(f"{server_name}_search")]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    result = await get_mcp_tools_by_server(config)

    assert list(result) == ["GOOD"]
    assert [t.name for t in result["GOOD"].tools] == ["GOOD_search"]


@pytest.mark.asyncio
async def test_successful_empty_is_present_but_failure_is_absent(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "EMPTY": {"enabled": True, "type": "http", "url": "https://empty.example/mcp"},
                "FAIL": {"enabled": True, "type": "http", "url": "https://fail.example/mcp"},
            }
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
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    result = await get_mcp_tools_by_server(config)

    assert result["EMPTY"].tools == ()
    assert "FAIL" not in result


@pytest.mark.asyncio
async def test_discovery_timeout_is_absent_and_retried(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "SLOW": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://slow.example/mcp",
                    "session_init_timeout": 0.01,
                },
            }
        }
    )
    attempts = 0

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(60)

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    first = await get_mcp_tools_by_server(config)
    second = await get_mcp_tools_by_server(config)

    assert "SLOW" not in first
    assert "SLOW" not in second
    assert attempts == 2


@pytest.mark.asyncio
async def test_initial_oauth_headers_only_fetch_selected_names(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.oauth import get_initial_oauth_headers

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
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
        }
    )
    manager = MagicMock()
    manager.has_oauth_servers.return_value = True
    manager.oauth_server_names.return_value = ("A", "B")
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
async def test_task_snapshot_guard_validates_full_config_before_selected_discovery(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, set_mcp_task_config_snapshot
    from deerflow.mcp.tools import _configure_task_tools_for_server, get_mcp_tools_by_server

    full_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "a-server",
                    "task_toolsets": [{"name": "reports", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                },
                "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
            }
        }
    )
    changed_config = full_config.model_copy(deep=True)
    changed_config.mcp_servers["A"].command = "a-replaced-server"
    created: list[set[str]] = []

    class FakeClient:
        def __init__(self, connections, **kwargs):
            created.append(set(connections))
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return [_tool(f"{server_name}_search")]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])

    set_mcp_task_config_snapshot(full_config)
    try:
        with pytest.raises(McpTaskConfigurationError, match="A.*restart"):
            await get_mcp_tools_by_server(changed_config, server_names={"B"})
        assert created == []

        unchanged = await get_mcp_tools_by_server(full_config, server_names={"B"})
        assert list(unchanged) == ["B"]
        assert created == [{"B"}]

        task_config = full_config.mcp_servers["A"]
        agent_tools = _configure_task_tools_for_server(
            [_tool("A_submit"), _tool("A_status"), _tool("A_cancel")],
            server_name="A",
            server_config=task_config,
            tool_name_prefix=True,
        )
        assert [tool.name for tool in agent_tools] == ["A_submit"]
        assert "durable background task" in agent_tools[0].description
    finally:
        set_mcp_task_config_snapshot(None)


@pytest.mark.asyncio
async def test_selected_invalid_connection_logs_selected_names_not_no_enabled(monkeypatch, caplog):
    import logging

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
                "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
            }
        }
    )

    def reject_connection(name, server):
        raise ValueError(f"invalid connection for {name}")

    monkeypatch.setattr("deerflow.mcp.client.build_server_params", reject_connection)
    with caplog.at_level(logging.INFO, logger="deerflow.mcp.tools"):
        result = await get_mcp_tools_by_server(config, server_names={"A"})

    assert result == {}
    assert "No valid MCP connections for selected servers: ['A']" in caplog.text
    assert "No enabled MCP servers configured" not in caplog.text


@pytest.mark.asyncio
async def test_discovery_log_counts_only_selected_successful_groups(monkeypatch, caplog):
    import logging

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tools import get_mcp_tools_by_server

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "A": {"enabled": True, "type": "http", "url": "https://a.example/mcp"},
                "B": {"enabled": True, "type": "http", "url": "https://b.example/mcp"},
                "C": {"enabled": True, "type": "http", "url": "https://c.example/mcp"},
            }
        }
    )

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.callbacks = None
            self.tool_interceptors = kwargs.get("tool_interceptors") or []

        async def get_tools(self, *, server_name=None):
            return [_tool("A_search")] if server_name == "A" else []

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", AsyncMock(return_value={}))
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *a, **kw: [])
    with caplog.at_level(logging.INFO, logger="deerflow.mcp.tools"):
        groups = await get_mcp_tools_by_server(config, server_names={"A", "B"})

    assert list(groups) == ["A", "B"]
    assert len(groups["A"].tools) == 1
    assert groups["B"].tools == ()
    assert "Discovered 1 tool(s) from 2 MCP server(s)" in caplog.text
    assert "Successfully loaded" not in caplog.text
