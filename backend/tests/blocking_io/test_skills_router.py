"""Regression anchor: get_custom_skill_history must not block the event loop.

``app.gateway.routers.skills.get_custom_skill_history`` is an async route handler
that probes custom-skill storage (``custom_skill_exists`` /
``get_skill_history_file().exists()``) and reads the per-skill ``.history`` file —
all blocking filesystem IO. It offloads that work via ``asyncio.to_thread``; if it
regresses back onto the event loop, the strict Blockbuster gate raises
``BlockingError`` and this test fails.

Seeding the history on disk is itself offloaded with ``asyncio.to_thread`` so only
the handler's own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import Request

from app.gateway.routers.skills import _get_user_skill_storage, get_custom_skill_history

pytestmark = pytest.mark.asyncio


def _config(skills_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


def _admin_request() -> Request:
    # The route is admin-only. ``AuthMiddleware`` normally stamps
    # ``request.state.user``; supply it directly here, as
    # ``test_channel_runtime_config_store`` does for the same reason.
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "headers": [], "state": {"user": user}})


async def test_get_custom_skill_history_does_not_block_event_loop(tmp_path: Path) -> None:
    config = _config(tmp_path / "skills")

    def _seed() -> None:
        # Seed through the same user-scoped accessor the handler uses so both
        # resolve the same storage root. An existing history file is enough for
        # the handler to skip the 404 branch and read it.
        history_file = _get_user_skill_storage(config).get_skill_history_file("demo-skill")
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps({"action": "human_edit", "new_content": "x"}) + "\n", encoding="utf-8")

    request = await asyncio.to_thread(_admin_request)
    await asyncio.to_thread(_seed)

    response = await get_custom_skill_history("demo-skill", request, config)

    assert len(response.history) == 1
    assert response.history[-1]["action"] == "human_edit"
