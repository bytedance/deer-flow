"""Provider contracts: actual HTTP serialization, business errors and MCP tools."""

import json

import httpx
import pytest

from deerflow.capabilities.business import BusinessClient, build_server, connection_config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,credentials,host",
    [
        ("dingtalk", {"access_token": "robot-token", "sign_secret": "SEC-sign"}, "oapi.dingtalk.com"),
        ("wecom", {"webhook_key": "robot-key"}, "qyapi.weixin.qq.com"),
    ],
)
async def test_robot_wire_contract(provider, credentials, host):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BusinessClient(provider, credentials, http)
        assert await client.send_message("通知", "markdown", "日报") == {"sent": True}
    request = requests[0]
    assert request.url.host == host
    body = json.loads(request.content)
    assert body["msgtype"] == "markdown"
    if provider == "dingtalk":
        assert request.url.params["access_token"] == "robot-token"
        assert request.url.params["timestamp"] and request.url.params["sign"]
        assert body["markdown"] == {"text": "通知", "title": "日报"}
    else:
        assert request.url.params["key"] == "robot-key"
        assert body["markdown"] == {"content": "通知"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(200, {"errcode": 40014, "errmsg": "secret-token"}), (401, {"message": "secret-token"}), (302, {})])
async def test_errors_never_claim_success_or_expose_response_secrets(status, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))) as http:
        client = BusinessClient("wecom", {"webhook_key": "secret-token"}, http)
        with pytest.raises(ValueError) as error:
            await client.send_message("hello")
        assert "secret-token" not in str(error.value)


@pytest.mark.asyncio
async def test_hubspot_pagination_and_contact_creation():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"results": [{"id": "12"}], "paging": {"next": {"after": "next-page"}}})
        return httpx.Response(201, json={"id": "42", "properties": {"email": "person@example.test"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BusinessClient("hubspot", {"access_token": "private-token"}, http)
        assert (await client.get_companies(2, "cursor"))["next_after"] == "next-page"
        assert (await client.create_contact("person@example.test", firstname="A"))["id"] == "42"
    assert requests[0].url.params["after"] == "cursor"
    assert requests[0].url.params["limit"] == "2"
    assert requests[0].headers["Authorization"] == "Bearer private-token"
    assert requests[1].url.path == "/crm/v3/objects/contacts"
    assert json.loads(requests[1].content) == {"properties": {"email": "person@example.test", "firstname": "A"}}


@pytest.mark.asyncio
async def test_mcp_discovery_does_not_need_or_expose_credentials():
    server = build_server("hubspot")
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"get_companies", "create_contact"}
    for tool in tools:
        assert "access_token" not in json.dumps(tool.inputSchema)
        assert tool.annotations.readOnlyHint == (tool.name == "get_companies")


@pytest.mark.parametrize("provider,values", [("wecom", {}), ("dingtalk", {"access_token": "x"}), ("hubspot", {"access_token": "x", "url": "http://localhost"}), ("hubspot", {"access_token": "***"})])
def test_invalid_configuration_rejected(provider, values):
    with pytest.raises(ValueError):
        connection_config(provider, values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,credentials,tool,arguments",
    [
        ("dingtalk", {"access_token": "fixture-token", "sign_secret": "fixture-secret"}, "send_message", {"content": ""}),
        ("wecom", {"webhook_key": "fixture-key"}, "send_message", {"content": ""}),
        ("hubspot", {"access_token": "fixture-token"}, "create_contact", {"email": "invalid"}),
    ],
)
async def test_exact_installed_launcher_discovers_and_rejects_invalid_calls(provider, credentials, tool, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config = connection_config(provider, credentials)
    params = StdioServerParameters(command=config["command"], args=config["args"], env=config["env"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        discovered = await session.list_tools()
        assert tool in {item.name for item in discovered.tools}
        result = await session.call_tool(tool, arguments)
        assert result.isError
        for secret in credentials.values():
            assert secret not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,credentials,tool,arguments,expected",
    [
        ("dingtalk", {"access_token": "fixture-token", "sign_secret": "fixture-secret"}, "send_message", {"content": "Report ready"}, "sent"),
        ("wecom", {"webhook_key": "fixture-key"}, "send_message", {"content": "Report ready"}, "sent"),
        ("hubspot", {"access_token": "fixture-token"}, "get_companies", {"limit": 1}, "Acme"),
        ("hubspot", {"access_token": "fixture-token"}, "create_contact", {"email": "person@example.test"}, "contact-42"),
    ],
)
async def test_real_mcp_tool_invocation_with_simulated_provider(tmp_path, provider, credentials, tool, arguments, expected):
    """Real stdio protocol and client code; only external HTTP is simulated."""
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = tmp_path / "business_fixture.py"
    script.write_text(
        """import httpx
from deerflow.capabilities.business import build_server
import sys
original = httpx.AsyncClient
def handle(request):
    if request.url.host == "api.hubapi.com":
        if request.method == "GET":
            return httpx.Response(200, json={"results": [{"id": "1", "properties": {"name": "Acme"}}]})
        return httpx.Response(201, json={"id": "contact-42", "properties": {"email": "person@example.test"}})
    return httpx.Response(200, json={"errcode": 0})
httpx.AsyncClient = lambda: original(transport=httpx.MockTransport(handle))
build_server(sys.argv[1]).run()
""",
        encoding="utf-8",
    )
    params = StdioServerParameters(command=sys.executable, args=["-I", str(script), provider], env=connection_config(provider, credentials)["env"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(tool, arguments)
        assert not result.isError, result
        assert expected in result.model_dump_json()


@pytest.mark.asyncio
async def test_robot_missing_business_status_is_failure_and_network_exception_is_redacted():
    async def missing(_):
        return httpx.Response(200, json={"ok": True})

    def broken(request):
        raise httpx.ConnectError("https://example.test?key=super-secret", request=request)

    for handler in (missing, broken):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ValueError) as error:
                await BusinessClient("wecom", {"webhook_key": "super-secret"}, http).send_message("hello")
            assert "super-secret" not in str(error.value)
