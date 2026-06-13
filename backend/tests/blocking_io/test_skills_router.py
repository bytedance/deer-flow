"""Regression anchor: get_custom_skill_history must not block the event loop.

``app.gateway.routers.skills.get_custom_skill_history`` is an async route handler
that probes custom-skill storage (``custom_skill_exists`` /
``get_skill_history_file().exists()``) and reads the per-skill ``.history`` file —
all blocking filesystem IO. It offloads that work via ``asyncio.to_thread``; if it
regresses back onto the event loop, the strict Blockbuster gate raises
``BlockingError`` and this test fails.

Seeding the skill + history on disk is itself offloaded with ``asyncio.to_thread``
so only the handler's own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.routers.skills import get_custom_skill_history
from deerflow.skills.storage import get_or_new_skill_storage

pytestmark = pytest.mark.asyncio


def _config(skills_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )


async def test_get_custom_skill_history_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    config = _config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    def _seed() -> None:
        # Real custom skill + history file on disk (seeding offloaded; not under test).
        custom_dir = skills_root / "custom" / "demo-skill"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "SKILL.md").write_text("---\nname: demo-skill\ndescription: d\n---\n", encoding="utf-8")
        history_file = get_or_new_skill_storage(app_config=config).get_skill_history_file("demo-skill")
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps({"action": "human_edit", "new_content": "x"}) + "\n", encoding="utf-8")

    await asyncio.to_thread(_seed)

    response = await get_custom_skill_history("demo-skill", config)

    assert len(response.history) == 1
    assert response.history[-1]["action"] == "human_edit"
