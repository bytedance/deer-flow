# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import jwt
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

# Check if we're in a test environment
def is_test_environment() -> bool:
    """Check if we're running in a test environment"""
    import sys
    
    # Check if pytest is in the command line arguments
    is_pytest_running = any('pytest' in arg for arg in sys.argv)
    
    return (
        is_pytest_running or
        os.getenv("PYTEST_CURRENT_TEST") is not None or  # pytest is running
        os.getenv("TESTING") == "true" or  # explicit test flag
        os.getenv("APP_ENV") == "test"  # test environment
    )

# Validate secret key complexity
def validate_secret_key(key: str) -> bool:
    """Validate that the secret key meets security requirements"""
    if len(key) < 32:
        return False
    # Check for basic complexity - should contain mix of character types
    has_upper = any(c.isupper() for c in key)
    has_lower = any(c.islower() for c in key)
    has_digit = any(c.isdigit() for c in key)
    has_special = any(not c.isalnum() for c in key)
    return has_upper and has_lower and has_digit and has_special

# Set up JWT secret key with fallback for test environments
if not SECRET_KEY:
    if is_test_environment():
        # Use a test-only secret key in test environments
        SECRET_KEY = "test-secret-key-for-development-only-do-not-use-in-production-123!@#ABC"
        logger.warning("Using test JWT secret key. This should only be used in test environments.")
    else:
        raise ValueError("JWT_SECRET_KEY environment variable is required. Set a secure random secret key.")
elif not validate_secret_key(SECRET_KEY):
    if is_test_environment():
        logger.warning("JWT secret key does not meet complexity requirements. Using in test environment only.")
    else:
        raise ValueError("JWT_SECRET_KEY must be at least 32 characters and contain uppercase, lowercase, digits, and special characters.")

security = HTTPBearer()

# In-memory token blacklist for invalidated (logged-out) tokens.
# NOTE: For production deployments with multiple workers/processes, replace
# this with a shared store such as Redis.
_token_blacklist: set[str] = set()
_blacklist_expiry: dict[str, datetime] = {}


def add_token_to_blacklist(token: str) -> None:
    """Invalidate a token by adding it to the blacklist.

    The token's own expiry claim is used so that the blacklist entry is
    automatically cleaned up once the token would have expired anyway.
    """
    _cleanup_expired_blacklist_entries()
    _token_blacklist.add(token)
    # Try to extract the token's expiry so we can auto-purge later
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp")
        if exp:
            _blacklist_expiry[token] = datetime.fromtimestamp(exp, tz=timezone.utc)
        else:
            _blacklist_expiry[token] = datetime.now(timezone.utc) + timedelta(hours=24)
    except Exception:
        # If decoding fails, default to 24 h
        _blacklist_expiry[token] = datetime.now(timezone.utc) + timedelta(hours=24)


def is_token_blacklisted(token: str) -> bool:
    """Return True if the token has been blacklisted (i.e. logged out)."""
    return token in _token_blacklist


def _cleanup_expired_blacklist_entries() -> None:
    """Remove expired entries from the blacklist to prevent unbounded growth."""
    now = datetime.now(timezone.utc)
    expired = [t for t, exp in _blacklist_expiry.items() if exp < now]
    for t in expired:
        _token_blacklist.discard(t)
        _blacklist_expiry.pop(t, None)


def clear_token_blacklist() -> None:
    """Clear the entire blacklist (intended for tests)."""
    _token_blacklist.clear()
    _blacklist_expiry.clear()


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Create JWT token with configurable expiration"""
    to_encode = data.copy()
    
    # Use provided expiration or default to 24 hours
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=24)
    
    to_encode.update({
        "exp": expire,
        "iat": now  # Issued at time
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def generate_csrf_token() -> str:
    """Generate a secure CSRF token"""
    return secrets.token_urlsafe(32)

def validate_csrf_token(request: Request, csrf_token: str) -> bool:
    """Validate CSRF token sent in header against CSRF cookie"""
    # For state-changing operations, validate CSRF token using a double-submit
    # pattern: compare the value in the X-CSRF-Token header to the value stored
    # in the csrf_token cookie that the server previously set.
    expected_token = request.cookies.get("csrf_token")
    if not expected_token:
        logger.warning("CSRF token cookie is missing during CSRF validation")
        return False
    return secrets.compare_digest(csrf_token, expected_token)


def verify_token(token: str) -> dict:
    """Verify JWT token with enhanced error handling"""
    # Reject tokens that have been explicitly invalidated (logged out)
    if is_token_blacklisted(token):
        logger.info("Token verification failed: token has been blacklisted")
        return {}

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Additional validation
        if not all(key in payload for key in ["sub", "email", "role"]):
            return {}

        return payload
    except jwt.ExpiredSignatureError:
        logger.info("Token verification failed: expired signature")
        return {}
    except jwt.InvalidTokenError:
        logger.info("Token verification failed: invalid token")
        return {}

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from token"""
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

def require_admin_user(current_user: dict = Depends(get_current_user)):
    """Require admin role"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return current_user

def authenticate_user(email: str, password: str) -> dict:
    """Authenticate user by verifying credentials against users.yaml"""
    from src.config.users import verify_user_credentials
    
    user = verify_user_credentials(email, password)
    if not user:
        return {}
    
    return user