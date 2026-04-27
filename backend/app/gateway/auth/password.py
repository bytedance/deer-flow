"""Password hashing utilities using bcrypt with SHA-256 pre-hashing.

Passwords are pre-hashed with SHA-256 before bcrypt to avoid silent
truncation at 72 bytes (bcrypt's internal limit). This ensures the
full password contributes to the hash regardless of length.
"""

import asyncio
import base64
import hashlib

import bcrypt


def _pre_hash(password: str) -> bytes:
    """Pre-hash password with SHA-256 to bypass bcrypt's 72-byte limit."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with SHA-256 pre-hashing."""
    return bcrypt.hashpw(_pre_hash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(_pre_hash(plain_password), hashed_password.encode("utf-8"))


async def hash_password_async(password: str) -> str:
    """Hash a password using bcrypt (non-blocking).

    Wraps the blocking bcrypt operation in a thread pool to avoid
    blocking the event loop during password hashing.
    """
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash (non-blocking).

    Wraps the blocking bcrypt operation in a thread pool to avoid
    blocking the event loop during password verification.
    """
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)
