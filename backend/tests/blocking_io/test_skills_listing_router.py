"""Regression anchors: the skill listing/detail routes must not block the event loop.

``list_skills``, ``list_custom_skills`` and ``get_skill`` all call
``SkillStorage.load_skills()``, which walks every public and custom skill
directory and parses each ``SKILL.md`` -- blocking filesystem IO that scales
with the number of installed skills. #5747 moved the same call off the loop
for ``get_custom_skill`` (and left a comment saying why) but these three
routes kept calling it inline. Under the strict Blockbuster gate they raise
``BlockingError``; with the fix they offload it via ``asyncio.to_thread``.

Seeding the custom skill on disk is itself offloaded so only the handlers'
own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

# ``_filter_visible_skills`` resolves the caller through ``deps`` helpers that
# import ``app.gateway.auth`` lazily; import it here so that one-time module
# load happens at collection time and only the handlers' own filesystem access
# is exercised on the loop (same reason ``test_agents_router`` builds the app
# at import time).
import app.gateway.auth  # noqa: F401
import app.gateway.auth.errors  # noqa: F401
from app.gateway.routers.skills import get_skill, list_custom_skills, list_skills
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio

_SKILL_NAME = "loop-listing-skill"
_SKILL_MD = f"---\nname: {_SKILL_NAME}\ndescription: Anchor fixture skill.\n---\n\n# {_SKILL_NAME}\n"


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)


def _config(skills_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        authorization=SimpleNamespace(enabled=False, fail_closed=False),
    )


def _anonymous_request() -> Request:
    # No auth state: ``_filter_visible_skills`` returns the input unfiltered,
    # so the only filesystem work on the loop is the handler's own.
    return Request({"type": "http", "headers": [], "state": {}})


def _install_skill(skills_root: Path) -> None:
    (skills_root / "public").mkdir(parents=True, exist_ok=True)
    skill_dir = get_paths().user_custom_skills_dir(get_effective_user_id()) / _SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")


async def _seeded(tmp_path: Path) -> tuple[SimpleNamespace, Request]:
    skills_root = tmp_path / "skills"
    config = _config(skills_root)
    await asyncio.to_thread(_install_skill, skills_root)
    request = await asyncio.to_thread(_anonymous_request)
    return config, request


async def test_list_skills_does_not_block_event_loop(tmp_path: Path) -> None:
    config, request = await _seeded(tmp_path)

    response = await list_skills(request, config)

    assert [skill.name for skill in response.skills] == [_SKILL_NAME]


async def test_list_custom_skills_does_not_block_event_loop(tmp_path: Path) -> None:
    config, request = await _seeded(tmp_path)

    response = await list_custom_skills(request, config)

    assert [skill.name for skill in response.skills] == [_SKILL_NAME]


async def test_get_skill_does_not_block_event_loop(tmp_path: Path) -> None:
    config, request = await _seeded(tmp_path)

    response = await get_skill(_SKILL_NAME, request, config)
    assert response.name == _SKILL_NAME

    # The 404 branch walks the same directories before deciding.
    with pytest.raises(HTTPException) as exc_info:
        await get_skill("never-installed-skill", request, config)
    assert exc_info.value.status_code == 404
