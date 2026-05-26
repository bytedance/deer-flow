"""Unit tests for the DeerFlow MCP server module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def _reset_mcp_tools_flag():
    """Reset the module-level _mcp_tools_initialized flag between tests."""
    import deerflow.mcp.server as mod

    original = mod._mcp_tools_initialized
    mod._mcp_tools_initialized = False
    yield
    mod._mcp_tools_initialized = original


def test_create_mcp_server_returns_fastmcp_instance():
    from deerflow.mcp.server import create_mcp_server

    server = create_mcp_server()

    assert server is not None
    assert server.name == "deerflow"


def test_create_mcp_server_registers_two_tools():
    from deerflow.mcp.server import create_mcp_server

    server = create_mcp_server()
    tools = server._tool_manager._tools

    assert "deerflow_research" in tools
    assert "deerflow_ask" in tools
    assert len(tools) == 2


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_ensure_mcp_tools_initializes_once():
    with patch("deerflow.mcp.initialize_mcp_tools", new_callable=AsyncMock) as mock_init:
        from deerflow.mcp.server import _ensure_mcp_tools

        await _ensure_mcp_tools()
        await _ensure_mcp_tools()

        mock_init.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_ensure_mcp_tools_handles_import_failure():
    with patch("deerflow.mcp.initialize_mcp_tools", side_effect=RuntimeError("boom"), new_callable=AsyncMock):
        import deerflow.mcp.server as mod

        await mod._ensure_mcp_tools()

        assert mod._mcp_tools_initialized is True


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_invoke_agent_returns_last_message_content():
    fake_message = MagicMock()
    fake_message.content = "42"

    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"messages": [fake_message], "artifacts": []}

    with (
        patch("deerflow.mcp.server._ensure_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.server.make_lead_agent", return_value=fake_agent),
    ):
        from deerflow.mcp.server import _invoke_agent

        result = await _invoke_agent("What is 6 * 7?")

    assert result == "42"
    fake_agent.ainvoke.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_invoke_agent_appends_artifacts():
    fake_message = MagicMock()
    fake_message.content = "result"

    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"messages": [fake_message], "artifacts": ["artifact-1", "artifact-2"]}

    with (
        patch("deerflow.mcp.server._ensure_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.server.make_lead_agent", return_value=fake_agent),
    ):
        from deerflow.mcp.server import _invoke_agent

        result = await _invoke_agent("query")

    assert "artifact-1" in result
    assert "artifact-2" in result
    assert "--- Artifacts ---" in result


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_invoke_agent_handles_empty_messages():
    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"messages": []}

    with (
        patch("deerflow.mcp.server._ensure_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.server.make_lead_agent", return_value=fake_agent),
    ):
        from deerflow.mcp.server import _invoke_agent

        result = await _invoke_agent("empty")

    assert result == "(DeerFlow returned no messages)"


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_invoke_agent_passes_model_name():
    fake_message = MagicMock()
    fake_message.content = "ok"

    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"messages": [fake_message], "artifacts": []}

    with (
        patch("deerflow.mcp.server._ensure_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.server.make_lead_agent", return_value=fake_agent) as mock_make,
    ):
        from deerflow.mcp.server import _invoke_agent

        await _invoke_agent("q", model_name="gpt-5.3-codex")

    config_arg = mock_make.call_args[0][0]
    assert config_arg["configurable"]["model_name"] == "gpt-5.3-codex"


@pytest.mark.anyio
@pytest.mark.usefixtures("_reset_mcp_tools_flag")
async def test_invoke_agent_plan_mode_config():
    fake_message = MagicMock()
    fake_message.content = "planned"

    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"messages": [fake_message], "artifacts": []}

    with (
        patch("deerflow.mcp.server._ensure_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.server.make_lead_agent", return_value=fake_agent) as mock_make,
    ):
        from deerflow.mcp.server import _invoke_agent

        await _invoke_agent("research this", plan_mode=True, thinking=False)

    config_arg = mock_make.call_args[0][0]
    assert config_arg["configurable"]["is_plan_mode"] is True
    assert config_arg["configurable"]["thinking_enabled"] is False
