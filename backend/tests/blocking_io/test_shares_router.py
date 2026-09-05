"""Regression anchor: share-token pepper cold initialization stays off-loop.

The create and anonymous resolve handlers both need the process-wide share
pepper.  On first use that lookup may create/read a local secret file and, for
a concurrent loser, retry with ``time.sleep``.  This test drives both real
handlers under the strict Blockbuster gate with the cache empty.  Removing the
production thread offload makes the real filesystem access fail the test.

Imports stay at module scope so collection-time framework work runs outside the
strict per-test gate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Response

from app.gateway.routers import shares as shares_router
from app.gateway.routers.shares import ShareCreateRequest, create_share, get_public_share
from app.gateway.shares.tokens import set_share_pepper

pytestmark = pytest.mark.asyncio

_THREAD_ID = "share-blocking-io-thread"
_USER_ID = "share-blocking-io-user"
_SNAPSHOT = {
    "version": 1,
    "messages": [{"id": "m1", "role": "user", "content": "hello"}],
}


class _ThreadStore:
    async def get(self, thread_id: str, *, user_id=None):
        assert thread_id == _THREAD_ID
        assert user_id is None
        return {"user_id": _USER_ID}


class _ShareRepo:
    def __init__(self) -> None:
        self.record: dict | None = None

    async def create(self, **values):
        self.record = {
            "id": "share-blocking-io-id",
            "title": values["title"],
            "token_hash": values["token_hash"],
            "snapshot_json": values["snapshot_json"],
            "snapshot_version": values["snapshot_version"],
            "expires_at": values["expires_at"],
            "revoked_at": None,
            "created_at": datetime.now(UTC),
        }
        return self.record

    async def get_active_by_token_hash(self, token_hash: str):
        if self.record is None or self.record["token_hash"] != token_hash:
            return None
        return self.record


def _request(repo: _ShareRepo):
    return SimpleNamespace(
        _deerflow_test_bypass_auth=True,
        app=SimpleNamespace(state=SimpleNamespace(share_repo=repo)),
    )


async def test_create_and_public_resolve_cold_pepper_do_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "home"
    pepper_file = base_dir / ".share_token_pepper"
    repo = _ShareRepo()
    request = _request(repo)

    monkeypatch.delenv("SHARE_TOKEN_PEPPER", raising=False)
    monkeypatch.setattr(
        "deerflow.config.paths.get_paths",
        lambda: SimpleNamespace(base_dir=base_dir),
    )
    monkeypatch.setattr(
        shares_router,
        "_sharing_config",
        lambda: SimpleNamespace(
            enabled=True,
            allow_no_expiry=True,
            default_expiry_days=30,
        ),
    )

    async def _current_user(_request):
        return _USER_ID

    async def _snapshot(*_args, **_kwargs):
        return _SNAPSHOT, None

    monkeypatch.setattr(shares_router, "get_current_user", _current_user)
    monkeypatch.setattr(shares_router, "build_share_snapshot", _snapshot)
    monkeypatch.setattr(shares_router, "get_client_ip", lambda _request: "198.51.100.10")
    monkeypatch.setattr("app.gateway.deps.get_thread_store", lambda _request: _ThreadStore())
    shares_router._public_resolve_hits.clear()
    set_share_pepper(None)

    try:
        created = await create_share(
            _THREAD_ID,
            request=request,
            body=ShareCreateRequest(
                never_expires=True,
                title="Blocking IO anchor",
            ),
        )
        persisted_pepper = await asyncio.to_thread(
            pepper_file.read_text,
            encoding="utf-8",
        )
        assert len(persisted_pepper) == 43

        # Force the public handler through the real file-read cold path too;
        # it must resolve the token using the same persisted pepper.
        set_share_pepper(None)
        token = created.share_url.rsplit("/", maxsplit=1)[-1]
        public = await get_public_share(
            token,
            request=request,
            response=Response(),
        )
        assert public.snapshot == _SNAPSHOT
    finally:
        set_share_pepper(None)
        shares_router._public_resolve_hits.clear()
