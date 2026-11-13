"""Regression anchors: minting a GitHub App installation token must not read the key on the loop.

``mint_installation_token`` runs on the channel manager's event loop for every
GitHub delivery whose cached token is missing or near expiry. Building the App
JWT reads ``GITHUB_APP_PRIVATE_KEY_PATH`` and signs with the key, so the async
mint does that in a worker thread.

The key lives in a real file and the anchors verify the JWT GitHub receives
against it, so an anchor cannot pass because the key was never read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import httpx
import jwt
import pytest
from blockbuster import BlockingError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.github import app_auth

pytestmark = pytest.mark.asyncio

_APP_ID = "123456"


def _write_key(path: Path) -> rsa.RSAPublicKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key.public_key()


@pytest.fixture
def key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, rsa.RSAPublicKey]]:
    path = tmp_path / "github-app.pem"
    # Runs before the async test body, still outside any event loop.
    public_key = _write_key(path)
    monkeypatch.setenv("GITHUB_APP_ID", _APP_ID)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(path))
    app_auth._clear_token_cache_for_tests()
    yield path, public_key
    app_auth._clear_token_cache_for_tests()


def _github(seen_jwts: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_jwts.append(request.headers["Authorization"].removeprefix("Bearer "))
        return httpx.Response(201, json={"token": f"ghs_{len(seen_jwts)}", "expires_at": "2099-01-01T00:00:00Z"})

    return httpx.MockTransport(handler)


async def test_cold_mint_reads_the_private_key_off_the_loop(key_file) -> None:
    _, public_key = key_file
    seen_jwts: list[str] = []
    async with httpx.AsyncClient(transport=_github(seen_jwts)) as client:
        token = await app_auth.mint_installation_token(42, client=client)

    assert token == "ghs_1"
    [app_jwt] = seen_jwts
    assert jwt.decode(app_jwt, public_key, algorithms=["RS256"])["iss"] == _APP_ID


async def test_refresh_reads_a_rotated_key_off_the_loop(key_file) -> None:
    path, first_public_key = key_file
    seen_jwts: list[str] = []
    async with httpx.AsyncClient(transport=_github(seen_jwts)) as client:
        await app_auth.mint_installation_token(42, client=client)
        rotated_public_key = await asyncio.to_thread(_write_key, path)
        token = await app_auth.mint_installation_token(42, client=client, force_refresh=True)

    assert token == "ghs_2"
    jwt.decode(seen_jwts[0], first_public_key, algorithms=["RS256"])
    # The refresh signs with the key now on disk, not the one parsed first.
    jwt.decode(seen_jwts[1], rotated_public_key, algorithms=["RS256"])
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(seen_jwts[1], first_public_key, algorithms=["RS256"])


async def test_blocking_probe_inline_app_jwt_actually_trips_the_gate(key_file) -> None:
    """Meta-check: building the App JWT inline on the loop is caught by the gate."""
    with pytest.raises(BlockingError):
        app_auth.mint_app_jwt()
