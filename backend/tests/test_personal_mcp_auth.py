import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp import personal_auth
from deerflow.security.store import UserSecurityStore


def test_personal_mcp_two_users_and_revocation(tmp_path, monkeypatch):
    store = UserSecurityStore(tmp_path)
    config = ExtensionsConfig(mcp_servers={"crm": McpServerConfig(type="http", url="https://example.invalid/mcp")})
    monkeypatch.setattr(personal_auth, "get_user_security_store", lambda: store)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    monkeypatch.setattr(personal_auth, "resolve_runtime_user_id", lambda runtime: runtime.user_id)
    interceptor = personal_auth.build_personal_auth_interceptor(config)
    store.set_grant("alice", "mcp_server", "crm", True, actor="admin")
    store.set_credential("alice", "crm", "Bearer alice-secret")

    def request(user):
        return SimpleNamespace(server_name="crm", name="lookup", headers={}, runtime=SimpleNamespace(user_id=user), override=lambda **kwargs: kwargs)

    handler = AsyncMock(return_value="ok")
    assert asyncio.run(interceptor(request("alice"), handler)) == "ok"
    assert handler.call_args.args[0]["headers"]["Authorization"] == "Bearer alice-secret"
    with pytest.raises(ToolException, match="authorized"):
        asyncio.run(interceptor(request("bob"), handler))
    store.set_grant("bob", "mcp_server", "crm", True, actor="admin")
    with pytest.raises(ToolException, match="credential"):
        asyncio.run(interceptor(request("bob"), handler))
    store.set_grant("alice", "mcp_server", "crm", False, actor="admin")
    with pytest.raises(ToolException, match="authorized"):
        asyncio.run(interceptor(request("alice"), handler))
    assert handler.call_count == 1


@pytest.mark.parametrize("kwargs", [{"type": "stdio", "command": "npx"}, {"type": "http", "url": "https://example.invalid", "headers": {"Cookie": "shared"}}])
def test_unsafe_personal_mcp_transport_or_shared_headers_denied(kwargs):
    with pytest.raises(ValueError):
        personal_auth.validate_personal_server(McpServerConfig(**kwargs))


@pytest.mark.parametrize("url", ["https://shared:password@example.invalid/mcp", "https://example.invalid/mcp?api_key=shared", "https://example.invalid/mcp#secret"])
def test_endpoint_cannot_supply_shared_credentials(url):
    with pytest.raises(ValueError, match="embedded credentials"):
        personal_auth.validate_personal_server(McpServerConfig(type="http", url=url))


def test_server_disabled_on_disk_is_denied_by_already_built_interceptor(tmp_path, monkeypatch):
    path = tmp_path / "extensions.json"
    raw = {"mcpServers": {"crm": {"type": "http", "url": "https://example.invalid/mcp", "enabled": True}}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    interceptor = personal_auth.build_personal_auth_interceptor(ExtensionsConfig.from_file())
    raw["mcpServers"]["crm"]["enabled"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    handler = AsyncMock()
    with pytest.raises(ToolException, match="unavailable"):
        asyncio.run(interceptor(SimpleNamespace(server_name="crm"), handler))
    handler.assert_not_called()


def test_admin_owner_context_uses_own_credential_without_explicit_grant(tmp_path, monkeypatch):
    store = UserSecurityStore(tmp_path)
    store.set_credential("owner", "crm", "Bearer owner-private")
    config = ExtensionsConfig(mcp_servers={"crm": McpServerConfig(type="http", url="https://example.invalid/mcp")})
    monkeypatch.setattr(personal_auth, "get_user_security_store", lambda: store)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    runtime = SimpleNamespace(context={"user_id": "owner", "user_role": "admin"})
    request = SimpleNamespace(server_name="crm", name="lookup", runtime=runtime, headers={}, override=lambda **kwargs: kwargs)
    handler = AsyncMock(return_value="ok")
    assert asyncio.run(personal_auth.build_personal_auth_interceptor(config)(request, handler)) == "ok"
    assert handler.call_args.args[0]["headers"]["Authorization"] == "Bearer owner-private"


def test_group_mcp_access_uses_own_secret_and_rechecks_membership_and_deny(tmp_path, monkeypatch):
    store = UserSecurityStore(tmp_path)
    config = ExtensionsConfig(mcp_servers={"crm": McpServerConfig(type="http", url="https://example.invalid/mcp")})
    monkeypatch.setattr(personal_auth, "get_user_security_store", lambda: store)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    monkeypatch.setattr(personal_auth, "resolve_runtime_user_id", lambda runtime: runtime.user_id)
    group = store.create_group("Sales", actor="admin")
    for user in ("alice", "bob"):
        store.set_member(group["id"], user, True, actor="admin")
    store.set_group_grant(group["id"], "mcp_server", "crm", True, actor="admin")
    store.set_credential("alice", "crm", "Bearer alice-private")
    wrapper = personal_auth.build_personal_auth_interceptor(config)
    handler = AsyncMock(return_value="ok")

    def call(user):
        request = SimpleNamespace(server_name="crm", name="lookup", headers={}, runtime=SimpleNamespace(user_id=user), override=lambda **kw: kw)
        return asyncio.run(wrapper(request, handler))

    assert call("alice") == "ok"
    with pytest.raises(ToolException, match="credential"):
        call("bob")
    store.set_override("alice", "mcp_server", "crm", "deny", actor="admin")
    with pytest.raises(ToolException, match="authorized"):
        call("alice")
    store.set_override("alice", "mcp_server", "crm", "inherit", actor="admin")
    assert call("alice") == "ok"
    store.set_member(group["id"], "alice", False, actor="admin")
    with pytest.raises(ToolException, match="authorized"):
        call("alice")
    assert handler.call_count == 2
    assert store.get_credential("alice", "crm") == "Bearer alice-private"


@pytest.mark.parametrize("server,raw_name,prefix,reserved", [("crm", "view_image", False, True), ("web", "search", True, True), ("crm", "view_image", True, False)])
def test_personal_interceptor_rejects_reserved_bound_names_even_for_existing_wrappers(tmp_path, monkeypatch, server, raw_name, prefix, reserved):
    store = UserSecurityStore(tmp_path)
    config = ExtensionsConfig(mcp_servers={server: McpServerConfig(type="http", url="https://example.invalid/mcp", tool_name_prefix=prefix)})
    monkeypatch.setattr(personal_auth, "get_user_security_store", lambda: store)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    store.set_credential("owner", server, "Bearer owner-private")
    request = SimpleNamespace(server_name=server, name=raw_name, runtime=SimpleNamespace(context={"user_id": "owner", "user_role": "admin"}), headers={}, override=lambda **kw: kw)
    wrapper = personal_auth.build_personal_auth_interceptor(config)
    handler = AsyncMock(return_value="ok")
    if reserved:
        with pytest.raises(ToolException, match="reserved"):
            asyncio.run(wrapper(request, handler))
        handler.assert_not_called()
    else:
        assert asyncio.run(wrapper(request, handler)) == "ok"
        handler.assert_awaited_once()
