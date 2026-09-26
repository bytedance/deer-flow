"""Local self-registration gate (``auth.local.allow_registration``).

The OIDC provisioning policy (``allowed_email_domains``, ``require_verified_email``,
``auto_create_users``) is enforced only in the SSO callback via
``get_or_provision_oidc_user``. ``POST /api/v1/auth/register`` creates a local account
without consulting any of it, so an SSO-provisioned deployment that declares a domain
allowlist can still be joined by any address through the local path. These tests pin the
gate that lets such a deployment close it.
"""

import secrets

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.config import AuthConfig, set_auth_config
from deerflow.config.auth_config import AuthAppConfig, LocalAuthConfig

_TEST_SECRET = "test-secret-key-for-registration-gate-tests-only"


@pytest.fixture(autouse=True)
def _persistence_engine(tmp_path):
    """Per-test SQLite engine + clean ``deps._cached_*`` (mirrors test_auth_type_system).

    These tests drive the real ``/register`` handler, which reaches
    ``SQLiteUserRepository`` → ``get_session_factory``. A fresh DB per test also means
    the admin slot is empty for the /initialize case.
    """
    import asyncio

    from app.gateway import deps
    from deerflow.persistence.engine import close_engine, init_engine

    asyncio.run(init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/registration_gate.db", sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        asyncio.run(close_engine())


@pytest.fixture
def client(monkeypatch):
    """TestClient whose gate reads a config we control.

    Overrides only ``auth.local`` on a deep copy of the real config: the app lifespan
    reads other sections (``database`` above all) to initialise the engine, and a
    narrower stub would abort startup and leak an uninitialised engine into the
    globals ``app.gateway.deps`` caches for the rest of the session.
    """
    from pathlib import Path

    from deerflow.config.app_config import AppConfig

    # config.yaml is gitignored, so tests cannot rely on it existing. The committed
    # example is a valid config and gives every other section (database above all)
    # a real value for the app lifespan.
    baseline = AppConfig.from_file(str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

    def _make(*, allow_registration: bool) -> TestClient:
        set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
        patched = baseline.model_copy(deep=True)
        patched.auth = AuthAppConfig(local=LocalAuthConfig(allow_registration=allow_registration), oidc=baseline.auth.oidc)
        monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: patched)
        # setup-status memoizes per client IP; drop it so each direction is read fresh.
        from app.gateway.routers import auth as auth_router

        auth_router._SETUP_STATUS_CACHE.clear()

        from app.gateway.app import create_app

        return TestClient(create_app())

    return _make


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}@test.com"


def test_register_succeeds_when_registration_allowed(client):
    """Default (allow_registration=True) keeps self-registration working."""
    resp = client(allow_registration=True).post(
        "/api/v1/auth/register",
        json={"email": _unique_email("gate-allowed"), "password": "Tr0ub4dor3a!"},
    )
    assert resp.status_code == 201


def test_register_rejected_when_registration_disabled(client):
    """allow_registration=False closes the local self-registration path."""
    resp = client(allow_registration=False).post(
        "/api/v1/auth/register",
        json={"email": _unique_email("gate-denied"), "password": "Tr0ub4dor3a!"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "registration_disabled"


def test_register_rejected_before_the_account_is_created(client):
    """The gate runs ahead of user creation — a denied email stays unregistered.

    Guards against a gate placed after ``create_user``, which would 403 the caller
    while still persisting the account.
    """
    email = _unique_email("gate-not-persisted")
    denied = client(allow_registration=False)
    assert denied.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a!"}).status_code == 403

    # Re-open registration: the same address must still be free, i.e. the denied
    # attempt created nothing. A leaked account would surface as 400 email_already_exists.
    resp = client(allow_registration=True).post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Tr0ub4dor3a!"},
    )
    assert resp.status_code == 201


def test_registration_defaults_to_allowed():
    """The default must stay True — this change is meant to add an opt-in, not flip behaviour.

    Flipping the default would silently close self-registration on every existing
    deployment that never sets the key.
    """
    assert LocalAuthConfig().allow_registration is True
    assert AuthAppConfig().local.allow_registration is True


def test_gate_falls_back_to_open_when_config_is_absent(monkeypatch):
    """No config.yaml → the pre-gate default (open), not a 500.

    Bare-app contexts never load a config file. Before this gate, /register and
    /setup-status did not read the app config at all; the fallback keeps that true.
    """
    from app.gateway.routers import auth as auth_router

    def _raise() -> None:
        raise FileNotFoundError("`config.yaml` file not found in the project root")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", _raise)
    assert auth_router._local_registration_enabled() is True


@pytest.mark.parametrize("allowed", [True, False])
def test_setup_status_reports_registration_state(client, allowed):
    """The login page needs the flag to decide whether to offer a signup entry."""
    resp = client(allow_registration=allowed).get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["registration_enabled"] is allowed


def test_initialize_is_not_gated_by_the_registration_flag(client):
    """Closing self-registration must never block first-boot admin creation.

    ``config.example.yaml`` promises that turning the flag off cannot lock an operator
    out of a fresh install; the per-test engine gives us a genuinely empty admin slot.
    """
    resp = client(allow_registration=False).post(
        "/api/v1/auth/initialize",
        json={"email": _unique_email("gate-initialize"), "password": "Tr0ub4dor3a!"},
    )
    assert resp.status_code == 201
