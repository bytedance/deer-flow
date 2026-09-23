"""Regression anchors: the login throttle must not block the event loop.

``_login_throttle_policy`` resolves the live policy via ``get_app_config()``,
which stats and re-hashes ``config.yaml`` on every call. ``login_local`` is an
unauthenticated async endpoint, and every request from a recorded IP resolves
the policy — including an already-locked attacker flooding the endpoint on
the way to its 429. Both resolution points (the rate-limit check and the
failure recorder) offload via ``asyncio.to_thread``; if either regresses onto
the event loop, the strict Blockbuster gate raises ``BlockingError``.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from starlette.requests import Request

from app.gateway.routers import auth as auth_router

pytestmark = pytest.mark.asyncio

_CLIENT_IP = "203.0.113.9"


@pytest.fixture(autouse=True)
def _throttle_state(monkeypatch):
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    auth_router._login_attempts.clear()
    yield
    auth_router._login_attempts.clear()


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login/local",
            "headers": [],
            "query_string": b"",
            "client": (_CLIENT_IP, 44000),
            "server": ("testserver", 80),
        }
    )


def _form() -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(username="user@example.com", password="wrong")


async def test_locked_ip_policy_resolution_does_not_block_loop() -> None:
    """A locked IP floods the endpoint: every request resolves the policy on
    the way to 429, and that resolution must stay off the event loop."""
    auth_router._login_attempts[_CLIENT_IP] = (9, time.time(), 3600.0)  # sentence running

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.login_local(_request(), Response(), _form(), remember_me=True)

    assert exc_info.value.status_code == 429


async def test_failed_login_recording_does_not_block_loop(monkeypatch) -> None:
    """The wrong-password path resolves the policy again inside the recorder;
    counting must happen without blocking IO on the loop."""

    class _Provider:
        async def authenticate(self, credentials):
            return None

    monkeypatch.setattr(auth_router, "get_local_provider", lambda: _Provider())
    auth_router._login_attempts[_CLIENT_IP] = (1, 0.0, 0.0)  # counting, not locked

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.login_local(_request(), Response(), _form(), remember_me=True)

    assert exc_info.value.status_code == 401
    assert auth_router._login_attempts[_CLIENT_IP][0] == 2
