"""Contributed routers need the caller's identity without importing app.*.

Every extension route is session-authenticated (contributed routers cannot
enter host-reserved or auth-exempt prefixes), but "logged in" and "admin" are
different questions and an extension must be able to ask the second one.
"""

from types import SimpleNamespace

import pytest
from deerflow_extension_api import (
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
    require_admin,
    resolve_principal,
)

ADMIN = ExtensionPrincipal(user_id="u1", is_admin=True, is_internal=False)
PLAIN = ExtensionPrincipal(user_id="u2", is_admin=False, is_internal=False)


def _request(principal):
    state = SimpleNamespace(**{EXTENSION_PRINCIPAL_RESOLVER_KEY: (lambda request: principal)})
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_resolve_returns_the_hosts_principal():
    assert resolve_principal(_request(ADMIN)) == ADMIN


def test_resolve_returns_none_when_the_host_installed_no_resolver():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert resolve_principal(request) is None


def test_resolve_returns_none_rather_than_raising_when_the_resolver_fails():
    def boom(request):
        raise RuntimeError("nope")

    state = SimpleNamespace(**{EXTENSION_PRINCIPAL_RESOLVER_KEY: boom})
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    assert resolve_principal(request) is None


def test_require_admin_accepts_an_admin():
    assert require_admin(_request(ADMIN)) == ADMIN


def test_require_admin_rejects_a_plain_user():
    with pytest.raises(PermissionError):
        require_admin(_request(PLAIN))


def test_require_admin_fails_closed_with_no_resolver():
    """An unanswerable authorization question must not resolve to 'allowed'."""
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(PermissionError):
        require_admin(request)


@pytest.fixture
def _stub_app_config(monkeypatch):
    """Keep ``create_app()`` independent of a real ``config.yaml``.

    The repo-root ``config.yaml`` is gitignored; a checkout that configures
    plugins there would otherwise make this test load them for real and leak
    a populated extension registry into the process-global singleton other
    tests read through (see ``tests/test_extension_app_loading.py`` for the
    same pattern).
    """
    import app.gateway.app as app_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.extensions import reset_loaded_extensions, reset_runtime_diagnostics

    config = AppConfig(sandbox=SandboxConfig(use="test"))
    monkeypatch.setattr(app_module, "get_app_config", lambda: config)
    reset_loaded_extensions()
    reset_runtime_diagnostics()
    yield
    reset_runtime_diagnostics()
    reset_loaded_extensions()


def test_host_installs_a_resolver_on_app_state(_stub_app_config):
    from app.gateway.app import create_app

    app = create_app()
    assert callable(getattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, None))


def test_the_installed_resolver_projects_system_role_into_roles(_stub_app_config):
    """The host's only role concept is the single system_role column; the
    projection must actually populate ``roles`` from it rather than reading a
    "roles" attribute the user model never had (which would always resolve to
    an empty tuple, silently breaking the documented contract)."""
    from app.gateway.app import create_app

    app = create_app()
    resolver = getattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY)

    admin_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="u1", system_role="admin"), auth_source=None))
    assert resolver(admin_request).roles == ("admin",)

    plain_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="u2", system_role="user"), auth_source=None))
    assert resolver(plain_request).roles == ("user",)

    no_role_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="u3", system_role=None), auth_source=None))
    assert resolver(no_role_request).roles == ()
