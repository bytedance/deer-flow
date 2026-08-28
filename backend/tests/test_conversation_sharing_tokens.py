"""Tests for conversation share token utilities and pepper lifecycle (#4548)."""

from __future__ import annotations

import os
import stat

import pytest

from app.gateway.shares.tokens import (
    SHARE_TOKEN_PREFIX,
    generate_share_token,
    get_share_pepper,
    set_share_pepper,
    share_token_hash,
)


@pytest.fixture(autouse=True)
def _reset_pepper():
    set_share_pepper(None)
    yield
    set_share_pepper(None)


def test_generate_share_token_format():
    token = generate_share_token()
    assert token.startswith(SHARE_TOKEN_PREFIX)
    body = token[len(SHARE_TOKEN_PREFIX) :]
    assert len(body) >= 40  # urlsafe(32 bytes) ≈ 43 chars of entropy
    assert token != generate_share_token()  # CSPRNG, not a counter


def test_share_token_hash_is_deterministic_and_pepper_keyed():
    token = generate_share_token()
    digest = share_token_hash(token, "pepper-a")
    assert digest == share_token_hash(token, "pepper-a")
    assert len(digest) == 64  # hex SHA-256
    # A different pepper yields a different digest — pepper rotation
    # invalidates every outstanding token, by design.
    assert digest != share_token_hash(token, "pepper-b")
    assert digest != share_token_hash(generate_share_token(), "pepper-a")


def test_get_share_pepper_prefers_environment(monkeypatch):
    monkeypatch.setenv("SHARE_TOKEN_PEPPER", "env-pepper")
    assert get_share_pepper() == "env-pepper"


def test_get_share_pepper_persists_generated_pepper_locally(monkeypatch, tmp_path):
    base = tmp_path / "home"
    monkeypatch.delenv("SHARE_TOKEN_PEPPER", raising=False)
    monkeypatch.setattr(
        "deerflow.config.paths.get_paths",
        lambda: type("P", (), {"base_dir": base})(),
    )

    first = get_share_pepper()
    assert first

    pepper_file = base / ".share_token_pepper"
    assert pepper_file.exists()
    # 0600 permissions — the pepper must not become group/world readable.
    mode = stat.S_IMODE(os.stat(pepper_file).st_mode)
    assert mode == 0o600

    # Re-resolving after a cache reset reuses the persisted value.
    set_share_pepper(None)
    assert get_share_pepper() == first
