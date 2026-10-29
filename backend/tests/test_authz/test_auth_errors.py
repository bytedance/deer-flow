"""Tests for auth error types and typed decode_token."""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import create_access_token, decode_token
from app.gateway.auth.oidc_state import _verify_state_signed


def test_auth_error_code_values():
    assert AuthErrorCode.INVALID_CREDENTIALS == "invalid_credentials"
    assert AuthErrorCode.TOKEN_EXPIRED == "token_expired"
    assert AuthErrorCode.NOT_AUTHENTICATED == "not_authenticated"


def test_token_error_values():
    assert TokenError.EXPIRED == "expired"
    assert TokenError.INVALID_SIGNATURE == "invalid_signature"
    assert TokenError.MALFORMED == "malformed"


def test_auth_error_response_serialization():
    err = AuthErrorResponse(
        code=AuthErrorCode.TOKEN_EXPIRED,
        message="Token has expired",
    )
    d = err.model_dump()
    assert d == {"code": "token_expired", "message": "Token has expired"}


def test_auth_error_response_from_dict():
    d = {"code": "invalid_credentials", "message": "Wrong password"}
    err = AuthErrorResponse(**d)
    assert err.code == AuthErrorCode.INVALID_CREDENTIALS


# ── decode_token typed failure tests ──────────────────────────────

_TEST_SECRET = "test-secret-for-jwt-decode-token-tests"


def _setup_config():
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


def test_decode_token_returns_token_error_on_expired():
    _setup_config()
    expired_payload = {"sub": "user-1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired_payload, _TEST_SECRET, algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.EXPIRED


def test_decode_token_returns_token_error_on_bad_signature():
    _setup_config()
    payload = {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.INVALID_SIGNATURE


def test_decode_token_returns_token_error_on_malformed():
    _setup_config()
    result = decode_token("not-a-jwt")
    assert result == TokenError.MALFORMED


def test_decode_token_returns_payload_on_valid():
    _setup_config()
    token = create_access_token("user-123")
    result = decode_token(token)
    assert not isinstance(result, TokenError)
    assert result.sub == "user-123"


def test_decode_token_returns_token_error_on_signed_token_with_wrong_claims():
    _setup_config()
    # The OIDC state cookie is signed with the same secret but has no sub/exp.
    state_payload = {"provider": "google", "state": "abc", "issued_at": 1}
    token = pyjwt.encode(state_payload, _TEST_SECRET, algorithm="HS256")

    assert decode_token(token) == TokenError.MALFORMED


def test_decode_token_prefers_expired_over_malformed():
    _setup_config()
    # jwt.decode raises ExpiredSignatureError before TokenPayload(**payload) runs, so a token that is
    # both expired and missing `sub` must keep reporting EXPIRED.
    expired_without_sub = {"provider": "x", "exp": datetime.now(UTC) - timedelta(hours=1)}
    token = pyjwt.encode(expired_without_sub, _TEST_SECRET, algorithm="HS256")
    assert decode_token(token) == TokenError.EXPIRED


def test_verify_state_signed_rejects_signed_payload_with_bad_claims():
    _setup_config()
    # A cookie signed with our secret but missing required claims used to raise ValidationError out of
    # the public callback endpoint; it has to be treated like any other unusable state.
    signed = pyjwt.encode({"not_provider": "x"}, _TEST_SECRET, algorithm="HS256")
    assert _verify_state_signed(signed) is None


def test_verify_state_signed_accepts_a_valid_state():
    _setup_config()
    now = datetime.now(UTC).timestamp()
    signed = pyjwt.encode({"provider": "google", "state": "abc", "issued_at": now}, _TEST_SECRET, algorithm="HS256")
    payload = _verify_state_signed(signed)
    assert payload is not None
    assert payload.provider == "google"
