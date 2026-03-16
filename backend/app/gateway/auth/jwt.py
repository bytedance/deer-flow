"""JWT authentication utilities for DeerFlow multi-tenancy.

This module provides JWT token creation and validation for multi-tenant mode.
When multi_tenant.enabled is false, authentication is optional and unauthenticated
requests use user_id="default".

Tokens include:
- sub: user_id (required)
- email: user email (optional)
- role: "admin" or "user" (default: "user")
- exp: expiration time (unix timestamp)
"""

import os
from datetime import datetime, timedelta

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

from app.gateway.auth.models import AuthenticationError, TokenData, UserRole
from deerflow.config.multi_tenant_config import get_multi_tenant_config

# Token configuration defaults
DEFAULT_SECRET_KEY = "change-this-secret-key-in-production"
DEFAULT_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days (RFC-001 compliant)

security = HTTPBearer()

# JWT secret cache to avoid repeated config lookups
_jwt_secret_cache: str | None = None


def get_jwt_secret() -> str:
    """Get JWT secret key from config or environment variable (cached).

    Priority:
    1. config.yaml multi_tenant.jwt_secret
    2. DEER_FLOW_JWT_SECRET environment variable
    3. Default secret key (development only)

    Returns:
        JWT secret key
    """
    global _jwt_secret_cache
    if _jwt_secret_cache is not None:
        return _jwt_secret_cache

    config = get_multi_tenant_config()
    secret = config.jwt_secret
    if secret:
        _jwt_secret_cache = secret
        return secret

    secret = os.getenv("DEER_FLOW_JWT_SECRET")
    if secret:
        _jwt_secret_cache = secret
        return secret

    _jwt_secret_cache = DEFAULT_SECRET_KEY
    return DEFAULT_SECRET_KEY


def create_access_token(
    data: dict,
    secret_key: str | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        data: Payload data to encode (should include 'sub' for user_id)
        secret_key: Secret key for signing (default: from config/env)
        algorithm: JWT algorithm (default: HS256)
        expires_delta: Token expiration time (default: from config)

    Returns:
        Encoded JWT token string

    Raises:
        RuntimeError: If PyJWT is not installed
    """
    if not JWT_AVAILABLE:
        raise RuntimeError("PyJWT is not installed. Install with: uv add pyjwt")

    if secret_key is None:
        secret_key = get_jwt_secret()

    to_encode = data.copy()
    if "exp" not in to_encode:
        config = get_multi_tenant_config()
        expire_minutes = config.token_expire_minutes
        expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
        to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret_key: str | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
) -> TokenData:
    """Decode and validate a JWT access token.

    Args:
        token: JWT token string
        secret_key: Secret key for validation (default: from config/env)
        algorithm: JWT algorithm (default: HS256)

    Returns:
        TokenData with user information

    Raises:
        AuthenticationError: If token is invalid or missing required fields
    """
    if not JWT_AVAILABLE:
        # When JWT is not available, return default user for backward compatibility
        return TokenData(user_id="default", email=None, role=UserRole.USER)

    if secret_key is None:
        secret_key = get_jwt_secret()

    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise AuthenticationError("Invalid token: missing user_id")
        return TokenData(
            user_id=user_id,
            email=payload.get("email"),
            role=payload.get("role", UserRole.USER),
        )
    except jwt.PyJWTError as e:
        raise AuthenticationError(f"Invalid token: {str(e)}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    secret_key: str | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
) -> TokenData:
    """Extract and validate user from JWT token in Authorization header.

    This is a strict dependency that requires authentication.

    Args:
        credentials: HTTP Authorization credentials
        secret_key: Secret key for validation (default: from config/env)
        algorithm: JWT algorithm

    Returns:
        TokenData with user information

    Raises:
        HTTPException: If token is invalid or missing
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if secret_key is None:
        secret_key = get_jwt_secret()

    try:
        return decode_access_token(credentials.credentials, secret_key, algorithm)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Security(HTTPBearer(auto_error=False)),
    secret_key: str | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
) -> TokenData:
    """Optional authentication - returns default user if no token provided.

    This allows backward compatibility for single-tenant mode.

    Args:
        credentials: HTTP Authorization credentials (optional)
        secret_key: Secret key for validation (default: from config/env)
        algorithm: JWT algorithm

    Returns:
        TokenData with user information (default user if unauthenticated)
    """
    if credentials is None:
        return _get_default_user()

    if secret_key is None:
        secret_key = get_jwt_secret()

    try:
        return decode_access_token(credentials.credentials, secret_key, algorithm)
    except HTTPException:
        return _get_default_user()


def _get_default_user() -> TokenData:
    """Get the default user for unauthenticated requests.

    Returns:
        TokenData with default user information.
    """
    config = get_multi_tenant_config()
    return TokenData(
        user_id=config.default_user_id,
        email=None,
        role=UserRole.USER,
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with passlib.

    This uses bcrypt (via passlib) for secure password hashing,
    which is the industry standard for password storage and provides
    excellent security against GPU/ASIC attacks.

    Args:
        password: Plain text password

    Returns:
        Bcrypt hash string for storage
    """
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    Args:
        password: Plain text password
        hashed_password: Stored bcrypt hash

    Returns:
        True if password matches hash
    """
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(password, hashed_password)


def reset_jwt_secret_cache() -> None:
    """Reset the cached JWT secret key.

    This is useful when the configuration has been updated and you want
    to force reloading of the secret key.
    """
    global _jwt_secret_cache
    _jwt_secret_cache = None
