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


def test_concurrent_first_use_agrees_on_one_pepper(monkeypatch, tmp_path):
    """Multi-worker cold start: O_EXCL winner/loser protocol — every worker
    must cache the same pepper, not the candidate it generated itself."""
    import threading

    from app.gateway.shares.tokens import _load_or_create_pepper

    base = tmp_path / "home"
    monkeypatch.delenv("SHARE_TOKEN_PEPPER", raising=False)
    monkeypatch.setattr(
        "deerflow.config.paths.get_paths",
        lambda: type("P", (), {"base_dir": base})(),
    )

    barrier = threading.Barrier(8)
    results: list[str] = []

    def worker():
        barrier.wait()  # maximize the window where all see the file absent
        results.append(_load_or_create_pepper())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(results)) == 1, f"workers cached different peppers: {set(results)}"
    assert (base / ".share_token_pepper").read_text(encoding="utf-8").strip() == results[0]


def test_crashed_creator_leaves_recoverable_failure(monkeypatch, tmp_path):
    """An empty pepper file (creator died mid-write) fails loudly with
    operator remediation instead of silently regenerating a second pepper."""
    import pytest

    from app.gateway.shares.tokens import _load_or_create_pepper

    base = tmp_path / "home"
    base.mkdir()
    (base / ".share_token_pepper").write_text("", encoding="utf-8")
    monkeypatch.delenv("SHARE_TOKEN_PEPPER", raising=False)
    monkeypatch.setattr(
        "deerflow.config.paths.get_paths",
        lambda: type("P", (), {"base_dir": base})(),
    )
    # Keep the failure fast instead of waiting out the full retry window.
    monkeypatch.setattr("app.gateway.shares.tokens._PEPPER_READ_RETRIES", 2)
    monkeypatch.setattr("app.gateway.shares.tokens._PEPPER_READ_RETRY_DELAY_SECONDS", 0.0)

    with pytest.raises(RuntimeError, match="unreadable or empty"):
        _load_or_create_pepper()
