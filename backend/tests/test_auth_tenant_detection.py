"""Tests for tenant auto-detection in login flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.password import hash_password
from app.gateway.auth.providers import TenantSelectionRequired


def _make_user(email: str = "user@example.com", tenant_id: str = "default", password: str = "TestPass123") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        tenant_id=tenant_id,
    )


def _make_provider(users_by_email: list[User] | None = None, user_by_email_and_tenant: User | None = None) -> LocalAuthProvider:
    mock_repo = MagicMock()
    mock_repo.get_users_by_email = AsyncMock(return_value=users_by_email or [])
    mock_repo.get_user_by_email_and_tenant = AsyncMock(return_value=user_by_email_and_tenant)
    mock_repo.update_user = AsyncMock(side_effect=lambda u: u)
    return LocalAuthProvider(mock_repo)


class TestAutoDetectSingleTenant:
    def test_single_tenant_correct_password(self):
        user = _make_user(tenant_id="zm", password="Correct123")
        provider = _make_provider(users_by_email=[user])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "Correct123"}))

        assert result is not None
        assert not isinstance(result, TenantSelectionRequired)
        assert result.tenant_id == "zm"
        assert result.email == "user@example.com"

    def test_single_tenant_wrong_password(self):
        user = _make_user(tenant_id="zm", password="Correct123")
        provider = _make_provider(users_by_email=[user])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "WrongPass1"}))

        assert result is None

    def test_email_not_found(self):
        provider = _make_provider(users_by_email=[])

        result = asyncio.run(provider.authenticate({"email": "nobody@example.com", "password": "AnyPass123"}))

        assert result is None


class TestAutoDetectMultiTenant:
    def test_multi_tenant_single_password_match(self):
        user_zm = _make_user(tenant_id="zm", password="ZmPass123!")
        user_acme = _make_user(tenant_id="acme", password="AcmePass456!")
        provider = _make_provider(users_by_email=[user_zm, user_acme])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "ZmPass123!"}))

        assert result is not None
        assert not isinstance(result, TenantSelectionRequired)
        assert result.tenant_id == "zm"

    def test_multi_tenant_multiple_password_match_returns_selection_required(self):
        password = "SharedPass123!"
        user_zm = _make_user(tenant_id="zm", password=password)
        user_acme = _make_user(tenant_id="acme", password=password)
        provider = _make_provider(users_by_email=[user_zm, user_acme])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": password}))

        assert isinstance(result, TenantSelectionRequired)
        assert len(result.tenants) == 2
        tenant_ids = {t["tenant_id"] for t in result.tenants}
        assert tenant_ids == {"zm", "acme"}

    def test_multi_tenant_no_password_match(self):
        user_zm = _make_user(tenant_id="zm", password="ZmPass123!")
        user_acme = _make_user(tenant_id="acme", password="AcmePass456!")
        provider = _make_provider(users_by_email=[user_zm, user_acme])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "WrongForAll!"}))

        assert result is None


class TestExplicitTenant:
    def test_explicit_tenant_uses_original_logic(self):
        user = _make_user(tenant_id="zm", password="Correct123")
        provider = _make_provider(user_by_email_and_tenant=user)

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "Correct123", "tenant_id": "zm"}))

        assert result is not None
        assert not isinstance(result, TenantSelectionRequired)
        assert result.tenant_id == "zm"
        provider._repo.get_users_by_email.assert_not_called()

    def test_explicit_tenant_wrong_password(self):
        user = _make_user(tenant_id="zm", password="Correct123")
        provider = _make_provider(user_by_email_and_tenant=user)

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "WrongPass1", "tenant_id": "zm"}))

        assert result is None
        provider._repo.get_users_by_email.assert_not_called()

    def test_explicit_tenant_user_not_found(self):
        provider = _make_provider(user_by_email_and_tenant=None)

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "AnyPass123", "tenant_id": "nonexistent"}))

        assert result is None


class TestMaxTenantVerifyLimit:
    def test_exceeds_limit_with_matching_password_returns_selection_required(self):
        password = "SharedPass1!"
        users = [_make_user(tenant_id=f"tenant_{i}", password=password) for i in range(11)]
        provider = _make_provider(users_by_email=users)

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": password}))

        assert isinstance(result, TenantSelectionRequired)
        assert len(result.tenants) >= 2

    def test_exceeds_limit_with_no_matching_password_returns_none(self):
        users = [_make_user(tenant_id=f"tenant_{i}", password=f"UniquePass{i}!") for i in range(11)]
        provider = _make_provider(users_by_email=users)

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": "WrongForAll!"}))

        assert result is None


class TestRehashBehavior:
    def test_rehash_on_single_match(self):
        import bcrypt

        password = "RehashMe123!"
        legacy_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user = User(id=uuid4(), email="rehash@test.com", password_hash=legacy_hash, tenant_id="zm")

        provider = _make_provider(users_by_email=[user])

        result = asyncio.run(provider.authenticate({"email": "rehash@test.com", "password": password}))

        assert result is not None
        assert result.password_hash.startswith("$dfv2$")
        provider._repo.update_user.assert_called_once()

    def test_no_rehash_on_multi_match_409(self):
        password = "SharedPass123!"
        user_zm = _make_user(tenant_id="zm", password=password)
        user_acme = _make_user(tenant_id="acme", password=password)
        provider = _make_provider(users_by_email=[user_zm, user_acme])

        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": password}))

        assert isinstance(result, TenantSelectionRequired)
        provider._repo.update_user.assert_not_called()


class TestGetUsersByEmail:
    def test_returns_empty_list_for_unknown_email(self):
        provider = _make_provider(users_by_email=[])
        result = asyncio.run(provider._repo.get_users_by_email("unknown@test.com"))
        assert result == []

    def test_returns_multiple_users(self):
        users = [_make_user(tenant_id="a"), _make_user(tenant_id="b")]
        provider = _make_provider(users_by_email=users)
        result = asyncio.run(provider._repo.get_users_by_email("user@example.com"))
        assert len(result) == 2


class TestEdgeCases:
    def test_empty_email(self):
        provider = _make_provider()
        result = asyncio.run(provider.authenticate({"email": "", "password": "AnyPass123"}))
        assert result is None

    def test_empty_password(self):
        provider = _make_provider()
        result = asyncio.run(provider.authenticate({"email": "user@example.com", "password": ""}))
        assert result is None

    def test_oauth_user_without_password_hash(self):
        user = User(id=uuid4(), email="oauth@test.com", password_hash=None, tenant_id="zm")
        provider = _make_provider(users_by_email=[user])

        result = asyncio.run(provider.authenticate({"email": "oauth@test.com", "password": "AnyPass123"}))

        assert result is None
