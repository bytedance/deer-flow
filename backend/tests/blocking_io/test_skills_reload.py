"""Regression anchor: the admin skills reload endpoint must not block ASGI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.gateway.routers import skills as skills_router
from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

pytestmark = pytest.mark.asyncio


def _seed_skill(skills_root: Path) -> None:
    skill_dir = skills_root / "public" / "reload-anchor"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reload-anchor\ndescription: blocking IO regression anchor\n---\n# Reload anchor\n",
        encoding="utf-8",
    )


async def test_reload_skills_offloads_directory_scan(tmp_path: Path, monkeypatch) -> None:
    await asyncio.to_thread(_seed_skill, tmp_path)
    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(tmp_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(skills_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda **_kwargs: storage)

    response = await skills_router.reload_skills(request=None)

    assert response.success is True
    assert response.scope == "process"
