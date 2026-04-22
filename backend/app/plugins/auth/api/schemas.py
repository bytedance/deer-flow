"""HTTP schemas and request helpers for the auth plugin API."""

from __future__ import annotations

import os
import time
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty12",
        "qwertyui",
        "qwerty123",
        "abc12345",
        "abcd1234",
        "iloveyou",
        "letmein1",
        "welcome1",
        "welcome123",
        "admin123",
        "administrator",
        "passw0rd",
        "p@ssw0rd",
        "monkey12",
        "trustno1",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "batman123",
        "starwars",
        "dragon123",
        "master123",
        "shadow12",
        "michael1",
        "jennifer",
        "computer",
    }
)
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300
_MAX_TRACKED_IPS = 10000
_login_attempts: dict[str, tuple[int, float]] = {}


class LoginResponse(BaseModel):
    expires_in: int
    needs_setup: bool = False


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    new_email: EmailStr | None = None

    _strong_password = field_validator("new_password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class MessageResponse(BaseModel):
    message: str


class InitializeAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


def _password_is_common(password: str) -> bool:
    return password.lower() in _COMMON_PASSWORDS


def _validate_strong_password(value: str) -> str:
    if _password_is_common(value):
        raise ValueError("Password is too common; choose a stronger password.")
    return value


def _trusted_proxies() -> list:
    raw = os.getenv("AUTH_TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    nets = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ip_network(entry, strict=False))
        except ValueError:
            pass
    return nets


def _get_client_ip(request: Request) -> str:
    peer_host = request.client.host if request.client else None
    trusted = _trusted_proxies()
    if trusted and peer_host:
        try:
            peer_ip = ip_address(peer_host)
            if any(peer_ip in net for net in trusted):
                real_ip = request.headers.get("x-real-ip", "").strip()
                if real_ip:
                    return real_ip
        except ValueError:
            pass
    return peer_host or "unknown"


def _check_rate_limit(ip: str) -> None:
    record = _login_attempts.get(ip)
    if record is None:
        return
    fail_count, lock_until = record
    if fail_count >= _MAX_LOGIN_ATTEMPTS:
        if time.time() < lock_until:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
        del _login_attempts[ip]


def _record_login_failure(ip: str) -> None:
    if len(_login_attempts) >= _MAX_TRACKED_IPS:
        now = time.time()
        expired = [k for k, (c, t) in _login_attempts.items() if c >= _MAX_LOGIN_ATTEMPTS and now >= t]
        for key in expired:
            del _login_attempts[key]
        if len(_login_attempts) >= _MAX_TRACKED_IPS:
            by_time = sorted(_login_attempts.items(), key=lambda kv: kv[1][1])
            for key, _ in by_time[: len(by_time) // 2]:
                del _login_attempts[key]

    record = _login_attempts.get(ip)
    if record is None:
        _login_attempts[ip] = (1, 0.0)
    else:
        new_count = record[0] + 1
        lock_until = time.time() + _LOCKOUT_SECONDS if new_count >= _MAX_LOGIN_ATTEMPTS else 0.0
        _login_attempts[ip] = (new_count, lock_until)


def _record_login_success(ip: str) -> None:
    _login_attempts.pop(ip, None)


__all__ = [
    "ChangePasswordRequest",
    "InitializeAdminRequest",
    "LoginResponse",
    "MessageResponse",
    "RegisterRequest",
    "_check_rate_limit",
    "_get_client_ip",
    "_login_attempts",
    "_record_login_failure",
    "_record_login_success",
]
