"""Source inspect must keep ZIP, extraction, digest, and cleanup IO off-loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Request

from app.gateway import skill_source
from app.gateway.auth.models import User
from app.gateway.authz import AuthContext
from app.gateway.routers.skills import SkillSourceInspectRequest, inspect_skill_source
from deerflow.config.authorization_config import AuthorizationConfig

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_SKILL_MD = "---\nname: find-skills\ndescription: Find useful skills.\n---\n\n# Find skills\n"

pytestmark = pytest.mark.asyncio


def _request() -> Request:
    user = User(email="admin@example.com", password_hash="x", system_role="admin", id=uuid4())
    request = Request({"type": "http", "headers": [], "state": {}})
    request.state.user = user
    request.state.auth = AuthContext(user=user, permissions=["skills:manage"])
    return request


async def test_source_inspect_archive_work_does_not_block_event_loop(monkeypatch, tmp_path):
    """Drive the real route through a real local temporary .skill archive."""
    payload = {
        "id": "vercel-labs/skills/find-skills",
        "source": "vercel-labs/skills",
        "slug": "find-skills",
        "hash": None,
        "files": [
            {"path": "SKILL.md", "contents": _SKILL_MD},
            {"path": "references/guide.md", "contents": "# Guide\n"},
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    def _client(**kwargs):
        assert kwargs["trust_env"] is False
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(skill_source.httpx, "AsyncClient", _client)
    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    config = SimpleNamespace(skill_scan=SimpleNamespace(enabled=False), authorization=AuthorizationConfig(enabled=False))

    response = await inspect_skill_source(_request(), SkillSourceInspectRequest(source="vercel-labs/skills@find-skills"), config)

    assert response.file_count == 2
    assert len(response.snapshot_digest) == 64
    assert not await asyncio.to_thread(tmp_path.exists)
