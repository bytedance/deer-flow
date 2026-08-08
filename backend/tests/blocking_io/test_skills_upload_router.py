"""Regression anchor: the skill upload route must offload temporary-file IO."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import Request, UploadFile

from app.gateway.routers import skills as skills_router

pytestmark = pytest.mark.asyncio


def _admin_request() -> Request:
    user = SimpleNamespace(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        system_role="admin",
    )
    return Request({"type": "http", "headers": [], "state": {"user": user}})


async def test_skill_upload_temp_file_io_does_not_block_event_loop(monkeypatch) -> None:
    archive_paths: list[Path] = []

    class _Storage:
        async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
            archive_paths.append(Path(archive_path))
            return {
                "success": True,
                "skill_name": "loop-skill",
                "message": "installed",
            }

    async def _refresh(_user_id: str) -> None:
        return None

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: _Storage())
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(
        skills_router,
        "refresh_user_skills_system_prompt_cache_async",
        _refresh,
    )

    response = await skills_router.upload_and_install_skill(
        _admin_request(),
        UploadFile(file=BytesIO(b"archive"), filename="loop-skill.skill"),
        SimpleNamespace(),
    )

    assert response.skill_name == "loop-skill"
    assert len(archive_paths) == 1
    assert not await asyncio.to_thread(archive_paths[0].exists)
