# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from pydantic import ValidationError
from src.server.mcp_request import MCPServerMetadataRequest, MCPServerMetadataResponse


def test_mcp_server_metadata_request_required_fields():
    # 'transport' is required
    req = MCPServerMetadataRequest(transport="stdio")
    assert req.transport == "stdio"
    assert req.command is None
    assert req.args is None
    assert req.url is None
    assert req.env is None
    assert req.timeout_seconds is None


def test_mcp_server_metadata_request_optional_fields():
    req = MCPServerMetadataRequest(
        transport="sse",
        command="run",
        args=["--foo", "bar"],
        url="http://localhost:8080",
        env={"FOO": "BAR"},
        timeout_seconds=30,
    )
    assert req.transport == "sse"
    assert req.command == "run"
    assert req.args == ["--foo", "bar"]
    assert req.url == "http://localhost:8080"
    assert req.env == {"FOO": "BAR"}
    assert req.timeout_seconds == 30


def test_mcp_server_metadata_request_missing_transport():
    with pytest.raises(ValidationError):
        MCPServerMetadataRequest()


def test_mcp_server_metadata_response_required_fields():
    resp = MCPServerMetadataResponse(transport="stdio")
    assert resp.transport == "stdio"
    assert resp.command is None
    assert resp.args is None
    assert resp.url is None
    assert resp.env is None
    assert resp.tools == []


def test_mcp_server_metadata_response_optional_fields():
    resp = MCPServerMetadataResponse(
        transport="sse",
        command="run",
        args=["--foo", "bar"],
        url="http://localhost:8080",
        env={"FOO": "BAR"},
        tools=["tool1", "tool2"],
    )
    assert resp.transport == "sse"
    assert resp.command == "run"
    assert resp.args == ["--foo", "bar"]
    assert resp.url == "http://localhost:8080"
    assert resp.env == {"FOO": "BAR"}
    assert resp.tools == ["tool1", "tool2"]


def test_mcp_server_metadata_response_tools_default_factory():
    resp1 = MCPServerMetadataResponse(transport="stdio")
    resp2 = MCPServerMetadataResponse(transport="stdio")
    resp1.tools.append("toolA")
    assert resp2.tools == []  # Should not share list between instances
