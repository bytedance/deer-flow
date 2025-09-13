# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import jwt
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Any, Optional
from fastapi import HTTPException, Depends, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY environment variable is required. Set a secure random secret key.")
ALGORITHM = "HS256"

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

if not validate_secret_key(SECRET_KEY):
    raise ValueError("JWT_SECRET_KEY must be at least 32 characters and contain uppercase, lowercase, digits, and special characters.")

security = HTTPBearer()

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
    """Validate CSRF token against session or header"""
    # For state-changing operations, validate CSRF token
    # In production, you might store this in session or validate against user session
    expected_token = request.headers.get("X-CSRF-Token") or request.cookies.get("csrf_token")
    return secrets.compare_digest(csrf_token, expected_token) if expected_token else False

def csrf_protected(request: Request = None):
    """Decorator for CSRF protection on state-changing operations"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            if request and request.method in ["POST", "PUT", "DELETE", "PATCH"]:
                csrf_token = request.headers.get("X-CSRF-Token")
                if not csrf_token or not validate_csrf_token(request, csrf_token):
                    raise HTTPException(status_code=403, detail="CSRF token validation failed")
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def verify_token(token: str) -> dict:
    """Verify JWT token with enhanced error handling"""
    try:
        import jwt
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Additional validation
        if not all(key in payload for key in ["sub", "email", "role"]):
            return {}
            
        return payload
    except jwt.ExpiredSignatureError:
        return {}
    except jwt.InvalidTokenError:
        return {}
    except Exception as e:
        logger.warning(f"Token verification error: {e}")
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
    """Authenticate user - in production, check against database"""
    # This is a simple mock implementation
    # In production, you would check against a database
    if email and password:
        # Simple role assignment based on email for demo
        role = "admin" if "admin" in email else "user"
        return {
            "id": f"user_{email}",
            "email": email,
            "name": email.split("@")[0],
            "role": role
        }
    return {}