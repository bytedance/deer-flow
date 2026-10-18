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
    monkeypatch.setattr(prompt_module, "resolve_shared_config_path", lambda: None)

    response = await skills_router.reload_skills(request=None)

    assert response.success is True
    assert response.scope == "process"


async def test_reload_skills_publishes_shared_marker_off_the_loop(tmp_path: Path, monkeypatch) -> None:
    """Resolving the shared config path and writing the reset marker are filesystem work."""
    await asyncio.to_thread(_seed_skill, tmp_path)
    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(tmp_path))
    config_path = tmp_path / "extensions_config.json"
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(skills_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda **_kwargs: storage)

    try:
        response = await skills_router.reload_skills(request=None)
    finally:
        prompt_module._skills_cache_reset_tracker.reset()

    assert response.success is True
    assert response.scope == "shared_config"
    assert await asyncio.to_thread(lambda: prompt_module.SKILLS_CACHE_RESET_MARKER.path_for(config_path).exists())
