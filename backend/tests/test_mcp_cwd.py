"""Configured stdio working directories must reach discovery and pooled calls."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.paths import Paths
from deerflow.mcp import tools as mcp_tools
from deerflow.mcp.session_pool import MCPSessionPool


@pytest.mark.asyncio
@pytest.mark.parametrize("relative_script", [True, False], ids=["relative-entrypoint", "relative-tool-input"])
async def test_stdio_cwd_from_config_reaches_discovery_and_tool_calls(tmp_path, monkeypatch, relative_script):
    server_dir = tmp_path / "mcp server"
    server_dir.mkdir()
    (server_dir / "marker.txt").write_text("configured-directory", encoding="utf-8")
    server_path = server_dir / "server.py"
    server_path.write_text(
        """
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cwd-test")

@mcp.tool()
def read_marker() -> str:
    return Path("marker.txt").read_text(encoding="utf-8")

mcp.run(transport="stdio")
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": sys.executable,
                        "args": ["server.py" if relative_script else str(server_path)],
                        "cwd": "$TEST_MCP_CWD",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TEST_MCP_CWD", str(server_dir))
    monkeypatch.setattr(mcp_tools, "get_paths", lambda: Paths(tmp_path / "deerflow"))
    pool = MCPSessionPool()
    monkeypatch.setattr(mcp_tools, "get_session_pool", lambda: pool)
    runtime = SimpleNamespace(context={"thread_id": "thread", "user_id": "user"}, config={})

    try:
        tools = await mcp_tools.get_mcp_tools()
        assert [tool.name for tool in tools] == ["local_read_marker"]
        content, _artifact = await tools[0].coroutine(runtime=runtime)
        assert content[0]["text"] == "configured-directory"
    finally:
        await pool.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cwd_config",
    [{}, {"cwd": None}, {"cwd": ""}, {"cwd": "$TEST_UNSET_MCP_CWD"}],
    ids=["omitted", "null", "empty", "unset-env"],
)
async def test_empty_stdio_cwd_preserves_default_working_directories(tmp_path, monkeypatch, cwd_config):
    launch_dir = tmp_path / "gateway"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.delenv("TEST_UNSET_MCP_CWD", raising=False)
    server_path = tmp_path / "cwd_server.py"
    server_path.write_text(
        """
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cwd-defaults-test")

@mcp.tool(description=str(Path.cwd()))
def read_cwd() -> str:
    return str(Path.cwd())

mcp.run(transport="stdio")
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"local": {"command": sys.executable, "args": [str(server_path)], **cwd_config}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    paths = Paths(tmp_path / "deerflow")
    monkeypatch.setattr(mcp_tools, "get_paths", lambda: paths)
    pool = MCPSessionPool()
    monkeypatch.setattr(mcp_tools, "get_session_pool", lambda: pool)
    runtime = SimpleNamespace(context={"thread_id": "thread", "user_id": "user"}, config={})

    try:
        tools = await mcp_tools.get_mcp_tools()
        assert [tool.name for tool in tools] == ["local_read_cwd"]
        assert Path(tools[0].description) == launch_dir.resolve()
        content, _artifact = await tools[0].coroutine(runtime=runtime)
        assert Path(content[0]["text"]) == paths.sandbox_work_dir("thread", user_id="user").resolve()
    finally:
        await pool.close_all()
