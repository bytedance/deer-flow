"""Authentication module for DeerFlow.

This module provides:
- JWT-based authentication
- Provider Factory pattern for extensible auth methods
- UserRepository interface for storage backends (SQLite)
"""

from app.gateway.auth.config import AuthConfig, get_auth_config, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import TokenPayload, create_access_token, decode_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User, UserResponse
from app.gateway.auth.password import hash_password, verify_password
from app.gateway.auth.providers import AuthProvider
from app.gateway.auth.repositories.base import UserRepository

__all__ = [
    # Config
    "AuthConfig",
    "get_auth_config",
    "set_auth_config",
    # Errors
    "AuthErrorCode",
    "AuthErrorResponse",
    "TokenError",
    # JWT
    "TokenPayload",
    "create_access_token",
    "decode_token",
    # Password
    "hash_password",
    "verify_password",
    # Models
    "User",
    "UserResponse",
    # Providers
    "AuthProvider",
    "LocalAuthProvider",
    # Repository
    "UserRepository",
]
