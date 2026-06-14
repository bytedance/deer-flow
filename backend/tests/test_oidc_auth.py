from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity, OIDCMetadata, OIDCService, OIDCValidationError
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
async def test_oidc_email_linking_requires_verified_email_even_when_login_does_not():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(
                allow_email_linking=True,
                require_verified_email=False,
                auto_create_users=False,
            ),
            identity=_identity(email_verified=False),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 403
    local_provider.update_user.assert_not_called()


@pytest.mark.asyncio
async def test_oidc_email_linking_updates_existing_user_when_email_is_verified():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user
    local_provider.update_user.side_effect = lambda user: user

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(allow_email_linking=True, auto_create_users=False),
        identity=_identity(subject="verified-subject"),
        local_provider=local_provider,
    )

    assert result == {"user": local_user, "created": False}
    assert local_user.oauth_provider == "keycloak"
    assert local_user.oauth_id == "verified-subject"
    local_provider.update_user.assert_awaited_once_with(local_user)


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
async def test_oidc_email_linking_uses_normalized_email_for_lookup():
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user
    local_provider.update_user.side_effect = lambda user: user

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(allow_email_linking=True, auto_create_users=False),
        identity=_identity(email="User@Example.COM"),
        local_provider=local_provider,
    )

    assert result == {"user": local_user, "created": False}
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
