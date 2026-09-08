"""Phase 3 sandbox-level authorization tests.

Covers the ``authorize("sandbox", "execute")`` gate at the sandbox-use entry
point. When denied, a :class:`SandboxAuthorizationError` propagates up
through the tool so the agent's tool-error handling returns a friendly message
(RFC §9), rather than crashing the run.

The gate lives in :func:`authorize_sandbox_execution` (``authz/sandbox_authz.py``)
and is called from:
- ``ensure_sandbox_initialized`` / ``ensure_sandbox_initialized_async`` (lazy path)
- ``SandboxMiddleware.before_agent`` / ``abefore_agent`` (eager path)
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.sandbox_authz import authorize_sandbox_execution
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.exceptions import SandboxAuthorizationError

# ── Helpers ────────────────────────────────────────────────────────────


def _make_app_config() -> AppConfig:
    """Build a minimal AppConfig for authorization tests."""
    return AppConfig(
        models=[ModelConfig(name="gpt-4", model="gpt-4", use="langchain_openai:ChatOpenAI")],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(),
    )


def _context(**overrides):
    values = {
        "user_id": "user-123",
        "user_role": "user",
        "oauth_provider": "github",
        "oauth_id": "oauth-456",
        "is_internal": False,
    }
    values.update(overrides)
    return values


def _enable_authz(app_config: AppConfig, *, fail_closed: bool = True, default_role: str = "user") -> None:
    app_config.authorization = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role=default_role,
    )


# ── authorize_sandbox_execution unit tests ─────────────────────────────


def test_authorize_sandbox_disabled_is_noop():
    """When authorization is disabled, no check is performed (allow)."""
    app_config = _make_app_config()
    # AuthorizationConfig() defaults to enabled=False.
    authorize_sandbox_execution(context=_context(), app_config=app_config)  # must not raise


def test_authorize_sandbox_rbac_allow(monkeypatch):
    """Role with sandbox allow → permitted."""
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    authorize_sandbox_execution(context=_context(), app_config=app_config)  # must not raise


def test_authorize_sandbox_rbac_deny(monkeypatch):
    """Role with sandbox allow: [] → SandboxAuthorizationError."""
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    with pytest.raises(SandboxAuthorizationError, match="not permitted for your role"):
        authorize_sandbox_execution(context=_context(), app_config=app_config)


def test_authorize_sandbox_rbac_deny_via_bool(monkeypatch):
    """Role with sandbox allow: false → denied."""
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": False}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    with pytest.raises(SandboxAuthorizationError):
        authorize_sandbox_execution(context=_context(), app_config=app_config)


def test_authorize_sandbox_no_policy_is_unrestricted(monkeypatch):
    """Role with no sandbox policy → unrestricted (allow)."""
    provider = RbacAuthorizationProvider(roles={"user": {"tools": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    authorize_sandbox_execution(context=_context(), app_config=app_config)  # must not raise


def test_authorize_sandbox_provider_error_fail_closed(monkeypatch):
    """Provider error + fail_closed → SandboxAuthorizationError."""

    class _ErrorProvider:
        name = "error"

        def authorize(self, request):
            raise RuntimeError("boom")

        async def aauthorize(self, request):
            raise RuntimeError("boom")

        def filter_resources(self, principal, resource_type, candidates):
            raise RuntimeError("boom")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=True)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: _ErrorProvider(),
    )
    with pytest.raises(SandboxAuthorizationError):
        authorize_sandbox_execution(context=_context(), app_config=app_config)


def test_authorize_sandbox_provider_error_fail_open(monkeypatch):
    """Provider error + fail_open → allow (no raise)."""

    class _ErrorProvider:
        name = "error"

        def authorize(self, request):
            raise RuntimeError("boom")

        async def aauthorize(self, request):
            raise RuntimeError("boom")

        def filter_resources(self, principal, resource_type, candidates):
            raise RuntimeError("boom")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=False)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: _ErrorProvider(),
    )
    authorize_sandbox_execution(context=_context(), app_config=app_config)  # must not raise


def test_authorize_sandbox_internal_caller_uses_default_role(monkeypatch):
    """Internal callers (system_role=None) fall under default_role."""
    provider = RbacAuthorizationProvider(
        roles={
            "user": {"sandbox": {"allow": []}},
            "admin": {"sandbox": {"allow": "*"}},
        }
    )
    app_config = _make_app_config()
    _enable_authz(app_config, default_role="admin")
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    # Internal caller with system_role=None → default_role="admin" → allowed.
    authorize_sandbox_execution(
        context=_context(user_role=None, is_internal=True),
        app_config=app_config,
    )


def test_authorize_sandbox_denied_error_carries_role(monkeypatch):
    """The SandboxAuthorizationError carries the denied role for diagnostics."""
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    with pytest.raises(SandboxAuthorizationError) as exc_info:
        authorize_sandbox_execution(context=_context(), app_config=app_config)
    assert exc_info.value.role == "user"


# ── Integration: ensure_sandbox_initialized denies on authz reject ──────


def test_ensure_sandbox_initialized_denies_on_authz_reject(monkeypatch):
    """ensure_sandbox_initialized raises SandboxAuthorizationError on deny.

    Real-path test: the genuine gate runs inside ensure_sandbox_initialized
    before provider.acquire is touched, so a denied role never acquires a
    sandbox (and the error propagates as a friendly ToolMessage upstream).
    """
    from deerflow.sandbox import tools as sandbox_tools

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    runtime = SimpleNamespace(
        state={"sandbox": None},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )
    # A mock provider whose acquire must never be called.
    sandbox_provider = MagicMock()
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)

    with pytest.raises(SandboxAuthorizationError):
        sandbox_tools.ensure_sandbox_initialized(runtime)
    sandbox_provider.acquire.assert_not_called()


def test_ensure_sandbox_initialized_rechecks_authz_for_reused_sandbox(monkeypatch):
    """A persisted sandbox id must not outlive a revoked execute grant."""
    from deerflow.sandbox import tools as sandbox_tools

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    sandbox_provider = MagicMock()
    sandbox_provider.get.return_value = MagicMock()
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "sbx-existing"}},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )

    with pytest.raises(SandboxAuthorizationError):
        sandbox_tools.ensure_sandbox_initialized(runtime)
    sandbox_provider.get.assert_not_called()
    sandbox_provider.acquire.assert_not_called()


def test_ensure_sandbox_initialized_allows_on_authz_permit(monkeypatch):
    """ensure_sandbox_initialized proceeds to acquire on allow."""
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.sandbox.sandbox_provider import (
        reset_sandbox_provider,
        set_sandbox_provider,
    )

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    acquired = {"called": False}

    class _StubProvider:
        def acquire(self, thread_id=None, *, user_id=None):
            acquired["called"] = True
            return "sbx-1"

        def get(self, sandbox_id):
            return MagicMock()  # sandbox instance shape doesn't matter for this test

        def release(self, sandbox_id):
            pass

        def reset(self):
            pass

    set_sandbox_provider(_StubProvider())
    try:
        runtime = SimpleNamespace(
            state={"sandbox": None},
            context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
            config=None,
        )
        sandbox = sandbox_tools.ensure_sandbox_initialized(runtime)
        assert sandbox is not None
        assert acquired["called"] is True
    finally:
        reset_sandbox_provider()


# ── Custom provider: authorize called with correct args ────────────────


def test_authorize_sandbox_calls_provider_with_correct_request(monkeypatch):
    """The provider receives resource='sandbox', action='execute', target='*'."""

    class _RecordingProvider:
        name = "recording"

        def __init__(self):
            self.request = None

        def authorize(self, request):
            self.request = request
            return AuthzDecision(allow=True, reasons=[AuthzReason(code="authz.allowed")])

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            return list(candidates)

    provider = _RecordingProvider()
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    authorize_sandbox_execution(context=_context(), app_config=app_config)

    assert provider.request.resource == "sandbox"
    assert provider.request.action == "execute"
    assert provider.request.target == "*"


# ── Gateway auxiliary paths: uploads / artifacts sync ──────────────────
# Regression for the multi-path coverage self-check (pr-review checkpoint 14):
# the uploads and artifacts routers acquire the thread sandbox directly (not
# via ensure_sandbox_initialized) to sync files. A role denied sandbox:execute
# must not trigger sandbox allocation there; the primary operation (upload /
# artifact edit) still succeeds with the sandbox sync skipped.


def _make_upload_app(monkeypatch, provider, *, fail_closed: bool = True):
    """Build a FastAPI app with the uploads router and authz enabled."""
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.routers import uploads as uploads_router

    app_config = _make_app_config()
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=fail_closed, default_role="user")
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: app_config.authorization,
    )
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )

    app = make_authed_test_app()
    app.include_router(uploads_router.router)
    app.dependency_overrides[uploads_router.get_config] = lambda: app_config
    return TestClient(app)


def test_upload_sandbox_sync_skipped_when_denied(monkeypatch, tmp_path):
    """Denied role: upload succeeds, sandbox.acquire is never called."""
    from unittest.mock import AsyncMock, MagicMock

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    client = _make_upload_app(monkeypatch, provider)
    _isolated_uploads_dir(monkeypatch, tmp_path)

    sandbox_provider = MagicMock()
    sandbox_provider.uses_thread_data_mounts = False
    sandbox_provider.acquire_async = AsyncMock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr("app.gateway.routers.uploads.get_sandbox_provider", lambda: sandbox_provider)
    monkeypatch.setattr(
        "app.gateway.deps.get_optional_user_from_request",
        AsyncMock(return_value=_request_user()),
    )

    resp = client.post("/api/threads/upload-test/uploads", files={"files": ("a.txt", b"hello")})
    assert resp.status_code == 200, resp.text
    sandbox_provider.acquire_async.assert_not_called()


def test_upload_sandbox_sync_proceeds_when_allowed(monkeypatch, tmp_path):
    """Allowed role: sandbox.acquire_async is called as before."""
    from unittest.mock import AsyncMock, MagicMock

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": "*"}}})
    client = _make_upload_app(monkeypatch, provider)
    _isolated_uploads_dir(monkeypatch, tmp_path)

    sandbox_provider = MagicMock()
    sandbox_provider.uses_thread_data_mounts = False
    sandbox_provider.acquire_async = AsyncMock(return_value="sbx-1")
    sandbox_provider.get = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("app.gateway.routers.uploads.get_sandbox_provider", lambda: sandbox_provider)
    monkeypatch.setattr(
        "app.gateway.deps.get_optional_user_from_request",
        AsyncMock(return_value=_request_user()),
    )

    resp = client.post("/api/threads/upload-test/uploads", files={"files": ("a.txt", b"hello")})
    assert resp.status_code == 200, resp.text
    sandbox_provider.acquire_async.assert_called_once()


def _isolated_uploads_dir(monkeypatch, tmp_path):
    """Redirect thread uploads storage to tmp_path (test-isolation).

    Without this the upload route writes into the real global uploads root,
    polluting other tests that assert on uploads directory state.
    """
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)
    monkeypatch.setattr("app.gateway.routers.uploads.get_uploads_dir", lambda thread_id, user_id=None: uploads_dir)
    monkeypatch.setattr("app.gateway.routers.uploads.ensure_uploads_dir", lambda thread_id, user_id=None: uploads_dir)
    return uploads_dir


def _request_user():
    from types import SimpleNamespace

    return SimpleNamespace(id="user-123", system_role="user", oauth_provider=None, oauth_id=None)


def test_authorize_sandbox_mock_app_config_is_noop():
    """A SimpleNamespace/duck-typed app_config without `authorization` is a no-op.

    Mirrors the mock-safe guard in filter_available_skills_by_authorization
    (skill_filter.py) — regression for the consistency finding willem-bd raised
    on apply_skill_authorization in #4541: the sibling guards use getattr so
    test doubles that don't carry a real AuthorizationConfig don't blow up.
    """
    authorize_sandbox_execution(context=_context(), app_config=SimpleNamespace(sandbox=None))  # must not raise


# ── willem-bd review round 1 regressions ───────────────────────────────


def test_authorize_sandbox_resolution_error_fail_open_allows(monkeypatch):
    """Provider *resolution* error + fail_open → allow (not an inverted deny).

    Regression for willem-bd's finding: resolve_authorization_provider ran
    outside the try, so a misconfigured provider (ValueError) propagated as a
    raw exception and effectively denied under fail_open — inverted semantics.
    """

    def _boom(_config):
        raise ValueError("bad provider class path")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=False)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        _boom,
    )
    authorize_sandbox_execution(context=_context(), app_config=app_config)  # must not raise


def test_authorize_sandbox_resolution_error_fail_closed_denies(monkeypatch):
    """Provider *resolution* error + fail_closed → SandboxAuthorizationError."""

    def _boom(_config):
        raise ValueError("bad provider class path")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=True)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        _boom,
    )
    with pytest.raises(SandboxAuthorizationError):
        authorize_sandbox_execution(context=_context(), app_config=app_config)


def test_eager_before_agent_deny_skips_acquisition(monkeypatch):
    """Eager-path deny skips acquisition instead of raising a run-level error.

    Regression for willem-bd's finding: an exception from before_agent is
    outside any tool call, so it would surface as a graph error rather than
    the RFC §9 friendly ToolMessage. On deny the middleware now returns None
    (no sandbox assigned); the lazy gate denies per-tool later.
    """
    from types import SimpleNamespace as _NS

    from deerflow.sandbox.middleware import SandboxMiddleware

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    acquired = {"called": False}

    def _no_acquire(_thread_id, *, user_id=None):
        acquired["called"] = True
        return "sbx-1"

    middleware = SandboxMiddleware(lazy_init=False)
    monkeypatch.setattr(middleware, "_acquire_sandbox", _no_acquire)

    runtime = _NS(context={"thread_id": "t1", "user_id": "u1", "user_role": "user"})
    result = middleware.before_agent({"sandbox": None}, runtime)

    assert result is None  # no sandbox assigned
    assert acquired["called"] is False  # acquire never touched


def test_artifact_sandbox_sync_skipped_when_denied(monkeypatch, tmp_path):
    """Artifacts router deny path: host-side update completes, acquire skipped.

    Regression for willem-bd's round-2 nit — the uploads router's deny path
    had coverage but this copy didn't; a reverted gate here would pass the
    suite unnoticed.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.gateway.routers import artifacts as artifacts_router

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: app_config.authorization,
    )
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )

    sandbox_provider = MagicMock()
    sandbox_provider.uses_thread_data_mounts = False
    sandbox_provider.acquire_async = AsyncMock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr(artifacts_router, "get_sandbox_provider", lambda: sandbox_provider)
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _t, _p, user_id=None: tmp_path / "note.txt")

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _allow_write(*_args, **_kwargs):
        yield

    monkeypatch.setattr(artifacts_router, "reserve_artifact_write", _allow_write)
    monkeypatch.setattr(
        "app.gateway.deps.get_optional_user_from_request",
        AsyncMock(return_value=_request_user()),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    from _router_auth_helpers import call_unwrapped

    artifact_path = tmp_path / "note.txt"
    artifact_path.write_bytes(b"before")
    request = type("R", (), {})()  # simple object; only passed through to mocked helpers

    import asyncio
    import hashlib

    from app.gateway.routers.artifacts import ArtifactUpdateRequest

    sha = hashlib.sha256(b"before").hexdigest()
    asyncio.run(
        call_unwrapped(
            artifacts_router.update_artifact,
            "t-denied",
            "mnt/user-data/outputs/note.txt",
            ArtifactUpdateRequest(content="after", expected_sha256=sha),
            request,
        )
    )
    sandbox_provider.acquire_async.assert_not_called()
    assert artifact_path.read_bytes() == b"after"


def test_authorize_sandbox_no_config_file_is_noop(monkeypatch):
    """No readable config.yaml (CI environments) → the gate is a no-op.

    Regression for the CI failure: get_app_config raises FileNotFoundError in
    config-less environments, which previously propagated out of the gate and
    broke ensure_sandbox_initialized's direct-call tests.
    """
    from deerflow.authz import sandbox_authz as mod

    def _no_config():
        raise FileNotFoundError("config.yaml file not found in the project root")

    monkeypatch.setattr("deerflow.config.get_app_config", _no_config)
    # safe_app_config imports get_app_config lazily from deerflow.config.
    assert mod.safe_app_config() is None
    # And the gate itself tolerates app_config=None (same as disabled).
    authorize_sandbox_execution(context=_context(), app_config=None)  # must not raise


def test_upload_gate_tolerates_request_none(monkeypatch, tmp_path):
    """Direct-call tests pass request=None; the uploads gate must not crash.

    Regression for the blocking-io CI failure: get_optional_user_from_request
    dereferences request.cookies on the no-state-user path, so request=None
    raised AttributeError before the None guard.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.gateway.routers import uploads as uploads_router

    _isolated_uploads_dir(monkeypatch, tmp_path)

    sandbox_provider = MagicMock()
    sandbox_provider.uses_thread_data_mounts = False
    sandbox_provider.acquire_async = AsyncMock(return_value="sbx-1")
    sandbox_provider.get = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(uploads_router, "get_sandbox_provider", lambda: sandbox_provider)
    # If the request=None guard were missing, this lookup would dereference
    # request.cookies and raise AttributeError; with the guard it is never called.
    monkeypatch.setattr(
        "app.gateway.deps.get_optional_user_from_request",
        AsyncMock(side_effect=AttributeError("'NoneType' object has no attribute 'cookies'")),
    )

    from io import BytesIO

    from _router_auth_helpers import call_unwrapped
    from fastapi import UploadFile

    config = SimpleNamespace(uploads={"max_files": 5, "max_file_size": 10**6})
    file = UploadFile(filename="a.txt", file=BytesIO(b"hello"))
    # request=None — the None guard must skip the user lookup entirely.
    result = asyncio.run(call_unwrapped(uploads_router.upload_files, "t-none", request=None, files=[file], config=config))
    assert result.success is True
    sandbox_provider.acquire_async.assert_called_once()


def test_ensure_sandbox_initialized_async_denies_on_authz_reject(monkeypatch):
    """Async acquisition path deny: acquire_async never called.

    Regression for willem-bd's round-4 finding — the async gate copy is
    verbatim-sync, so without this test deleting it would leave the suite green.
    """
    from deerflow.sandbox import tools as sandbox_tools

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    sandbox_provider = MagicMock()
    sandbox_provider.acquire_async = AsyncMock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)

    runtime = SimpleNamespace(
        state={"sandbox": None},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )
    import asyncio

    with pytest.raises(SandboxAuthorizationError):
        asyncio.run(sandbox_tools.ensure_sandbox_initialized_async(runtime))
    sandbox_provider.acquire_async.assert_not_called()


def test_ensure_sandbox_initialized_async_rechecks_authz_for_reused_sandbox(monkeypatch):
    """Async tool calls also re-check a revoked grant before sandbox reuse."""
    from deerflow.sandbox import tools as sandbox_tools

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    sandbox_provider = MagicMock()
    sandbox_provider.get.return_value = MagicMock()
    sandbox_provider.acquire_async = AsyncMock(return_value="sbx-new")
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "sbx-existing"}},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )
    import asyncio

    with pytest.raises(SandboxAuthorizationError):
        asyncio.run(sandbox_tools.ensure_sandbox_initialized_async(runtime))
    sandbox_provider.get.assert_not_called()
    sandbox_provider.acquire_async.assert_not_called()


def test_async_provider_is_constructed_on_running_event_loop(monkeypatch):
    """A loop-affine custom provider must not be constructed in a worker."""
    from deerflow.authz.sandbox_authz import authorize_sandbox_execution_async

    provider_module = ModuleType("loop_affine_authz_test_provider")
    constructed_on = []

    class LoopAffineProvider:
        name = "loop-affine"

        def __init__(self):
            self.loop = asyncio.get_running_loop()
            constructed_on.append(self.loop)

        def authorize(self, request):
            return AuthzDecision(allow=True)

        async def aauthorize(self, request):
            assert asyncio.get_running_loop() is self.loop
            return AuthzDecision(allow=True)

        def filter_resources(self, principal, resource_type, candidates):
            return list(candidates)

    provider_module.LoopAffineProvider = LoopAffineProvider
    monkeypatch.setitem(sys.modules, provider_module.__name__, provider_module)

    app_config = _make_app_config()
    app_config.authorization = AuthorizationConfig(
        enabled=True,
        fail_closed=True,
        default_role="user",
        provider=AuthorizationProviderConfig(use=f"{provider_module.__name__}:LoopAffineProvider"),
    )

    async def _run() -> None:
        running_loop = asyncio.get_running_loop()
        await authorize_sandbox_execution_async(context=_context(), app_config=app_config)
        assert constructed_on == [running_loop]

    asyncio.run(_run())


def test_async_sandbox_tool_authorizes_once_via_async_provider(monkeypatch):
    """One async tool invocation must make one async authorization decision."""
    from deerflow.sandbox import tools as sandbox_tools

    provider = MagicMock()
    provider.authorize.return_value = AuthzDecision(allow=True)
    provider.aauthorize = AsyncMock(return_value=AuthzDecision(allow=True))
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    sandbox = MagicMock()
    sandbox.list_dir.return_value = []
    sandbox_provider = MagicMock()
    sandbox_provider.get.return_value = sandbox
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: False)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "sbx-existing"}},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )

    import asyncio

    result = asyncio.run(
        sandbox_tools.ls_tool.coroutine(
            runtime=runtime,
            description="list workspace",
            path="/mnt/user-data/workspace",
        )
    )

    assert result == "(empty)"
    provider.aauthorize.assert_awaited_once()
    provider.authorize.assert_not_called()


def _composed_file_request(name, args, runtime, messages=()):
    from langgraph.prebuilt.tool_node import ToolCallRequest

    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": f"call-{name}"},
        tool=None,
        state={"messages": list(messages)},
        runtime=runtime,
    )


def _install_composed_file_authz(monkeypatch, *, allow=True):
    from deerflow.sandbox import tools as sandbox_tools

    provider = MagicMock()
    provider.authorize.return_value = AuthzDecision(allow=allow)
    provider.aauthorize = AsyncMock(return_value=AuthzDecision(allow=allow))
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    sandbox = MagicMock()
    sandbox.id = "sbx-existing"
    sandbox_provider = MagicMock()
    sandbox_provider.get.return_value = sandbox
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: False)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "sbx-existing"}},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )
    return provider, sandbox, runtime


@pytest.mark.parametrize("tool_name", ["read_file", "write_file", "str_replace"])
def test_composed_sync_file_tool_authorizes_once(monkeypatch, tool_name):
    """Read-before-write re-entry shares one synchronous provider decision."""
    from langchain_core.messages import ToolMessage

    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    from deerflow.sandbox import tools as sandbox_tools

    provider, sandbox, runtime = _install_composed_file_authz(monkeypatch)
    path = "/mnt/user-data/outputs/report.md"
    middleware = ReadBeforeWriteMiddleware()
    messages = ()

    if tool_name == "read_file":
        sandbox.read_file.return_value = "v1"
        args = {"description": "read report", "path": path}

        def handler(_request):
            content = sandbox_tools.read_file_tool.func(runtime, args["description"], path)
            return ToolMessage(content=content, tool_call_id="call-read_file", name="read_file")

    elif tool_name == "write_file":
        sandbox.read_file.side_effect = FileNotFoundError(path)
        args = {"description": "write report", "path": path, "content": "v1"}

        def handler(_request):
            content = sandbox_tools.write_file_tool.func(runtime, args["description"], path, args["content"])
            return ToolMessage(content=content, tool_call_id="call-write_file", name="write_file")

    else:
        import hashlib

        sandbox.read_file.return_value = "v1"
        args = {"description": "edit report", "path": path, "old_str": "v1", "new_str": "v2"}
        read_mark = ToolMessage(content="v1", tool_call_id="prior-read", name="read_file")
        read_mark.additional_kwargs["deerflow_read_mark"] = {
            "path": path,
            "hash": hashlib.sha256(b"v1").hexdigest(),
        }
        messages = (read_mark,)

        def handler(_request):
            content = sandbox_tools.str_replace_tool.func(runtime, args["description"], path, args["old_str"], args["new_str"])
            return ToolMessage(content=content, tool_call_id="call-str_replace", name="str_replace")

    result = middleware.wrap_tool_call(_composed_file_request(tool_name, args, runtime, messages), handler)

    assert result.status != "error"
    provider.authorize.assert_called_once()
    provider.aauthorize.assert_not_called()


@pytest.mark.parametrize("tool_name", ["read_file", "write_file", "str_replace"])
def test_composed_async_file_tool_authorizes_once(monkeypatch, tool_name):
    """Async gate, tool body, and read-mark worker share one async decision."""
    import asyncio

    from langchain_core.messages import ToolMessage

    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    from deerflow.sandbox import tools as sandbox_tools

    provider, sandbox, runtime = _install_composed_file_authz(monkeypatch)
    path = "/mnt/user-data/outputs/report.md"
    middleware = ReadBeforeWriteMiddleware()
    messages = ()

    if tool_name == "read_file":
        sandbox.read_file.return_value = "v1"
        args = {"description": "read report", "path": path}

        async def handler(_request):
            content = await sandbox_tools.read_file_tool.coroutine(runtime, args["description"], path)
            return ToolMessage(content=content, tool_call_id="call-read_file", name="read_file")

    elif tool_name == "write_file":
        sandbox.read_file.side_effect = FileNotFoundError(path)
        args = {"description": "write report", "path": path, "content": "v1"}

        async def handler(_request):
            content = await sandbox_tools.write_file_tool.coroutine(runtime, args["description"], path, args["content"])
            return ToolMessage(content=content, tool_call_id="call-write_file", name="write_file")

    else:
        import hashlib

        sandbox.read_file.return_value = "v1"
        args = {"description": "edit report", "path": path, "old_str": "v1", "new_str": "v2"}
        read_mark = ToolMessage(content="v1", tool_call_id="prior-read", name="read_file")
        read_mark.additional_kwargs["deerflow_read_mark"] = {
            "path": path,
            "hash": hashlib.sha256(b"v1").hexdigest(),
        }
        messages = (read_mark,)

        async def handler(_request):
            content = await sandbox_tools.str_replace_tool.coroutine(runtime, args["description"], path, args["old_str"], args["new_str"])
            return ToolMessage(content=content, tool_call_id="call-str_replace", name="str_replace")

    result = asyncio.run(middleware.awrap_tool_call(_composed_file_request(tool_name, args, runtime, messages), handler))

    assert result.status != "error"
    provider.aauthorize.assert_awaited_once()
    provider.authorize.assert_not_called()


@pytest.mark.parametrize("is_async", [False, True])
def test_composed_write_authorization_deny_is_not_swallowed(monkeypatch, is_async):
    """The gate's generic fail-open path must never turn an authz deny into allow."""
    import asyncio

    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

    provider, sandbox, runtime = _install_composed_file_authz(monkeypatch, allow=False)
    path = "/mnt/user-data/outputs/report.md"
    args = {"description": "write report", "path": path, "content": "v1"}
    request = _composed_file_request("write_file", args, runtime)
    middleware = ReadBeforeWriteMiddleware()
    handler = MagicMock(side_effect=AssertionError("denied handler must not run"))

    if is_async:

        async def async_handler(_request):
            handler(_request)

        result = asyncio.run(middleware.awrap_tool_call(request, async_handler))
        provider.aauthorize.assert_awaited_once()
        provider.authorize.assert_not_called()
    else:
        result = middleware.wrap_tool_call(request, handler)
        provider.authorize.assert_called_once()
        provider.aauthorize.assert_not_called()

    assert result.status == "error"
    assert "not permitted" in str(result.content).lower()
    handler.assert_not_called()
    sandbox.read_file.assert_not_called()


def test_abefore_agent_deny_skips_acquisition(monkeypatch):
    """Async eager path deny: acquisition skipped, no run-level error.

    Async counterpart of test_eager_before_agent_deny_skips_acquisition.
    """
    from deerflow.sandbox.middleware import SandboxMiddleware

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.sandbox_authz.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: app_config)

    acquired = {"called": False}

    async def _no_acquire(_thread_id, *, user_id=None):
        acquired["called"] = True
        return "sbx-1"

    middleware = SandboxMiddleware(lazy_init=False)
    monkeypatch.setattr(middleware, "_acquire_sandbox_async", _no_acquire)

    runtime = SimpleNamespace(context={"thread_id": "t1", "user_id": "u1", "user_role": "user"})
    import asyncio

    result = asyncio.run(middleware.abefore_agent({"sandbox": None}, runtime))

    assert result is None  # no sandbox assigned
    assert acquired["called"] is False  # acquire_async never touched
