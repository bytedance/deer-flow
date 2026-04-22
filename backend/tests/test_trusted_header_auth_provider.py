from __future__ import annotations

import hmac
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.gateway.auth.config import TrustedHeaderProviderConfig
from app.gateway.auth.models import User
from app.gateway.auth.providers import AuthProvider, TrustedHeaderAuthProvider
from app.gateway.auth.repositories.base import UserRepository


class _Repo(UserRepository):
    def __init__(self, users: dict[str, User]):
        self._users = users

    async def create_user(self, user: User) -> User:
        self._users[str(user.id)] = user
        return user

    async def get_user_by_id(self, user_id: str):
        return self._users.get(user_id)

    async def get_user_by_email(self, email: str):
        for user in self._users.values():
            if user.email == email:
                return user
        return None

    async def update_user(self, user: User) -> User:
        self._users[str(user.id)] = user
        return user

    async def count_users(self) -> int:
        return len(self._users)

    async def count_admin_users(self) -> int:
        return sum(1 for u in self._users.values() if u.system_role == "admin")

    async def get_user_by_oauth(self, provider: str, oauth_id: str):
        for user in self._users.values():
            if user.oauth_provider == provider and user.oauth_id == oauth_id:
                return user
        return None


class _Request:
    def __init__(self, headers: dict[str, str], host: str):
        self.headers = headers
        self.client = SimpleNamespace(host=host)


class _NullProvider(AuthProvider):
    async def authenticate(self, credentials: dict):
        return None

    async def get_user(self, user_id: str):
        return None


@pytest.mark.anyio
async def test_trusted_header_provider_reads_primary_header():
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    cfg = TrustedHeaderProviderConfig(enabled=True, trusted_networks=["10.0.0.0/8"], user_id_header="X-Forwarded-User")
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request({"X-Forwarded-User": str(user.id)}, "10.1.2.3")
    resolved = await provider.authenticate_request(req)
    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.anyio
async def test_default_auth_provider_request_hook_returns_none():
    provider = _NullProvider()
    req = _Request({}, "10.0.0.1")
    assert await provider.authenticate_request(req) is None


@pytest.mark.anyio
async def test_trusted_header_provider_rejects_untrusted_ip():
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    cfg = TrustedHeaderProviderConfig(enabled=True, trusted_networks=["10.0.0.0/8"])
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request({"X-Forwarded-User": str(user.id)}, "192.168.1.9")
    assert await provider.authenticate_request(req) is None


@pytest.mark.anyio
async def test_trusted_header_provider_reads_legacy_json_header():
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    cfg = TrustedHeaderProviderConfig(enabled=True, trusted_networks=["10.0.0.0/8"], legacy_user_id_headers=["x-user-info"])
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request({"x-user-info": '{"user_id": "%s"}' % user.id}, "10.8.0.1")
    resolved = await provider.authenticate_request(req)
    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.anyio
async def test_trusted_header_provider_returns_none_when_header_missing():
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    cfg = TrustedHeaderProviderConfig(enabled=True, trusted_networks=["10.0.0.0/8"])
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request({}, "10.8.0.1")
    assert await provider.authenticate_request(req) is None


@pytest.mark.anyio
async def test_trusted_header_provider_ignores_bad_legacy_json():
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    cfg = TrustedHeaderProviderConfig(enabled=True, trusted_networks=["10.0.0.0/8"], legacy_user_id_headers=["x-user-info"])
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request({"x-user-info": "not-json"}, "10.8.0.1")
    assert await provider.authenticate_request(req) is None


@pytest.mark.anyio
async def test_trusted_header_provider_rejects_bad_hmac(monkeypatch):
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    monkeypatch.setenv("TRUSTED_HEADER_HMAC_SECRET", "secret-key")
    cfg = TrustedHeaderProviderConfig(
        enabled=True,
        trusted_networks=["10.0.0.0/8"],
        hmac_secret_env="TRUSTED_HEADER_HMAC_SECRET",
        hmac_signature_header="X-Forwarded-User-Signature",
    )
    provider = TrustedHeaderAuthProvider(repo, cfg)

    req = _Request(
        {
            "X-Forwarded-User": str(user.id),
            "X-Forwarded-User-Signature": "bad-signature",
        },
        "10.2.3.4",
    )
    assert await provider.authenticate_request(req) is None


@pytest.mark.anyio
async def test_trusted_header_provider_accepts_valid_hmac(monkeypatch):
    user = User(id=uuid4(), email="alice@test.com", password_hash="x")
    repo = _Repo({str(user.id): user})
    monkeypatch.setenv("TRUSTED_HEADER_HMAC_SECRET", "secret-key")
    cfg = TrustedHeaderProviderConfig(
        enabled=True,
        trusted_networks=["10.0.0.0/8"],
        hmac_secret_env="TRUSTED_HEADER_HMAC_SECRET",
        hmac_signature_header="X-Forwarded-User-Signature",
    )
    provider = TrustedHeaderAuthProvider(repo, cfg)
    signature = hmac.new(b"secret-key", str(user.id).encode("utf-8"), "sha256").hexdigest()

    req = _Request(
        {
            "X-Forwarded-User": str(user.id),
            "X-Forwarded-User-Signature": signature,
        },
        "10.2.3.4",
    )
    resolved = await provider.authenticate_request(req)
    assert resolved is not None
    assert resolved.id == user.id
