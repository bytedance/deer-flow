"""Administrator-only, read-only projections of the live extension diagnostics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers.plugins import router
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.extensions import initialize_runtime_diagnostics, record_runtime_diagnostics
from deerflow.extensions.loader import Diagnostic, ExtensionSpec, load_extensions

URL = "/api/plugins/diagnostics"
SECRET = "fixture-private-key"


@pytest.fixture
def diagnostics_client(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    monkeypatch.setattr("deerflow.extensions._runtime_diagnostics", [])
    users = {role: SimpleNamespace(id=role, system_role=role, needs_setup=False, token_version=0) for role in ("admin", "user")}

    async def resolve_session(request):
        user = users.get(request.cookies.get("access_token"))
        if user is None:
            raise HTTPException(401, "Not authenticated")
        return user

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", resolve_session)
    app = FastAPI()
    app.state.extension_diagnostics = initialize_runtime_diagnostics([])
    app.include_router(router)
    app.add_middleware(AuthMiddleware)
    with TestClient(app) as client:
        yield client, users


def admin(client):
    client.cookies.set("access_token", "admin")


def test_admin_reads_live_diagnostics_without_exposing_or_changing_details(diagnostics_client):
    client, _ = diagnostics_client
    admin(client)
    diagnostics = client.app.state.extension_diagnostics
    first = Diagnostic.error("example:install", f"install() failed: api_key={SECRET}; /private/config.yaml")
    record_runtime_diagnostics([first])
    response = client.get(URL)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == [{"source": "example:install", "level": "error", "summary": "Extension registration failed. See Gateway logs for details."}]
    assert SECRET not in response.text and "/private/config.yaml" not in response.text
    assert diagnostics == [first]
    record_runtime_diagnostics([Diagnostic.warning("other.plugin:install", f"service start() failed; continuing without it: {SECRET}")])
    updated = client.get(URL)
    assert updated.status_code == 200 and len(updated.json()) == 2
    assert updated.json()[1]["summary"] == "Extension service could not start. See Gateway logs for details."
    assert SECRET not in updated.text
    assert client.app.state.extension_diagnostics is diagnostics
    assert diagnostics[0] is first and SECRET in diagnostics[0].message


def test_empty_diagnostics_are_an_empty_array(diagnostics_client):
    client, _ = diagnostics_client
    admin(client)
    assert client.get(URL).json() == []


def test_failed_extension_is_visible_even_without_a_registered_plugin(diagnostics_client):
    client, _ = diagnostics_client
    admin(client)
    loaded, diagnostics = load_extensions([ExtensionSpec(use="nonexistent_diagnostics_fixture:install")])
    assert not loaded.plugins
    record_runtime_diagnostics(diagnostics)
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == [{"source": "nonexistent_diagnostics_fixture:install", "level": "error", "summary": "Extension loading failed. See Gateway logs for details."}]


@pytest.mark.parametrize("role", [None, "user", "internal"])
def test_non_admin_cannot_read_even_the_diagnostics_list(diagnostics_client, monkeypatch, role):
    client, _ = diagnostics_client

    def unreadable():
        pytest.fail("Diagnostics were read before administrator authorization")

    monkeypatch.setattr("app.gateway.routers.plugins.get_runtime_diagnostics", unreadable, raising=False)
    headers = {}
    if role == "internal":
        headers = create_internal_auth_headers()
    elif role:
        client.cookies.set("access_token", role)
    response = client.get(URL, headers=headers)
    assert response.status_code == (401 if role is None else 403)


@pytest.mark.parametrize("allow_route", [False, True])
def test_admin_pat_has_no_diagnostic_access(diagnostics_client, monkeypatch, allow_route):
    client, users = diagnostics_client
    monkeypatch.setattr("app.gateway.auth.pat.authenticate_pat", AsyncMock(return_value=(users["admin"], ["threads:read"])))
    if allow_route:
        # Pin the route's own admin guard even if an alternative host admits PATs.
        monkeypatch.setattr("app.gateway.auth.pat.is_pat_allowed_route", lambda method, path: True)
    response = client.get(URL, headers={"Authorization": "Bearer fixture-token"})
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_diagnostics_have_no_write_operation(diagnostics_client, method):
    client, _ = diagnostics_client
    admin(client)
    diagnostic = Diagnostic.error("example:install", SECRET)
    record_runtime_diagnostics([diagnostic])
    assert client.request(method, URL, json={"clear": True}).status_code == 405
    assert client.app.state.extension_diagnostics == [diagnostic]


@pytest.mark.parametrize(
    "source",
    [f"/private/{SECRET}.py", f"https://user:{SECRET}@example.com/plugin", f"example:install\n{SECRET}", f"{SECRET}" * 100, ""],
    ids=["path", "credentials", "newline", "oversized", "empty"],
)
def test_invalid_or_oversized_sources_are_redacted(diagnostics_client, source):
    client, _ = diagnostics_client
    admin(client)
    record_runtime_diagnostics([Diagnostic.error(source, f"arbitrary failure: {SECRET}")])
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == [{"source": "[redacted]", "level": "error", "summary": "Extension reported a diagnostic. See Gateway logs for details."}]
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("message", "summary"),
    [
        ("extension requires extension-api private-version", "Extension loading failed."),
        ("install() failed: credential", "Extension registration failed."),
        ("router path /private is already served", "Extension router could not be mounted."),
        ("service start() raised CancelledError; continuing without it", "Extension service could not start."),
        ("service stop() timed out after 5s; continuing shutdown", "Extension service could not stop."),
        ("PrivateMiddleware.before_model failed and was skipped", "Extension reported a diagnostic."),
    ],
)
def test_only_fixed_summaries_are_returned(diagnostics_client, message, summary):
    client, _ = diagnostics_client
    admin(client)
    record_runtime_diagnostics([Diagnostic.warning("example:install", f"{message}: {SECRET}")])
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()[0] == {"source": "example:install", "level": "warning", "summary": f"{summary} See Gateway logs for details."}
    assert SECRET not in response.text


def test_existing_retention_bound_is_preserved_without_draining_the_list(diagnostics_client):
    client, _ = diagnostics_client
    admin(client)
    records = [Diagnostic.error(f"example_{index}:install", SECRET) for index in range(1005)]
    record_runtime_diagnostics(records)
    response = client.get(URL)
    assert response.status_code == 200
    assert len(response.json()) == 1000
    assert response.json()[0]["source"] == "example_5:install"
    assert response.json()[-1]["source"] == "example_1004:install"
    assert client.app.state.extension_diagnostics == records[-1000:]
    assert client.get(URL).json() == response.json()
    assert SECRET not in response.text


def test_unknown_level_is_not_returned_as_free_form_text(diagnostics_client):
    client, _ = diagnostics_client
    admin(client)
    record_runtime_diagnostics([Diagnostic(SECRET, "example:install", SECRET)])
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()[0]["level"] == "unknown"
    assert SECRET not in response.text


def test_auth_disabled_mode_keeps_the_existing_synthetic_admin_policy(diagnostics_client, monkeypatch):
    client, _ = diagnostics_client
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_ENV", "test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == []
