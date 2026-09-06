from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCError, OIDCIdentity, OIDCMetadata, OIDCService, OIDCValidationError
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from deerflow.config.auth_config import OIDCProviderConfig


def _provider_config(**overrides):
    return OIDCProviderConfig(
        display_name="Test SSO",
        issuer="https://issuer.example.com",
        client_id="deer-flow",
        **overrides,
    )


def _identity(**overrides):
    values = {
        "provider": "keycloak",
        "subject": "oidc-subject",
        "email": "user@example.com",
        "email_verified": True,
        "name": "Test User",
        "claims": {},
    }
    values.update(overrides)
    return OIDCIdentity(**values)


@pytest.mark.asyncio
async def test_oidc_existing_local_account_blocks_sso_login_even_when_unverified():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(
                require_verified_email=False,
                auto_create_users=False,
            ),
            identity=_identity(email_verified=False),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.update_user.assert_not_called()


@pytest.mark.asyncio
async def test_oidc_existing_local_account_blocks_sso_login_even_when_verified():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(auto_create_users=False),
            identity=_identity(subject="verified-subject"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.update_user.assert_not_called()
    local_provider.create_oauth_user.assert_not_called()


@pytest.mark.asyncio
async def test_oidc_auto_create_assigns_admin_role_from_configured_email():
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    created_user = User(
        email="admin@example.com",
        password_hash=None,
        system_role="admin",
        oauth_provider="keycloak",
        oauth_id="admin-subject",
    )
    local_provider.create_oauth_user.return_value = created_user

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(admin_emails=["ADMIN@example.com"]),
        identity=_identity(subject="admin-subject", email="admin@example.com"),
        local_provider=local_provider,
    )

    assert result == {"user": created_user, "created": True}
    local_provider.create_oauth_user.assert_awaited_once_with(
        email="admin@example.com",
        oauth_provider="keycloak",
        oauth_id="admin-subject",
        system_role="admin",
    )


@pytest.mark.asyncio
async def test_oidc_validate_id_token_refreshes_jwks_once_on_kid_miss(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )
    load_calls = []
    resolve_results = [None, "signing-key"]

    async def load_jwks(jwks_uri, force_refresh=False):
        load_calls.append(force_refresh)
        return {"keys": []}

    async def resolve_signing_key(jwks_data, kid, algorithm, jwks_uri):
        return resolve_results.pop(0)

    monkeypatch.setattr(service, "_load_jwks", load_jwks)
    monkeypatch.setattr(service, "_resolve_signing_key", resolve_signing_key)
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.get_unverified_header", lambda token: {"kid": "new-kid", "alg": "RS256"})
    monkeypatch.setattr(
        "app.gateway.auth.oidc.jwt.decode",
        lambda *args, **kwargs: {"iss": metadata.issuer, "sub": "subject", "aud": "deer-flow", "exp": 9999999999},
    )

    claims = await service.validate_id_token(metadata, "deer-flow", "id-token")

    assert claims["sub"] == "subject"
    assert load_calls == [False, True]
    await service.close()


@pytest.mark.asyncio
async def test_oidc_validate_id_token_rejects_hmac_algorithms(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )

    async def load_jwks(jwks_uri, force_refresh=False):
        return {"keys": [{"kid": "kid", "kty": "oct", "k": "secret"}]}

    async def resolve_signing_key(jwks_data, kid, algorithm, jwks_uri):
        return "secret"

    def decode(*args, **kwargs):
        assert "HS256" not in kwargs["algorithms"]
        raise OIDCValidationError("HMAC algorithms must not be accepted")

    monkeypatch.setattr(service, "_load_jwks", load_jwks)
    monkeypatch.setattr(service, "_resolve_signing_key", resolve_signing_key)
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.get_unverified_header", lambda token: {"kid": "kid", "alg": "HS256"})
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.decode", decode)

    with pytest.raises(OIDCValidationError, match="unsupported algorithm"):
        await service.validate_id_token(metadata, "deer-flow", "id-token")

    await service.close()


@pytest.mark.asyncio
async def test_oidc_existing_account_lookup_uses_normalized_email():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(auto_create_users=False),
            identity=_identity(email="User@Example.COM"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.get_user_by_email.assert_awaited_once_with("user@example.com")


@pytest.mark.asyncio
async def test_oidc_auto_create_uses_normalized_email():
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    created_user = User(email="user@example.com", password_hash=None, oauth_provider="keycloak", oauth_id="subject")
    local_provider.create_oauth_user.return_value = created_user

    await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(),
        identity=_identity(subject="subject", email="User@Example.COM"),
        local_provider=local_provider,
    )

    local_provider.create_oauth_user.assert_awaited_once_with(
        email="user@example.com",
        oauth_provider="keycloak",
        oauth_id="subject",
        system_role="user",
    )


@pytest.mark.asyncio
async def test_oidc_metadata_from_dict_accepts_missing_overrides():
    service = OIDCService()

    metadata = service._metadata_from_dict(
        {
            "issuer": "https://issuer.example.com",
            "authorization_endpoint": "https://issuer.example.com/auth",
            "token_endpoint": "https://issuer.example.com/token",
            "userinfo_endpoint": "https://issuer.example.com/userinfo",
            "jwks_uri": "https://issuer.example.com/jwks",
        },
        None,
    )

    assert metadata.jwks_uri == "https://issuer.example.com/jwks"
    await service.close()


@pytest.mark.asyncio
async def test_oidc_authenticate_callback_treats_string_false_email_verified_as_unverified(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )

    async def exchange_code(**kwargs):
        return {"id_token": "id-token"}

    async def validate_id_token(**kwargs):
        return {"sub": "subject", "email": "user@example.com", "email_verified": "false"}

    monkeypatch.setattr(service, "exchange_code", exchange_code)
    monkeypatch.setattr(service, "validate_id_token", validate_id_token)

    identity = await service.authenticate_callback(
        provider_id="keycloak",
        metadata=metadata,
        client_id="deer-flow",
        client_secret=None,
        code="code",
        redirect_uri="https://app.example.com/callback",
    )

    assert identity.email_verified is False
    await service.close()


@pytest.mark.asyncio
async def test_oidc_provision_recovers_existing_user_on_create_race():
    """A concurrent create that loses the unique index re-resolves to the winner's row."""
    created_user = User(email="user@example.com", password_hash=None, oauth_provider="keycloak", oauth_id="subject")
    local_provider = AsyncMock()
    # First lookup (by oauth) misses, then create races and raises, then re-lookup wins.
    local_provider.get_user_by_oauth.side_effect = [None, created_user]
    local_provider.get_user_by_email.return_value = None
    local_provider.create_oauth_user.side_effect = ValueError("Email already registered: user@example.com")

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(),
        identity=_identity(subject="subject"),
        local_provider=local_provider,
    )

    assert result == {"user": created_user, "created": False}
    assert local_provider.get_user_by_oauth.await_count == 2


@pytest.mark.asyncio
async def test_oidc_provision_create_race_on_email_only_raises_409():
    """A create race that collides on email (different identity) surfaces a clean 409, not a 500."""
    local_provider = AsyncMock()
    # No existing oauth link before or after the race (email collision, not same subject).
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    local_provider.create_oauth_user.side_effect = ValueError("Email already registered: user@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(),
            identity=_identity(subject="subject"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_oidc_discover_rejects_mismatched_issuer(monkeypatch):
    service = OIDCService()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "issuer": "https://evil.example.com",
                "authorization_endpoint": "https://issuer.example.com/auth",
                "token_endpoint": "https://issuer.example.com/token",
                "jwks_uri": "https://issuer.example.com/jwks",
            }

    async def fake_get(url):
        return _Resp()

    monkeypatch.setattr(service._http, "get", fake_get)

    with pytest.raises(OIDCError, match="does not match configured issuer"):
        await service.discover("https://issuer.example.com")

    await service.close()


@pytest.mark.asyncio
async def test_oidc_discover_accepts_issuer_with_trailing_slash_difference(monkeypatch):
    service = OIDCService()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "issuer": "https://issuer.example.com/",
                "authorization_endpoint": "https://issuer.example.com/auth",
                "token_endpoint": "https://issuer.example.com/token",
                "jwks_uri": "https://issuer.example.com/jwks",
            }

    async def fake_get(url):
        return _Resp()

    monkeypatch.setattr(service._http, "get", fake_get)

    metadata = await service.discover("https://issuer.example.com")

    assert metadata.issuer == "https://issuer.example.com/"
    await service.close()


def _redirect_request(headers: dict, scheme: str = "http", netloc: str = "localhost:8001"):
    from unittest.mock import MagicMock

    req = MagicMock()
    req.headers = headers
    req.url.scheme = scheme
    req.url.netloc = netloc
    return req


def test_oidc_redirect_uri_prefers_configured_value():
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config(redirect_uri="https://app.example.com/api/v1/auth/callback/keycloak")
    req = _redirect_request({"host": "attacker.example.com"})

    assert _resolve_oidc_redirect_uri(req, "keycloak", cfg) == "https://app.example.com/api/v1/auth/callback/keycloak"


def test_oidc_redirect_uri_fallback_uses_forwarded_headers_not_raw_host():
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config()
    # Raw Host is attacker-controlled; proxy-set X-Forwarded-* must win.
    req = _redirect_request(
        {
            "host": "attacker.example.com",
            "x-forwarded-host": "app.example.com",
            "x-forwarded-proto": "https",
        }
    )

    result = _resolve_oidc_redirect_uri(req, "keycloak", cfg)

    assert result == "https://app.example.com/api/v1/auth/callback/keycloak"


def test_oidc_redirect_uri_fallback_plain_host_when_no_proxy_headers():
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config()
    req = _redirect_request({"host": "localhost:8001"})

    result = _resolve_oidc_redirect_uri(req, "keycloak", cfg)

    assert result == "http://localhost:8001/api/v1/auth/callback/keycloak"
