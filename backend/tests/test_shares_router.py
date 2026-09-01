"""HTTP-level security tests for read-only conversation sharing (#4548).

Pins the authorization properties from the design: owner-scoped
create/list/revoke, narrow middleware exemption for the public GET only,
indistinguishable 404s for invalid/revoked/expired links, and the public
endpoint never touching thread state under a synthetic principal.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.middleware.base import BaseHTTPMiddleware

import deerflow.persistence.models  # noqa: F401  (register every table)
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import shares as shares_router
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.base import Base
from deerflow.persistence.conversation_shares import ConversationShareRepository
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

USER_A = User(email="owner-a@example.com", password_hash="x", system_role="user", id=uuid4())
USER_B = User(email="intruder-b@example.com", password_hash="x", system_role="user", id=uuid4())
THREAD_A = "thread-owned-by-a"

_SNAPSHOT = {"version": 1, "messages": [{"id": "m1", "role": "user", "content": "hello"}]}


def _config(*, enabled: bool, allow_no_expiry: bool = False, default_expiry_days: int = 30) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "conversation_sharing": {
                "enabled": enabled,
                "allow_no_expiry": allow_no_expiry,
                "default_expiry_days": default_expiry_days,
            },
        }
    )


async def _make_repo(tmp_path) -> ConversationShareRepository:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/shares.db", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return ConversationShareRepository(async_sessionmaker(engine, expire_on_commit=False))


def _thread_store() -> MemoryThreadMetaStore:
    store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(store.create(THREAD_A, user_id=str(USER_A.id)))
    return store


@contextmanager
def _client(tmp_path, *, user=USER_A, enabled=True, allow_no_expiry=False, with_repo=True, default_expiry_days: int = 30):
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
    from app.gateway.shares.tokens import set_share_pepper

    class _AuthSourceTag(BaseHTTPMiddleware):
        # The shared stub middleware deliberately does not set auth_source
        # (other suites depend on its anonymous-resolution semantics); these
        # routes resolve the caller via get_current_user, which requires it.
        async def dispatch(self, request: Request, call_next: Callable) -> Response:
            request.state.auth_source = AUTH_SOURCE_SESSION
            return await call_next(request)

    set_app_config(_config(enabled=enabled, allow_no_expiry=allow_no_expiry, default_expiry_days=default_expiry_days))
    set_share_pepper("test-pepper")
    app = make_authed_test_app(user_factory=lambda: user)
    app.add_middleware(_AuthSourceTag)
    app.include_router(shares_router.router)
    app.state.thread_store = _thread_store()
    repo = asyncio.run(_make_repo(tmp_path)) if with_repo else None
    app.state.share_repo = repo
    shares_router._public_resolve_hits.clear()
    try:
        with TestClient(app) as client:
            yield client, repo
    finally:
        set_share_pepper(None)
        reset_app_config()


def _create(client: TestClient, *, thread_id: str = THREAD_A, payload: dict | None = None) -> object:
    return client.post(f"/api/threads/{thread_id}/shares", json=payload or {})


# ── Feature gate ──────────────────────────────────────────────────────────


def test_disabled_deployment_rejects_management_and_public(tmp_path):
    with _client(tmp_path, enabled=False) as (client, _repo):
        assert _create(client).status_code == 403
        assert client.get("/api/threads/" + THREAD_A + "/shares").status_code == 403
        assert client.get("/api/shares/dfs_whatever").status_code == 404


def test_memory_backend_fails_explicitly(tmp_path):
    with _client(tmp_path, with_repo=False) as (client, _none):
        response = _create(client)
        assert response.status_code == 503


# ── Ownership ─────────────────────────────────────────────────────────────


def test_cross_user_create_returns_404(tmp_path):
    with _client(tmp_path, user=USER_B) as (client, repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            response = _create(client)
    assert response.status_code == 404
    assert repo is not None and asyncio.run(repo.list_by_thread(THREAD_A, str(USER_B.id))) == []


def test_cross_user_revoke_returns_404(tmp_path):
    with _client(tmp_path) as (client, repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            created = _create(client).json()
        switch = _client(tmp_path, user=USER_B)
        with switch as (client_b, _repo_b):
            client_b.cookies.clear()
            response = client_b.delete(f"/api/threads/{THREAD_A}/shares/{created['share_id']}")
    assert response.status_code == 404
    # The share is still active for the real owner.
    assert asyncio.run(repo.get(created["share_id"]))["revoked_at"] is None


# ── Create semantics ──────────────────────────────────────────────────────


def test_create_returns_show_once_url_and_persists_only_hash(tmp_path):
    with _client(tmp_path) as (client, repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            response = _create(client, payload={"title": "My title"})
    assert response.status_code == 201
    body = response.json()
    assert body["share_url"].startswith("/share/dfs_")
    assert body["expires_at"] is not None  # default finite expiry
    row = asyncio.run(repo.get(body["share_id"]))
    assert row["token_hash"] != body["share_url"].split("/share/")[-1]
    assert row["snapshot_json"] == _SNAPSHOT
    # created_at reflects the persisted record, not response-time now().
    assert body["created_at"] == str(row["created_at"])


def test_custom_title_private_artifact_reference_is_neutralized_before_persistence(tmp_path):
    private_title = "/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf"
    with _client(tmp_path) as (client, repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            response = _create(client, payload={"title": private_title})

        body = response.json()
        row = asyncio.run(repo.get(body["share_id"]))
        token = body["share_url"].split("/share/")[-1]
        public = client.get(f"/api/shares/{token}").json()

    assert response.status_code == 201
    assert body["title"] == "[private artifact omitted]"
    assert row["title"] == "[private artifact omitted]"
    assert public["title"] == "[private artifact omitted]"


def test_public_resolution_defensively_neutralizes_private_title_from_storage(tmp_path):
    private_title = "/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf"
    token = "dfs_legacy-private-title"
    with _client(tmp_path) as (client, repo):
        asyncio.run(
            repo.create(
                thread_id=THREAD_A,
                owner_user_id=str(USER_A.id),
                token_hash=_hash(token),
                title=private_title,
                snapshot_json=_SNAPSHOT,
            )
        )

        response = client.get(f"/api/shares/{token}")

    assert response.status_code == 200
    assert response.json()["title"] == "[private artifact omitted]"


def test_public_resolution_defensively_neutralizes_private_message_from_storage(tmp_path):
    """Round-9 P1: snapshots are immutable once minted, so a stored message
    that still carries a private path — written through a sanitizer defect or
    before the rules were tightened — must be re-sanitized at the public read
    boundary, exactly like the title already is."""
    bad_snapshot = {
        "version": 1,
        "messages": [
            {"id": "m1", "role": "user", "content": "fetch /api/threads/thread-secret/artifacts/report.pdf for the data"},
        ],
    }
    token = "dfs_legacy-private-message"
    with _client(tmp_path) as (client, repo):
        asyncio.run(
            repo.create(
                thread_id=THREAD_A,
                owner_user_id=str(USER_A.id),
                token_hash=_hash(token),
                title="Fine title",
                snapshot_json=bad_snapshot,
            )
        )

        response = client.get(f"/api/shares/{token}")

    assert response.status_code == 200
    content = response.json()["snapshot"]["messages"][0]["content"]
    assert "thread-secret" not in content
    assert "[private artifact omitted]" in content


def test_operator_default_expiry_is_honored_without_coercion(tmp_path):
    """A configured default outside {1,7,30} must be used as-is, not coerced."""
    with _client(tmp_path, default_expiry_days=14) as (client, repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            response = _create(client)
    assert response.status_code == 201
    row = asyncio.run(repo.get(response.json()["share_id"]))
    from datetime import UTC, datetime

    expires_at = datetime.fromisoformat(str(row["expires_at"]))
    delta_days = (expires_at - datetime.now(UTC)).total_seconds() / 86400
    assert 13.9 < delta_days < 14.1


def test_create_rejects_invalid_expiry_choices_and_no_expiry(tmp_path):
    with _client(tmp_path) as (client, _repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            assert _create(client, payload={"expires_in_days": 5}).status_code == 400
            assert _create(client, payload={"never_expires": True}).status_code == 400


def test_create_allows_no_expiry_when_deployed_for_it(tmp_path):
    with _client(tmp_path, allow_no_expiry=True) as (client, _repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            response = _create(client, payload={"never_expires": True})
    assert response.status_code == 201
    assert response.json()["expires_at"] is None


def test_create_empty_conversation_conflict(tmp_path):
    with _client(tmp_path) as (client, _repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value={"version": 1, "messages": []})):
            response = _create(client)
    assert response.status_code == 409


def test_create_rejects_oversized_conversation_without_persisting(tmp_path):
    """A conversation too long to snapshot is rejected, never silently truncated."""
    from app.gateway.shares.snapshot import ShareSnapshotTooLarge

    with _client(tmp_path) as (client, repo):
        snapshot_mock = AsyncMock(side_effect=ShareSnapshotTooLarge(THREAD_A, 2000, 2000))
        with patch.object(shares_router, "build_share_snapshot", snapshot_mock):
            response = _create(client)
        assert response.status_code == 413
        assert "too long to share" in response.json()["detail"]
        assert asyncio.run(repo.list_by_thread(THREAD_A, str(USER_A.id))) == []


def test_list_strips_token_hashes(tmp_path):
    with _client(tmp_path) as (client, _repo):
        with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            _create(client)
        listed = client.get(f"/api/threads/{THREAD_A}/shares").json()
    assert len(listed) == 1
    assert "token_hash" not in listed[0]
    assert "share_url" not in listed[0]


# ── Public resolution ─────────────────────────────────────────────────────


def _mint(client: TestClient, repo: ConversationShareRepository, **overrides) -> str:
    with patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
        created = _create(client).json()
    return created["share_url"].split("/share/")[-1]


def test_public_get_resolves_snapshot_without_thread_access(tmp_path):
    with _client(tmp_path) as (client, repo):
        token = _mint(client, repo)
        with patch("app.gateway.deps.get_thread_store", side_effect=AssertionError("public read must not touch thread state")):
            response = client.get(f"/api/shares/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"] == _SNAPSHOT
    # No private identifiers cross the boundary.
    assert "thread_id" not in body and "token_hash" not in body
    # Token-in-URL mitigations: the public response forbids referrer leakage
    # and any browser/proxy caching, so revoked or expired shares stop being
    # served the moment the server rejects them.
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"


def test_public_get_is_exempt_from_auth_middleware(tmp_path):
    """Anonymous request reaches the route (404 for the unknown token), not 401."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(shares_router.router)
    set_app_config(_config(enabled=True))
    app.state.share_repo = None
    try:
        with TestClient(app) as client:
            response = client.get("/api/shares/dfs_unknown-token")
    finally:
        reset_app_config()
    assert response.status_code == 404  # route verdict, not middleware 401
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"


# ── The sharpest edges: auth-disabled mode and null-owner threads ─────────


def _enable_auth_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    # Production markers make is_auth_disabled() refuse to take effect —
    # clear them so the test exercises the mode deterministically.
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def _null_owner_thread_store() -> MemoryThreadMetaStore:
    store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(store.create("thread-null-owner", user_id=None))
    return store


def test_auth_disabled_mode_does_not_auto_publish(monkeypatch, tmp_path):
    """DEER_FLOW_AUTH_DISABLED=1 must not make conversations implicitly public.

    The synthetic admin can mint links for threads they own, but public
    resolution still requires an explicit share record in every mode.
    """
    _enable_auth_disabled(monkeypatch)
    set_app_config(_config(enabled=True))
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(shares_router.router)
    # The synthetic auth-disabled principal is the "default" admin; give it a
    # genuinely owned thread (strict ownership applies in every mode).
    store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(store.create("thread-admin-owned", user_id="default"))
    app.state.thread_store = store
    repo = asyncio.run(_make_repo(tmp_path))
    app.state.share_repo = repo
    from app.gateway.shares.tokens import set_share_pepper

    set_share_pepper("test-pepper")
    try:
        with TestClient(app) as client, patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            # No record yet: 404 even though every requester is a synthetic admin.
            assert client.get("/api/shares/dfs_any-token").status_code == 404

            # The synthetic admin can mint a link for an owned thread…
            created = client.post("/api/threads/thread-admin-owned/shares", json={})
            assert created.status_code == 201, created.text
            token = created.json()["share_url"].split("/share/")[-1]

            # …and only that explicit record becomes publicly readable.
            assert client.get(f"/api/shares/{token}").status_code == 200
    finally:
        set_share_pepper(None)
        reset_app_config()


def test_null_owner_and_untracked_threads_cannot_be_published(tmp_path):
    """Strict ownership on create: permissive owner_check semantics must not
    let an authenticated user publish pre-auth (user_id=NULL) or untracked
    legacy threads."""
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
    from app.gateway.shares.tokens import set_share_pepper

    class _AuthSourceTag(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable) -> Response:
            request.state.auth_source = AUTH_SOURCE_SESSION
            return await call_next(request)

    store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(store.create("thread-null-owner", user_id=None))
    set_app_config(_config(enabled=True))
    app = make_authed_test_app(user_factory=lambda: USER_A)
    app.add_middleware(_AuthSourceTag)
    app.include_router(shares_router.router)
    app.state.thread_store = store
    app.state.share_repo = asyncio.run(_make_repo(tmp_path))
    set_share_pepper("test-pepper")
    try:
        with TestClient(app) as client, patch.object(shares_router, "build_share_snapshot", AsyncMock(return_value=_SNAPSHOT)):
            assert client.post("/api/threads/thread-null-owner/shares", json={}).status_code == 404
            assert client.post("/api/threads/thread-never-existed/shares", json={}).status_code == 404
    finally:
        set_share_pepper(None)
        reset_app_config()


def test_only_the_public_get_is_mounted_under_the_exempt_prefix():
    """The /api/shares/ auth exemption is prefix-based in the middleware, so
    the mounted surface under it must stay exactly one anonymous GET — a
    future route there would otherwise ship silently unauthenticated.

    Two scans: live routers (mounted APIRoutes) and an AST sweep of every
    app/gateway module for route decorators targeting /api/shares/ paths, so
    a route registered on a differently-named router or directly on the app
    object cannot slip past the live scan.
    """
    import importlib
    import pkgutil

    from fastapi.routing import APIRoute

    import app.gateway.routers as routers_pkg

    for module_info in pkgutil.iter_modules(routers_pkg.__path__):
        module = importlib.import_module(f"app.gateway.routers.{module_info.name}")
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/api/shares/"):
                assert route.methods == {"GET"}, f"{module_info.name}: {route.path} is {route.methods}, not GET-only"
                assert route.path == "/api/shares/{share_token}"


def test_no_non_get_route_decorator_targets_the_exempt_prefix():
    """AST sweep: any decorator call like ``X.post("/api/shares/...")`` in
    app/gateway code must be GET — regardless of the router attribute name or
    whether it is registered on the app object directly."""
    import ast
    from pathlib import Path

    gateway_dir = Path(__file__).resolve().parent.parent / "app" / "gateway"
    violations = []
    for path in sorted(gateway_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            if not node.args[0].value.startswith("/api/shares/"):
                continue
            if node.func.attr != "get":
                violations.append(f"{path.name}: {node.func.attr} {node.args[0].value}")
    assert not violations, "non-GET routes under the auth-exempt /api/shares/ prefix:\n" + "\n".join(violations)


def test_null_owner_thread_without_share_record_is_not_public(tmp_path):
    """A legacy user_id=NULL thread stays private without an explicit record."""
    with _client(tmp_path) as (client, repo):
        token = "dfs_null-owner-explicit"
        asyncio.run(
            repo.create(
                thread_id="thread-null-owner",
                owner_user_id=str(USER_A.id),
                token_hash=_hash(token),
                title="legacy thread",
                snapshot_json=_SNAPSHOT,
            )
        )
        # Without a record: unknown token → 404 (covered above); the pinned
        # property here is that the record itself is the only gate.
        assert client.get(f"/api/shares/{token}").status_code == 200


def test_public_read_never_widens_access_via_null_owner_path(tmp_path):
    """Resolving a null-owner thread's share must not re-read thread state.

    The null-owner check_access path (which allows every authenticated user)
    must never be reachable from the public endpoint — possession of the
    token grants exactly the immutable snapshot and nothing else.
    """
    with _client(tmp_path) as (client, repo):
        token = "dfs_null-owner-widening"
        asyncio.run(
            repo.create(
                thread_id="thread-null-owner",
                owner_user_id=str(USER_A.id),
                token_hash=_hash(token),
                title="legacy thread",
                snapshot_json=_SNAPSHOT,
            )
        )
        with patch("app.gateway.deps.get_thread_store", side_effect=AssertionError("public read must never consult thread access")):
            response = client.get(f"/api/shares/{token}")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"title", "snapshot_version", "snapshot"}


def test_revoked_expired_and_unknown_tokens_share_one_404(tmp_path):
    with _client(tmp_path) as (client, repo):
        token = _mint(client, repo)
        # Resolve via repo list to find the share id for revocation.
        rows = asyncio.run(repo.list_by_thread(THREAD_A, str(USER_A.id)))
        assert asyncio.run(repo.revoke(rows[0]["id"], THREAD_A, str(USER_A.id))) is True
        revoked = client.get(f"/api/shares/{token}")
        assert revoked.status_code == 404

        # An expired link behaves identically.
        expired_token = "dfs_expired"
        asyncio.run(
            repo.create(
                thread_id=THREAD_A,
                owner_user_id=str(USER_A.id),
                token_hash=_hash(expired_token),
                title="t",
                snapshot_json=_SNAPSHOT,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        expired = client.get(f"/api/shares/{expired_token}")
        assert expired.status_code == 404

        unknown = client.get("/api/shares/dfs_garbage")
        assert unknown.status_code == 404
        # Indistinguishable: same status, same body.
        assert revoked.json() == expired.json() == unknown.json()


def _hash(token: str) -> str:
    from app.gateway.shares.tokens import share_token_hash

    return share_token_hash(token, "test-pepper")


def test_public_resolution_is_throttled_per_ip(tmp_path):
    with _client(tmp_path) as (client, repo):
        token = _mint(client, repo)
        statuses = [client.get(f"/api/shares/{token}").status_code for _ in range(shares_router._PUBLIC_RESOLVE_MAX_PER_WINDOW + 5)]
    assert statuses[0] == 200
    assert statuses[-1] == 404  # throttled within the window


def test_public_resolution_buckets_by_resolved_client_ip(tmp_path, monkeypatch):
    """Behind a trusted proxy the throttle keys on the resolved client IP, not
    the proxy peer — visitors get separate buckets instead of one global one
    (the shipped nginx topology previously made the limit effectively global)."""
    resolved = {"current": "198.51.100.1"}

    def fake_get_client_ip(request):
        return resolved["current"]

    monkeypatch.setattr(shares_router, "get_client_ip", fake_get_client_ip)
    with _client(tmp_path) as (client, repo):
        token = _mint(client, repo)
        # Visitor A fills their own bucket…
        for _ in range(shares_router._PUBLIC_RESOLVE_MAX_PER_WINDOW):
            assert client.get(f"/api/shares/{token}").status_code == 200
        assert client.get(f"/api/shares/{token}").status_code == 404  # A is throttled
        # …but visitor B is a separate bucket and still resolves.
        resolved["current"] = "198.51.100.2"
        assert client.get(f"/api/shares/{token}").status_code == 200


def test_resolve_tracker_prunes_oldest_without_flushing_everyone():
    """Exceeding the tracker cap evicts the longest-idle entries instead of
    clearing everything — a wholesale flush would reset every visitor's hit
    history and let anyone rotating past the cap un-throttle themselves."""
    cap = shares_router._PUBLIC_RESOLVE_TRACKER_MAX_IPS
    now = time.monotonic()
    shares_router._public_resolve_hits.clear()
    try:
        # Fill the tracker just under the cap with fresh-but-older entries…
        for index in range(cap - 1):
            shares_router._public_resolve_hits[f"10.1.{index // 256}.{index % 256}"] = [now - 5.0]
        # …then two very recent visitors who must survive the prune.
        assert not shares_router._public_resolve_throttled("198.51.100.9")
        assert not shares_router._public_resolve_throttled("198.51.100.10")  # pushes past the cap
        assert len(shares_router._public_resolve_hits) == cap
        assert "198.51.100.9" in shares_router._public_resolve_hits
        assert "198.51.100.10" in shares_router._public_resolve_hits
    finally:
        shares_router._public_resolve_hits.clear()
