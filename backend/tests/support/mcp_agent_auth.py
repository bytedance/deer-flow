"""Offline OAuth/MCP endpoints and isolated operator policy for auth tests."""

import json
from collections import OrderedDict
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config


class AgentAuthModel(BaseChatModel):
    """A configured model boundary for the real Gateway subprocess test."""

    @property
    def _llm_type(self):
        return "offline-agent-auth"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        answer = AIMessage(content="done")
        if not any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content="", tool_calls=[{"name": "tickets_submit_job", "args": {}, "id": "submit-1", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.fixture
def agent_auth_env(tmp_path, monkeypatch):
    from deerflow.mcp import agent_auth
    from deerflow.mcp.agent_auth import agent_definition_digest

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr(agent_auth, "_token_managers", OrderedDict())
    agent = AgentConfig(name="research-bot", tool_groups=["mcp"], skills=[])
    soul = "Research only."
    directory = tmp_path / "users" / "alice" / "agents" / agent.name
    directory.mkdir(parents=True)
    (directory / "config.yaml").write_text(json.dumps(agent.model_dump(mode="json")), encoding="utf-8")
    (directory / "SOUL.md").write_text(soul, encoding="utf-8")
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "extensions": {
                "mcpServers": {
                    "tickets": {
                        "type": "http",
                        "url": "https://mcp.example",
                        "agent_auth": True,
                        "headers": {"authorization": "Bearer discovery-secret"},
                    }
                }
            },
            "mcp_agent_auth": {
                "research-tickets": {
                    "server": "tickets",
                    "agent": agent.name,
                    "owners": ["alice"],
                    "definition_digests": [agent_definition_digest(agent, soul)],
                    "oauth": {
                        "grant_type": "client_credentials",
                        "token_url": "https://idp.example/token",
                        "client_id": "research-client",
                        "client_secret": "private-client-secret",
                    },
                }
            },
        }
    )
    set_app_config(config)
    yield SimpleNamespace(agent=agent, soul=soul, directory=directory, config=config)
    reset_app_config()


@pytest.fixture
def agent_mcp_transport(monkeypatch):
    from urllib.parse import parse_qs

    calls, token_clients, token_forms, discoveries = [], [], [], []

    def respond(request):
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            token_forms.append(form)
            client = form["client_id"][0]
            token_clients.append(client)
            return httpx.Response(200, json={"access_token": client + "-token", "expires_in": 3600})
        if request.method != "POST":
            return httpx.Response(405)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        method = message["method"]
        if method == "initialize":
            result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "tickets", "version": "1"}}
        elif method == "tools/list":
            discoveries.append(request.headers.get("authorization"))
            result = {"tools": [{"name": name, "description": name, "inputSchema": {"type": "object", "properties": {}}} for name in ("submit_job", "poll_job", "cancel_job", "search")]}
        elif method == "tools/call":
            assert len(request.headers.get_list("authorization")) == 1
            name, authorization = message["params"]["name"], request.headers["authorization"]
            calls.append((name, authorization))
            assert authorization.startswith("Bearer research-client") or authorization == "Bearer discovery-secret"
            result = {"isError": False, "content": [{"type": "text", "text": "ok"}], "structuredContent": {"task_id": "remote-1", "status": "cancelled" if name == "cancel_job" else "running"}}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    original = httpx.AsyncClient

    class OfflineClient(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(respond))
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", OfflineClient)
    return SimpleNamespace(calls=calls, token_clients=token_clients, token_forms=token_forms, discoveries=discoveries)
