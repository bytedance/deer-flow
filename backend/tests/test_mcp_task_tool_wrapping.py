import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.tasks.runtime import (
    McpTaskConfigurationError,
    set_mcp_task_config_snapshot,
    set_mcp_task_submitter,
)
from deerflow.mcp.tools import _configure_task_tools_for_server, get_mcp_tools


class _SubmitArgs(BaseModel):
    topic: str


def _tool(name: str, *, description: str | None = None) -> StructuredTool:
    async def call(topic: str):
        return topic

    return StructuredTool(
        name=name,
        description=description if description is not None else name,
        args_schema=_SubmitArgs,
        coroutine=call,
    )


def _server_config() -> McpServerConfig:
    return McpServerConfig.model_validate(
        {
            "task_toolsets": [
                {
                    "name": "report-generation",
                    "submit_tool": "submit_report",
                    "status_tool": "get_report_status",
                    "cancel_tool": "cancel_report",
                }
            ]
        }
    )


class FakeSubmitter:
    def __init__(self):
        self.calls = []

    async def submit(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "mcp-task-local-1",
            "status": "submitted",
            "remote_task_id": "must-not-leak",
            "driver_data": {"must": "not leak"},
        }


def test_unconfigured_server_tools_are_returned_unchanged() -> None:
    tools = [_tool("reports_search")]

    configured = _configure_task_tools_for_server(
        tools,
        server_name="reports",
        server_config=McpServerConfig(),
        tool_name_prefix=True,
    )

    assert configured == tools
    assert configured[0] is tools[0]


def test_configured_status_and_cancel_tools_are_hidden_from_the_agent() -> None:
    tools = [
        _tool("reports_submit_report"),
        _tool("reports_get_report_status"),
        _tool("reports_cancel_report"),
        _tool("reports_search"),
    ]

    configured = _configure_task_tools_for_server(
        tools,
        server_name="reports",
        server_config=_server_config(),
        tool_name_prefix=True,
    )

    assert [tool.name for tool in configured] == ["reports_submit_report", "reports_search"]


def test_submit_wrapper_preserves_server_description_and_appends_background_contract() -> None:
    tools = [
        _tool(
            "submit_report",
            description="Generate a quarterly financial report for the requested topic.",
        ),
        _tool("get_report_status"),
        _tool("cancel_report"),
    ]

    configured = _configure_task_tools_for_server(
        tools,
        server_name="reports",
        server_config=_server_config(),
        tool_name_prefix=False,
    )

    assert configured[0].description == (
        "Generate a quarterly financial report for the requested topic.\n\nSubmitted as durable background task 'report-generation'; returns a DeerFlow task ID immediately and status polling is handled automatically."
    )


def test_configured_task_toolsets_fail_when_a_raw_tool_is_missing() -> None:
    with pytest.raises(McpTaskConfigurationError, match="cancel_report"):
        _configure_task_tools_for_server(
            [_tool("reports_submit_report"), _tool("reports_get_report_status")],
            server_name="reports",
            server_config=_server_config(),
            tool_name_prefix=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_scope", ["deployment", "personal"])
async def test_submit_wrapper_persists_before_returning_only_the_local_handle(connection_scope: str) -> None:
    submitter = FakeSubmitter()
    set_mcp_task_submitter(submitter)
    try:
        configured = _configure_task_tools_for_server(
            [
                _tool("submit_report"),
                _tool("get_report_status"),
                _tool("cancel_report"),
            ],
            server_name="reports",
            server_config=_server_config(),
            tool_name_prefix=False,
            connection_scope=connection_scope,
        )
        submit_tool = configured[0]
        runtime = SimpleNamespace(
            context={"thread_id": "thread-1", "thread_incarnation": "incarnation-1", "run_id": "run-1"},
            config={},
            tool_call_id="call-1",
        )

        result = await submit_tool.coroutine(runtime=runtime, topic="MCP")

        assert result == {
            "task_id": "mcp-task-local-1",
            "task_name": "report-generation",
            "status": "submitted",
            "message": "Task is running in the background.",
        }
        call = submitter.calls[0]
        request = call["request"]
        assert call["driver_name"] == "ordinary-tools"
        assert request.user_id == "test-user-autouse"
        assert request.thread_id == "thread-1"
        assert request.run_id == "run-1"
        assert request.tool_call_id == "call-1"
        assert request.arguments == {"topic": "MCP"}
        assert request.driver_data == {
            "submit_tool": "submit_report",
            "status_tool": "get_report_status",
            "cancel_tool": "cancel_report",
            "connection_scope": connection_scope,
        }
    finally:
        set_mcp_task_submitter(None)


@pytest.mark.asyncio
async def test_submit_wrapper_fails_clearly_without_gateway_task_runtime() -> None:
    set_mcp_task_submitter(None)
    configured = _configure_task_tools_for_server(
        [_tool("submit_report"), _tool("get_report_status"), _tool("cancel_report")],
        server_name="reports",
        server_config=_server_config(),
        tool_name_prefix=False,
    )

    with pytest.raises(McpTaskConfigurationError, match="not initialized"):
        await configured[0].coroutine(topic="MCP")


@pytest.mark.asyncio
async def test_tool_reload_rejects_task_server_runtime_config_drift() -> None:
    startup = ExtensionsConfig(mcpServers={"reports": _server_config()})
    current = ExtensionsConfig(mcpServers={"reports": _server_config()})
    current.mcp_servers["reports"].env["TOKEN"] = "rotated"
    set_mcp_task_config_snapshot(startup)
    try:
        with (
            patch(
                "deerflow.mcp.tools.ExtensionsConfig.from_file",
                return_value=current,
            ),
            pytest.raises(McpTaskConfigurationError, match="reports.*restart"),
        ):
            await get_mcp_tools()
    finally:
        set_mcp_task_config_snapshot(None)


def _discovery_config(*, reports_init_timeout: float | None = None) -> ExtensionsConfig:
    reports = {"type": "http", "url": "http://reports.invalid/mcp", "task_toolsets": _server_config().model_dump()["task_toolsets"]}
    if reports_init_timeout is not None:
        reports["session_init_timeout"] = reports_init_timeout
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "healthy": {"type": "http", "url": "http://healthy.invalid/mcp"},
                "reports": reports,
            }
        }
    )


def _discovery_client(reports_discovery):
    class FakeClient:
        def __init__(self, connections, *, callbacks=None, tool_interceptors=None, tool_name_prefix=False) -> None:
            self.callbacks = callbacks
            self.tool_interceptors = tool_interceptors or []

        async def get_tools(self, *, server_name=None):
            if server_name == "reports":
                return await reports_discovery()
            return [_tool("healthy_search")]

    return FakeClient


async def _reports_unreachable():
    raise ConnectionError("reports is down")


async def _reports_hangs():
    await asyncio.sleep(60)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reports_discovery", "reports_init_timeout"),
    [(_reports_unreachable, None), (_reports_hangs, 0.05)],
    ids=["discovery-error", "discovery-timeout"],
)
async def test_failed_task_server_discovery_keeps_healthy_server_tools(reports_discovery, reports_init_timeout) -> None:
    # A task server that never answered has not shown its task_toolsets to be
    # wrong; it is skipped like any other failed server instead of raising.
    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _discovery_client(reports_discovery)):
        tools = await asyncio.wait_for(get_mcp_tools(_discovery_config(reports_init_timeout=reports_init_timeout)), timeout=5)

    assert [tool.name for tool in tools] == ["healthy_search"]


@pytest.mark.asyncio
async def test_task_server_answering_with_no_tools_still_fails() -> None:
    # An empty answer is a successful discovery, so the missing raw tools are a
    # configuration error rather than an outage.
    async def reports_without_tools():
        return []

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", _discovery_client(reports_without_tools)),
        pytest.raises(McpTaskConfigurationError, match="cancel_report, get_report_status, submit_report"),
    ):
        await get_mcp_tools(_discovery_config())
