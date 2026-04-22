"""Domain layer for the auth plugin."""

from app.plugins.auth.domain.config import AuthConfig, load_auth_config_from_env
from app.plugins.auth.domain.errors import AuthErrorCode, AuthErrorResponse, TokenError, token_error_to_code
from app.plugins.auth.domain.jwt import TokenPayload, create_access_token, decode_token
from app.plugins.auth.domain.models import User, UserResponse
from app.plugins.auth.domain.password import hash_password, hash_password_async, verify_password, verify_password_async
from app.plugins.auth.domain.service import AuthService, AuthServiceError

__all__ = [
    "AuthConfig",
    "AuthErrorCode",
    "AuthErrorResponse",
    "AuthService",
    "AuthServiceError",
    "TokenError",
    "TokenPayload",
    "User",
    "UserResponse",
    "create_access_token",
    "decode_token",
    "hash_password",
    "hash_password_async",
    "load_auth_config_from_env",
    "token_error_to_code",
    "verify_password",
    "verify_password_async",
]
