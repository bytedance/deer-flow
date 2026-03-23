"""Authentication and authorization module for DeerFlow multi-tenancy."""

from app.gateway.auth.jwt import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_jwt_secret,
    get_optional_user,
    hash_password,
    reset_jwt_secret_cache,
    verify_password,
)
from app.gateway.auth.models import AuthenticationError, TokenData, User, UserRole

__all__ = [
    # Models
    "TokenData",
    "User",
    "UserRole",
    "AuthenticationError",
    # JWT functions
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_optional_user",
    "get_jwt_secret",
    "hash_password",
    "verify_password",
    "reset_jwt_secret_cache",
]
