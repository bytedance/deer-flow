"""Tests for admin API router."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config
from deerflow.config.tenant_storage import TenantConfig
from deerflow.content_safety.log_storage import AuditLogEntry
from deerflow.cost.storage import UsageRecord


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_config()
    yield
    reset_auth_config()


class AsyncIteratorWrapper:
    """Wrap a list into an async iterator for mocking checkpointer.alist()."""

    def __init__(self, items: list[Any]):
        self._items = items

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeTenantStorage:
    def __init__(self, tenants: list[TenantConfig]):
        self._tenants = {tenant.tenant_id: tenant for tenant in tenants}

    def ensure_default(self) -> TenantConfig:
        tenant = self._tenants.get("default")
        if tenant is None:
            tenant = TenantConfig(
                tenant_id="default",
                name="Default Tenant",
                created_at=datetime.now(UTC).isoformat(),
            )
            self._tenants["default"] = tenant
        return tenant

    def list_all(self) -> list[TenantConfig]:
        return list(self._tenants.values())

    def get(self, tenant_id: str) -> TenantConfig | None:
        return self._tenants.get(tenant_id)

    def create(self, config: TenantConfig) -> TenantConfig:
        if config.tenant_id in self._tenants:
            raise ValueError(f"Tenant {config.tenant_id!r} already exists")
        self._tenants[config.tenant_id] = config
        return config

    def update(self, tenant_id: str, **fields) -> TenantConfig | None:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None
        updated = TenantConfig(
            tenant_id=tenant.tenant_id,
            name=fields.get("name", tenant.name),
            created_at=tenant.created_at,
            is_active=fields.get("is_active", tenant.is_active),
            daily_quota_usd=fields.get("daily_quota_usd", tenant.daily_quota_usd),
            monthly_quota_usd=fields.get("monthly_quota_usd", tenant.monthly_quota_usd),
        )
        self._tenants[tenant_id] = updated
        return updated

    def delete(self, tenant_id: str) -> bool:
        return self._tenants.pop(tenant_id, None) is not None


class FakeProvider:
    def __init__(self, users_by_tenant: dict[str, list[User]] | None = None):
        self._users_by_tenant = users_by_tenant or {}

    async def count_users_by_tenant(self, tenant_id: str) -> int:
        return len(self._users_by_tenant.get(tenant_id, []))

    async def list_users(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[User]:
        users = self._users_by_tenant.get(tenant_id, [])
        return users[offset : offset + limit]

    async def get_user(self, user_id: str) -> User | None:
        for users in self._users_by_tenant.values():
            for user in users:
                if str(user.id) == user_id:
                    return user
        return None

    async def count_admin_users(self) -> int:
        return sum(
            1
            for users in self._users_by_tenant.values()
            for user in users
            if user.system_role in ("superadmin", "tenant_admin")
        )

    async def delete_user(self, user_id: str) -> bool:
        for tenant_id, users in self._users_by_tenant.items():
            remaining = [user for user in users if str(user.id) != user_id]
            if len(remaining) != len(users):
                self._users_by_tenant[tenant_id] = remaining
                return True
        return False


def _tenant(tenant_id: str, name: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        name=name,
        created_at="2026-05-07T00:00:00+00:00",
    )


def _usage_record(
    *,
    tenant_id: str,
    total_tokens: int,
    cost_usd: float,
    timestamp: str = "2026-05-07T10:00:00+00:00",
    thread_id: str | None = None,
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp,
        tenant_id=tenant_id,
        thread_id=thread_id,
        model_name="gpt-4.1",
        input_tokens=total_tokens // 2,
        output_tokens=total_tokens - (total_tokens // 2),
        total_tokens=total_tokens,
        cost_usd=cost_usd,
    )


def _audit_entry(*, tenant_id: str, thread_id: str | None = None) -> AuditLogEntry:
    return AuditLogEntry(
        timestamp="2026-05-07T10:00:00+00:00",
        tenant_id=tenant_id,
        thread_id=thread_id,
        actor_user_id=None,
        direction="input",
        role="user",
        original_text="hello",
        allowed=True,
        reasons=[],
        provider="openai",
    )


def _user(*, email: str, tenant_id: str, system_role: str = "superadmin") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="hash",
        system_role=system_role,  # type: ignore[arg-type]
        tenant_id=tenant_id,
    )


def _make_client(*, tenant_id: str = "default", role: str = "superadmin") -> TestClient:
    from app.gateway.app import create_app
    from app.gateway.auth.dependencies import get_current_user, require_admin

    app = create_app()
    mock_user = MagicMock()
    mock_user.username = "admin"
    mock_user.tenant_id = tenant_id
    mock_user.role = role
    mock_user.auth_method = "jwt"
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[require_admin] = lambda: mock_user

    mock_checkpointer = MagicMock()
    mock_checkpointer.alist = MagicMock(return_value=AsyncIteratorWrapper([]))
    app.state.checkpointer = mock_checkpointer

    return TestClient(app)


def _make_unauth_client() -> TestClient:
    """Create a client with auth enabled but no credentials."""

    load_auth_config_from_dict({"enabled": True})
    return TestClient(__import__("app.gateway.app", fromlist=["create_app"]).create_app())


_CSRF_TOKEN = "test-csrf-token"


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF_TOKEN}


def _csrf_cookies() -> dict[str, str]:
    return {"csrf_token": _CSRF_TOKEN}


def _install_admin_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    usage_records: list[UsageRecord] | None = None,
    tenants: list[TenantConfig] | None = None,
    provider: FakeProvider | None = None,
    thread_counts: dict[str, int] | None = None,
) -> None:
    from app.gateway.routers import admin as admin_router

    monkeypatch.setattr(
        admin_router,
        "_get_cross_tenant_records",
        lambda start_date=None, end_date=None: list(usage_records or []),
    )
    monkeypatch.setattr(
        admin_router,
        "_get_tenant_storage",
        lambda: FakeTenantStorage(list(tenants or [_tenant("default", "Default Tenant")])),
    )
    monkeypatch.setattr(
        admin_router,
        "get_local_provider",
        lambda: provider or FakeProvider(),
    )

    async def _fake_discover_thread_counts(_checkpointer):
        return dict(thread_counts or {})

    monkeypatch.setattr(admin_router, "_discover_thread_counts", _fake_discover_thread_counts)


class TestAdminStats:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/stats")
        assert response.status_code == 401

    def test_returns_stats_for_system_admin(self, monkeypatch: pytest.MonkeyPatch):
        _install_admin_fakes(
            monkeypatch,
            usage_records=[
                _usage_record(tenant_id="default", total_tokens=120, cost_usd=1.2),
                _usage_record(tenant_id="acme", total_tokens=80, cost_usd=0.8),
            ],
            tenants=[_tenant("default", "Default Tenant"), _tenant("acme", "Acme")],
            thread_counts={"default": 2, "acme": 5},
        )

        response = _make_client().get("/api/admin/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tenants"] == 2
        assert data["active_tenants_today"] == 2
        assert data["total_threads"] == 7
        assert data["total_llm_calls_today"] == 2
        assert data["total_tokens_today"] == 200
        assert data["total_cost_today"] == 2.0

    def test_scopes_stats_to_current_tenant(self, monkeypatch: pytest.MonkeyPatch):
        _install_admin_fakes(
            monkeypatch,
            usage_records=[
                _usage_record(tenant_id="acme", total_tokens=120, cost_usd=1.2),
                _usage_record(tenant_id="other", total_tokens=900, cost_usd=9.9),
            ],
            tenants=[_tenant("acme", "Acme"), _tenant("other", "Other")],
            thread_counts={"acme": 2, "other": 8},
        )

        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tenants"] == 1
        assert data["active_tenants_today"] == 1
        assert data["total_threads"] == 2
        assert data["total_llm_calls_today"] == 1
        assert data["total_tokens_today"] == 120
        assert data["total_cost_today"] == 1.2
        assert data["total_cost_month"] == 1.2

    def test_rejects_non_admin(self):
        from app.gateway.app import create_app
        from app.gateway.auth.dependencies import get_current_user

        app = create_app()
        mock_user = MagicMock()
        mock_user.username = "user"
        mock_user.tenant_id = "default"
        mock_user.role = "member"
        mock_user.auth_method = "jwt"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)

        response = client.get("/api/admin/stats")

        assert response.status_code == 403


class TestListTenants:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/tenants")
        assert response.status_code == 401

    def test_returns_tenant_list_for_system_admin(self, monkeypatch: pytest.MonkeyPatch):
        provider = FakeProvider(
            {
                "default": [_user(email="root@example.com", tenant_id="default")],
                "acme": [_user(email="admin@acme.com", tenant_id="acme", system_role="tenant_admin")],
            }
        )
        _install_admin_fakes(
            monkeypatch,
            usage_records=[_usage_record(tenant_id="acme", total_tokens=30, cost_usd=0.3)],
            tenants=[_tenant("default", "Default Tenant"), _tenant("acme", "Acme")],
            provider=provider,
            thread_counts={"default": 1, "acme": 4},
        )

        response = _make_client().get("/api/admin/tenants")

        assert response.status_code == 200
        data = response.json()
        assert [tenant["tenant_id"] for tenant in data] == ["acme", "default"]

    def test_returns_only_current_tenant_for_scoped_admin(self, monkeypatch: pytest.MonkeyPatch):
        provider = FakeProvider(
            {
                "acme": [_user(email="admin@acme.com", tenant_id="acme", system_role="tenant_admin")],
                "other": [_user(email="admin@other.com", tenant_id="other", system_role="tenant_admin")],
            }
        )
        _install_admin_fakes(
            monkeypatch,
            usage_records=[
                _usage_record(tenant_id="acme", total_tokens=30, cost_usd=0.3),
                _usage_record(tenant_id="other", total_tokens=700, cost_usd=7.0),
            ],
            tenants=[_tenant("acme", "Acme"), _tenant("other", "Other")],
            provider=provider,
            thread_counts={"acme": 4, "other": 99},
        )

        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/tenants")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["tenant_id"] == "acme"
        assert data[0]["user_count"] == 1
        assert data[0]["thread_count"] == 4


class TestCreateTenant:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.post(
            "/api/admin/tenants",
            json={"tenant_id": "new-t", "name": "New"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        assert response.status_code == 401

    def test_system_admin_can_create_tenant(self, monkeypatch: pytest.MonkeyPatch):
        storage = FakeTenantStorage([_tenant("default", "Default Tenant")])
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "_get_tenant_storage", lambda: storage)

        response = _make_client().post(
            "/api/admin/tenants",
            json={"tenant_id": "new-t", "name": "New Tenant"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "new-t"
        assert data["name"] == "New Tenant"

    def test_scoped_admin_cannot_create_tenant(self):
        response = _make_client(tenant_id="acme", role="tenant_admin").post(
            "/api/admin/tenants",
            json={"tenant_id": "other", "name": "Other"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        assert response.status_code == 403

    def test_rejects_invalid_tenant_id(self):
        response = _make_client().post(
            "/api/admin/tenants",
            json={"tenant_id": "invalid id!", "name": "Bad"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        assert response.status_code == 422


class TestUpdateTenant:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.put(
            "/api/admin/tenants/t1",
            json={"name": "Updated"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        assert response.status_code == 401

    def test_system_admin_can_update_any_tenant(self, monkeypatch: pytest.MonkeyPatch):
        storage = FakeTenantStorage([_tenant("default", "Default Tenant"), _tenant("acme", "Acme")])
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "_get_tenant_storage", lambda: storage)

        response = _make_client().put(
            "/api/admin/tenants/acme",
            json={"name": "Updated Name"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_scoped_admin_can_only_update_own_tenant(self, monkeypatch: pytest.MonkeyPatch):
        storage = FakeTenantStorage([_tenant("acme", "Acme"), _tenant("other", "Other")])
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "_get_tenant_storage", lambda: storage)

        own_response = _make_client(tenant_id="acme", role="tenant_admin").put(
            "/api/admin/tenants/acme",
            json={"name": "Acme Updated"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        cross_response = _make_client(tenant_id="acme", role="tenant_admin").put(
            "/api/admin/tenants/other",
            json={"name": "Other Updated"},
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )

        assert own_response.status_code == 200
        assert own_response.json()["name"] == "Acme Updated"
        assert cross_response.status_code == 403


class TestDeleteTenant:
    def test_system_admin_can_delete_other_tenant(self, monkeypatch: pytest.MonkeyPatch):
        storage = FakeTenantStorage([_tenant("default", "Default Tenant"), _tenant("acme", "Acme")])
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "_get_tenant_storage", lambda: storage)

        response = _make_client().delete(
            "/api/admin/tenants/acme",
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}

    def test_scoped_admin_cannot_delete_tenant(self):
        response = _make_client(tenant_id="acme", role="tenant_admin").delete(
            "/api/admin/tenants/acme",
            headers=_csrf_headers(),
            cookies=_csrf_cookies(),
        )
        assert response.status_code == 403


class TestTenantUsers:
    def test_system_admin_can_list_any_tenant_users(self, monkeypatch: pytest.MonkeyPatch):
        provider = FakeProvider(
            {
                "acme": [
                    _user(email="admin@acme.com", tenant_id="acme", system_role="tenant_admin"),
                    _user(email="user@acme.com", tenant_id="acme", system_role="user"),
                ],
            }
        )
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "get_local_provider", lambda: provider)

        response = _make_client().get("/api/admin/tenants/acme/users")

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_scoped_admin_cannot_list_other_tenant_users(self, monkeypatch: pytest.MonkeyPatch):
        provider = FakeProvider({"other": [_user(email="admin@other.com", tenant_id="other", system_role="tenant_admin")]})
        from app.gateway.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "get_local_provider", lambda: provider)

        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/tenants/other/users")

        assert response.status_code == 403


class TestAdminUsage:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/usage")
        assert response.status_code == 401

    def test_returns_usage_data_for_system_admin(self, monkeypatch: pytest.MonkeyPatch):
        _install_admin_fakes(
            monkeypatch,
            usage_records=[
                _usage_record(tenant_id="default", total_tokens=120, cost_usd=1.2),
                _usage_record(tenant_id="acme", total_tokens=80, cost_usd=0.8),
            ],
        )

        response = _make_client().get("/api/admin/usage")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_scopes_usage_to_current_tenant(self, monkeypatch: pytest.MonkeyPatch):
        _install_admin_fakes(
            monkeypatch,
            usage_records=[
                _usage_record(tenant_id="acme", total_tokens=120, cost_usd=1.2),
                _usage_record(tenant_id="other", total_tokens=900, cost_usd=9.9),
            ],
        )

        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/usage")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["tenant_id"] == "acme"


class TestAuditLogs:
    def test_defaults_logs_to_current_tenant(self, monkeypatch: pytest.MonkeyPatch):
        from app.gateway.routers import admin as admin_router

        storage = MagicMock()
        storage.query.return_value = ([_audit_entry(tenant_id="acme")], 1)
        monkeypatch.setattr(admin_router, "_get_audit_storage", lambda: storage)

        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/logs")

        assert response.status_code == 200
        assert response.json()["entries"][0]["tenant_id"] == "acme"
        assert storage.query.call_args.kwargs["tenant_id"] == "acme"

    def test_rejects_cross_tenant_log_filter_for_scoped_admin(self):
        response = _make_client(tenant_id="acme", role="tenant_admin").get("/api/admin/logs?tenant_id=other")
        assert response.status_code == 403
