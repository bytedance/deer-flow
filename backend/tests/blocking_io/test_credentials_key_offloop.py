"""Regression anchor: the Gateway loads the credentials key off the event loop.

``app.gateway.app._load_credentials_cipher`` runs inside the lifespan. Without
``DEER_FLOW_CREDENTIALS_KEY`` it creates ``{base_dir}/.credentials_key`` (mkdir,
exclusive create, fsync, read-back), all of which must go through
``asyncio.to_thread``; the strict Blockbuster gate fails this test otherwise.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

# Imported at collection time: importing the Gateway app reads package
# metadata, which is not the startup path under test.
from app.gateway.app import _load_credentials_cipher
from deerflow.config.credentials_key import CREDENTIALS_KEY_ENV_VAR, CREDENTIALS_KEY_FILENAME, reset_credentials_cipher
from deerflow.config.paths import Paths

pytestmark = pytest.mark.asyncio


async def test_credentials_key_generation_does_not_block_the_event_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "missing" / "home"
    monkeypatch.delenv(CREDENTIALS_KEY_ENV_VAR, raising=False)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=home))
    reset_credentials_cipher()
    try:
        cipher = await _load_credentials_cipher(SimpleNamespace(channel_connections=SimpleNamespace(enabled=True)))
    finally:
        reset_credentials_cipher()

    assert cipher is not None
    assert (home / CREDENTIALS_KEY_FILENAME).exists()
