"""Admission and per-call policy reloads must keep filesystem I/O off-loop."""

import asyncio
import json

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.runtime import Runtime
from support.mcp_agent_auth import agent_auth_env as agent_auth_env
from support.mcp_agent_auth import agent_mcp_transport as agent_mcp_transport

from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config
from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, build_agent_auth_interceptor, capture_agent_authority, validate_task_agent_reference
from deerflow.utils.assembly_io import run_assembly


@pytest.mark.asyncio
async def test_cold_admission_and_live_policy_reload(agent_auth_env, agent_mcp_transport, tmp_path, monkeypatch):
    env = agent_auth_env
    path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    data = env.config.model_dump(mode="json", exclude={"extensions"})
    await asyncio.to_thread(path.write_text, json.dumps(data), encoding="utf-8")
    await asyncio.to_thread(extensions_path.write_text, env.config.extensions.model_dump_json(by_alias=True), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()
    reset_extensions_config()
    config = await run_assembly(get_app_config)
    authority = await run_assembly(capture_agent_authority, config, user_id="alice", agent_config=env.agent)
    interceptor = build_agent_auth_interceptor(config.extensions)
    request = MCPToolCallRequest(name="search", args={}, server_name="tickets", runtime=Runtime(context={"user_id": "alice", AGENT_AUTH_CONTEXT_KEY: authority}))
    headers = []

    async def handler(request):
        headers.append(request.headers)

    try:
        await interceptor(request, handler)
        assert {key.lower(): value for key, value in headers[0].items()}["authorization"] == "Bearer research-client-token"
        reference = authority.references[0].model_dump(mode="json")
        assert await validate_task_agent_reference("alice", "tickets", reference) is not None
        data["mcp_agent_auth"]["research-tickets"]["owners"] = []
        await asyncio.to_thread(path.write_text, json.dumps(data), encoding="utf-8")
        with pytest.raises(ToolException):
            await interceptor(request, handler)
        with pytest.raises(ToolException):
            await validate_task_agent_reference("alice", "tickets", reference)
        assert len(headers) == 1
    finally:
        reset_extensions_config()
        reset_app_config()


@pytest.mark.asyncio
async def test_existing_standalone_tool_observes_enabled_protection_off_loop(agent_auth_env, tmp_path, monkeypatch):
    config = agent_auth_env.config.extensions.model_copy(deep=True)
    config.mcp_servers["tickets"].agent_auth = False
    path = tmp_path / "extensions.json"
    await asyncio.to_thread(path.write_text, config.model_dump_json(by_alias=True), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    reset_app_config()  # MCP-only embeddings need no config.yaml.
    reset_extensions_config()
    interceptor = build_agent_auth_interceptor(config)
    request = MCPToolCallRequest(name="search", args={}, server_name="tickets")
    calls = []

    async def handler(request):
        calls.append(request)

    try:
        await interceptor(request, handler)
        updated = config.model_copy(deep=True)
        updated.mcp_servers["tickets"].agent_auth = True
        await asyncio.to_thread(path.write_text, updated.model_dump_json(by_alias=True), encoding="utf-8")
        with pytest.raises(ToolException):
            await interceptor(request, handler)
        assert len(calls) == 1
    finally:
        reset_extensions_config()
        reset_app_config()
