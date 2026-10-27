from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers import user_security
from deerflow.security.store import UserSecurityStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = UserSecurityStore(tmp_path)
    monkeypatch.setattr(user_security, "get_user_security_store", lambda: store)
    monkeypatch.setattr(user_security, "user_security_enabled", lambda: True)
    monkeypatch.setattr(
        user_security,
        "_catalog",
        lambda: [{"resource": "tool", "target": "custom_tool"}, {"resource": "skill", "target": "public:future-skill", "label": "Future skill"}, {"resource": "mcp_server", "target": "crm", "credential_supported": True}],
    )
    monkeypatch.setattr(user_security, "_catalog_for_user", lambda user_id: user_security._catalog())
    app = FastAPI()
    app.include_router(user_security.router)
    users = {name: SimpleNamespace(id=name, email=name + "@example.org", system_role="admin" if name == "admin" else "user") for name in ["alice", "bob", "admin"]}

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = users[request.headers.get("x-test-user", "alice")]
        request.state.auth_source = request.headers.get("x-test-source", "session")
        return await call_next(request)

    async def current(request):
        return request.state.user

    from fastapi import Request

    current.__annotations__["request"] = Request
    app.dependency_overrides[get_current_user_from_request] = current
    monkeypatch.setattr(
        user_security,
        "get_local_provider",
        lambda: SimpleNamespace(get_user_by_email=AsyncMock(side_effect=lambda email: next((user for user in users.values() if user.email == email), None)), get_user=AsyncMock(side_effect=lambda user_id: users.get(user_id))),
    )
    with TestClient(app) as test_client:
        yield test_client, store


def test_nonadmin_cannot_grant_and_pat_cannot_manage_credentials(client):
    http, _ = client
    assert http.put("/api/user-security/grants", json={"email": "bob@example.org", "resource": "tool", "target": "custom_tool", "allowed": True}).status_code == 403
    assert http.put("/api/user-security/credentials/crm", json={"credential": "secret"}, headers={"x-test-source": "pat"}).status_code == 403


def test_personal_credential_api_does_not_accept_other_owner_or_return_secret(client):
    http, store = client
    store.set_grant("alice", "mcp_server", "crm", True, actor="admin")
    response = http.put("/api/user-security/credentials/crm", json={"credential": "Bearer alice-private", "user_id": "bob"})
    assert response.status_code == 422
    response = http.put("/api/user-security/credentials/crm", json={"credential": "Bearer alice-private"})
    assert response.status_code == 200
    assert "alice-private" not in response.text
    assert store.get_credential("bob", "crm") is None
    assert store.get_credential("alice", "crm") == "Bearer alice-private"
    me = http.get("/api/user-security/me").json()
    assert me["credentials"] == ["crm"]
    assert "alice-private" not in str(me)
    assert http.get("/api/user-security/me", headers={"x-test-user": "bob"}).json()["credentials"] == []


def test_admin_can_grant_and_revoke_exact_user_resource(client):
    http, store = client
    body = {"email": "bob@example.org", "resource": "tool", "target": "custom_tool", "allowed": True}
    assert http.put("/api/user-security/grants", json=body, headers={"x-test-user": "admin"}).status_code == 200
    assert ("tool", "custom_tool") in store.grants("bob")
    body["allowed"] = False
    assert http.put("/api/user-security/grants", json=body, headers={"x-test-user": "admin"}).status_code == 200
    assert not store.grants("bob")


@pytest.mark.parametrize("body", [{"credential": ["secret-never-echo"]}, {"credential": "valid", "extra": "secret-never-echo"}])
def test_invalid_credential_request_never_echoes_submitted_values(client, body):
    http, _ = client
    response = http.put("/api/user-security/credentials/crm", json=body)
    assert response.status_code == 422
    assert "secret-never-echo" not in response.text


def test_catalog_uses_bound_tool_names_including_conditional_tools(monkeypatch):
    from deerflow.mcp import cache
    from deerflow.tools import tools as tool_loader

    monkeypatch.setattr(user_security, "get_app_config", lambda: SimpleNamespace(models=[]))
    monkeypatch.setattr(user_security, "_skill_catalog", lambda config: [])
    monkeypatch.setattr(tool_loader, "get_available_tools", lambda **kwargs: [SimpleNamespace(name="actual_name"), SimpleNamespace(name="list_uploaded_files"), SimpleNamespace(name="view_image")])
    monkeypatch.setattr(user_security.ExtensionsConfig, "from_file", lambda: SimpleNamespace(mcp_servers={}))
    monkeypatch.setattr(cache, "get_cached_mcp_tools", lambda: [])
    targets = {item["target"] for item in user_security._catalog()}
    assert targets == {"actual_name"}


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/groups", None),
        ("POST", "/groups", {"name": "Team"}),
        ("GET", "/groups/some-id", None),
        ("PATCH", "/groups/some-id", {"name": "Other"}),
        ("DELETE", "/groups/some-id", None),
        ("POST", "/groups/some-id/members", {"email": "bob@example.org"}),
        ("DELETE", "/groups/some-id/members/bob", None),
        ("PUT", "/groups/some-id/grants", {"resource": "tool", "target": "custom_tool", "allowed": True}),
        ("PUT", "/overrides", {"email": "bob@example.org", "resource": "tool", "target": "custom_tool", "mode": "deny"}),
    ],
)
def test_group_management_is_admin_session_only(client, method, path, body):
    http, _ = client
    for headers in ({"x-test-user": "alice"}, {"x-test-user": "admin", "x-test-source": "pat"}):
        assert http.request(method, "/api/user-security" + path, json=body, headers=headers).status_code == 403


def test_group_api_effective_permissions_and_personal_modes(client):
    http, store = client
    headers = {"x-test-user": "admin"}
    created = http.post("/api/user-security/groups", json={"name": "运营"}, headers=headers)
    assert created.status_code == 200
    group = created.json()
    path = "/api/user-security/groups/" + group["id"]
    assert http.post(path + "/members", json={"email": "alice@example.org"}, headers=headers).status_code == 200
    assert http.post(path + "/members", json={"email": "missing@example.org"}, headers=headers).status_code == 404
    body = {"resource": "tool", "target": "custom_tool", "allowed": True}
    assert http.put(path + "/grants", json=body, headers=headers).status_code == 200
    assert http.get("/api/user-security/groups", headers=headers).json()["groups"][0]["member_count"] == 1
    assert http.get(path, headers=headers).json()["members"] == [{"id": "alice", "email": "alice@example.org"}]
    details = http.get("/api/user-security/grants?email=alice@example.org", headers=headers).json()
    assert details["direct_grants"] == [] and details["denied"] == []
    assert details["grants"] == [{"resource": "tool", "target": "custom_tool"}]
    assert details["groups"] == [{"id": group["id"], "name": "运营"}]
    assert http.get("/api/user-security/me").json()["resources"][0]["allowed"]
    assert not http.get("/api/user-security/me", headers={"x-test-user": "bob"}).json()["resources"][0]["allowed"]
    override = {"email": "alice@example.org", "resource": "tool", "target": "custom_tool", "mode": "deny"}
    assert http.put("/api/user-security/overrides", json=override, headers=headers).status_code == 200
    assert not store.grants("alice")
    assert http.get("/api/user-security/grants?email=alice@example.org", headers=headers).json()["denied"] == [{"resource": "tool", "target": "custom_tool"}]
    override["mode"] = "inherit"
    assert http.put("/api/user-security/overrides", json=override, headers=headers).status_code == 200
    assert store.grants("alice") == {("tool", "custom_tool")}
    assert http.patch(path, json={"name": "Operations"}, headers=headers).json()["id"] == group["id"]
    assert http.delete(path + "/members/alice", headers=headers).status_code == 200
    assert store.grants("alice") == set()
    assert http.delete(path, headers=headers).status_code == 200
    assert http.get(path, headers=headers).status_code == 404


def test_group_api_rejects_unknown_resources_duplicate_names_and_admin_exceptions(client):
    http, _ = client
    headers = {"x-test-user": "admin"}
    path = "/api/user-security/groups"
    group = http.post(path, json={"name": "Team"}, headers=headers).json()
    assert http.post(path, json={"name": " TEAM "}, headers=headers).status_code == 409
    assert http.post(path, json={"name": "  "}, headers=headers).status_code == 400
    for target in ("not-configured", "*"):
        body = {"resource": "tool", "target": target, "allowed": True}
        assert http.put(path + "/" + group["id"] + "/grants", json=body, headers=headers).status_code == 400
    body = {"email": "admin@example.org", "resource": "tool", "target": "custom_tool", "mode": "deny"}
    assert http.put("/api/user-security/overrides", json=body, headers=headers).status_code == 400


def test_skill_group_grants_and_default_override_rejection(client):
    http, store = client
    headers = {"x-test-user": "admin"}
    group = http.post("/api/user-security/groups", json={"name": "Skills"}, headers=headers).json()
    path = "/api/user-security/groups/" + group["id"]
    http.post(path + "/members", json={"email": "alice@example.org"}, headers=headers)
    body = {"resource": "skill", "target": "public:future-skill", "allowed": True}
    assert http.put(path + "/grants", json=body, headers=headers).status_code == 200
    assert ("skill", "public:future-skill") in store.grants("alice")
    for resource, target in [("tool", "bash"), ("sandbox", "*"), ("skill", "public:deep-research")]:
        override = {"email": "alice@example.org", "resource": resource, "target": target, "mode": "deny"}
        assert http.put("/api/user-security/overrides", json=override, headers=headers).status_code == 400
        override["mode"] = "inherit"
        assert http.put("/api/user-security/overrides", json=override, headers=headers).status_code == 200


def test_admin_can_authorize_only_target_users_private_skill(client, monkeypatch):
    http, store = client
    monkeypatch.setattr(user_security, "_catalog_for_user", lambda user_id: [{"resource": "skill", "target": f"custom:{user_id}:report", "label": "report"}])
    headers = {"x-test-user": "admin"}
    resource = http.get("/api/user-security/grants?email=alice@example.org", headers=headers).json()["resources"][0]
    assert resource["target"] == "custom:alice:report"
    body = {"email": "alice@example.org", "resource": "skill", "target": resource["target"], "mode": "allow"}
    assert http.put("/api/user-security/overrides", json=body, headers=headers).status_code == 200
    body["email"] = "bob@example.org"
    assert http.put("/api/user-security/overrides", json=body, headers=headers).status_code == 400


def test_skill_catalog_excludes_fixed_defaults_but_not_future_public_or_custom(monkeypatch):
    from pathlib import Path

    from deerflow.skills import storage
    from deerflow.skills.types import Skill, SkillCategory

    def item(name, category):
        return Skill(name, "description", None, Path(name), Path(name) / "SKILL.md", Path(name), category)

    items = [item("data-analysis", SkillCategory.PUBLIC), item("future-public", SkillCategory.PUBLIC), item("data-analysis", SkillCategory.CUSTOM)]
    monkeypatch.setattr(storage, "get_or_new_user_skill_storage", lambda *args, **kwargs: SimpleNamespace(load_skills=lambda **kwargs: items))
    resources = user_security._skill_catalog(SimpleNamespace(), user_id="alice")
    assert {row["target"] for row in resources} == {"public:future-public", "custom:alice:data-analysis"}


def test_catalog_omits_reserved_mcp_tool_names_but_keeps_server(monkeypatch):
    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp import cache
    from deerflow.tools import tools as tool_loader

    monkeypatch.setattr(user_security, "get_app_config", lambda: SimpleNamespace(models=[]))
    monkeypatch.setattr(user_security, "_skill_catalog", lambda config: [])
    monkeypatch.setattr(tool_loader, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(user_security.ExtensionsConfig, "from_file", lambda: SimpleNamespace(mcp_servers={"web": McpServerConfig(type="http", url="https://example.invalid/mcp")}))
    source = {"deerflow_mcp_source": {"server_name": "web", "transport": "http"}}
    monkeypatch.setattr(cache, "get_cached_mcp_tools", lambda: [SimpleNamespace(name="web_search", metadata=source), SimpleNamespace(name="web_lookup", metadata=source)])
    assert {(row["resource"], row["target"]) for row in user_security._catalog()} == {("mcp_server", "web"), ("tool", "web_lookup")}
