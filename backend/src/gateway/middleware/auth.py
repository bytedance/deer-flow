"""
JWT-based authentication middleware for DeerFlow multi-tenancy.

This module provides JWT authentication for Deer-Flow's multi-tenant mode.
When multi_tenant.enabled is false, authentication is optional and unauthenticated
requests use user_id="default".

Tokens include:
- sub: user_id (required)
- email: user email (optional)
- role: "admin" or "user" (default: "user")
- exp: expiration time (unix timestamp)
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

from src.gateway.middleware.auth_enums import JWTAlgorithm, UserRole

# Token configuration (can be overridden via config.yaml)
DEFAULT_SECRET_KEY = "change-this-secret-key-in-production"
DEFAULT_ALGORITHM = JWTAlgorithm.HS256
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


class TokenData(BaseModel):
    """JWT token payload data."""
    user_id: str
    email: str | None = None
    role: UserRole = UserRole.USER


class User(BaseModel):
    """User model for authentication."""
    user_id: str
    email: str
    hashed_password: str
    role: UserRole = UserRole.USER
    created_at: datetime
    quota_limits: dict | None = None


class AuthenticationError(HTTPException):
    """Authentication error with 401 status."""

    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


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

    import os
    from src.config.app_config import get_app_config

    config = get_app_config()
    secret = config.multi_tenant.jwt_secret
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
    algorithm: JWTAlgorithm = DEFAULT_ALGORITHM,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        data: Payload data to encode (should include 'sub' for user_id)
        secret_key: Secret key for signing (default: from config/env)
        algorithm: JWT algorithm (default: HS256)
        expires_delta: Token expiration time (default: 24 hours)

    Returns:
        Encoded JWT token string
    """
    if not JWT_AVAILABLE:
        raise RuntimeError("PyJWT is not installed. Install with: pip install pyjwt")

    if secret_key is None:
        secret_key = get_jwt_secret()

    to_encode = data.copy()
    if "exp" not in to_encode:
        from src.config.app_config import get_app_config
        config = get_app_config()
        expire_minutes = config.multi_tenant.token_expire_minutes
        expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
        to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret_key: str | None = None,
    algorithm: JWTAlgorithm = DEFAULT_ALGORITHM,
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
        return TokenData(user_id="default", email=None, role="user")

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
            role=payload.get("role", "user")
        )
    except jwt.PyJWTError as e:
        raise AuthenticationError(f"Invalid token: {str(e)}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    secret_key: str | None = None,
    algorithm: JWTAlgorithm = DEFAULT_ALGORITHM,
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
        AuthenticationError: If token is invalid or missing
    """
    if credentials is None:
        raise AuthenticationError("Authorization header required")

    if secret_key is None:
        secret_key = get_jwt_secret()

    return decode_access_token(credentials.credentials, secret_key, algorithm)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Security(HTTPBearer(auto_error=False)),
    secret_key: str | None = None,
    algorithm: JWTAlgorithm = DEFAULT_ALGORITHM,
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
    from src.config.app_config import get_app_config
    config = get_app_config()
    return TokenData(
        user_id=config.multi_tenant.default_user_id,
        email=None,
        role=UserRole.USER
    )


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with salt.

    This uses Python's built-in hashlib for PBKDF2 key derivation,
    which is more secure than plain SHA-256. For production use,
    consider using bcrypt or argon2 libraries which provide even
    better security against GPU/ASIC attacks.

    Args:
        password: Plain text password

    Returns:
        Hex encoded hash with salt (format: salt:hash)
    """
    import hashlib
    import os

    # Generate a random salt
    salt = os.urandom(32)

    # Use PBKDF2-HMAC-SHA256 with 100,000 iterations
    # This is a key derivation function designed to be slow
    # to prevent brute force attacks
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100000,  # iterations - OWASP recommends 120,000 for SHA-256 as of 2023
        dklen=32  # derived key length
    )

    # Return salt:hash format for storage
    return f"{salt.hex()}:{hash_bytes.hex()}"


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    Args:
        password: Plain text password
        hashed_password: Stored password hash (format: salt:hash)

    Returns:
        True if password matches hash
    """
    import hashlib

    try:
        # Split salt and hash
        salt_hex, hash_hex = hashed_password.split(':')
        salt = bytes.fromhex(salt_hex)
        stored_hash = bytes.fromhex(hash_hex)

        # Compute hash of provided password with the same salt
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,
            dklen=32
        )

        # Compare in constant time to prevent timing attacks
        return compare_digest(computed_hash, stored_hash)
    except (ValueError, AttributeError):
        return False


def compare_digest(a: bytes, b: bytes) -> bool:
    """Compare two byte strings in constant time.

    This prevents timing attacks that could reveal information
    about how much of the hashes matched.

    Args:
        a: First byte string
        b: Second byte string

    Returns:
        True if the strings are equal
    """
    import hmac

    return hmac.compare_digest(a, b)
