"""Regression anchors: the custom-skill mutation routes must keep their filesystem IO off the loop.

``rollback_custom_skill`` offloads storage construction, existence probes and
the ``custom/.history/<name>.jsonl`` read through ``asyncio.to_thread``, matching
the adjacent ``get_custom_skill_history`` handler. History entries contain the
full previous and new skill content, so reading and parsing the entire history
on the Gateway loop would stall other requests.

``update_custom_skill`` follows the same rule for its pre-scan checks (storage
construction, the editability probes, and the frontmatter validation that
round-trips the draft through a temporary directory) and for the read of the
content being replaced. ``delete_custom_skill`` builds its storage in a worker
too, since a cold user-scoped storage resolves the project root on construction.

The rollback 404 and out-of-range branches return before the awaited security
scan, so they need no scanner or model stub; the accepted-path anchors stub the
LLM scan and keep the real static scan, which already runs in a worker.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException, Request

from app.gateway.routers.skills import CustomSkillUpdateRequest, SkillRollbackRequest, delete_custom_skill, rollback_custom_skill, update_custom_skill
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio

_SKILL_NAME = "loop-rollback-skill"
_SKILL_MD = f"---\nname: {_SKILL_NAME}\ndescription: Anchor fixture skill.\n---\n\n# {_SKILL_NAME}\n"


def _custom_dir() -> Path:
    return get_paths().user_custom_skills_dir(get_effective_user_id())


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)


def _admin_request() -> Request:
    # AuthMiddleware normally supplies this state; keep the real admin check.
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "headers": [], "state": {"user": user}})


def _install_skill() -> None:
    skill_dir = _custom_dir() / _SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")


def _write_history(records: list[dict]) -> None:
    history_dir = _custom_dir() / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{_SKILL_NAME}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


async def test_rollback_missing_skill_does_not_block_event_loop() -> None:
    """The 404 branch must not resolve paths or probe the filesystem from the loop."""
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=0), _admin_request(), config)

    assert excinfo.value.status_code == 404


async def test_rollback_history_read_does_not_block_event_loop() -> None:
    """The out-of-range branch reads and parses the whole history file first."""
    await asyncio.to_thread(_install_skill)
    await asyncio.to_thread(_write_history, [{"action": "edit", "ts": 1, "prev_content": _SKILL_MD, "new_content": _SKILL_MD}])
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=99), _admin_request(), config)

    assert excinfo.value.status_code == 400
    assert "history_index is out of range" in str(excinfo.value.detail)


async def test_rollback_accepted_path_does_not_block_event_loop(monkeypatch) -> None:
    """The accepted-rollback path (validate → scan → current-content read →
    write → append → response read) must keep every filesystem operation off
    the loop (#5747)."""
    await asyncio.to_thread(_install_skill)
    await asyncio.to_thread(
        _write_history,
        [{"action": "edit", "ts": 1, "prev_content": _SKILL_MD, "new_content": _SKILL_MD}],
    )
    monkeypatch.setattr(
        "app.gateway.routers.skills.scan_skill_content",
        AsyncMock(return_value=SimpleNamespace(decision="allow", reason="ok", static_findings=[])),
    )
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    response = await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=0), _admin_request(), config)

    assert response.content == _SKILL_MD


async def test_edit_accepted_path_does_not_block_event_loop(monkeypatch) -> None:
    """The accepted-edit path (editability check → validate → scan → read of
    the replaced content → write → append → response read) must keep every
    filesystem operation off the loop."""
    await asyncio.to_thread(_install_skill)
    monkeypatch.setattr(
        "app.gateway.routers.skills.scan_skill_content",
        AsyncMock(return_value=SimpleNamespace(decision="allow", reason="ok", static_findings=[])),
    )
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    edited = _SKILL_MD + "\nEdited.\n"

    response = await update_custom_skill(_SKILL_NAME, CustomSkillUpdateRequest(content=edited), _admin_request(), config)

    assert response.content == edited


async def test_edit_missing_skill_does_not_block_event_loop() -> None:
    """The editability check's 404 branch probes the public, legacy and
    integration roots before refusing; none of that may run on the loop."""
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await update_custom_skill(_SKILL_NAME, CustomSkillUpdateRequest(content=_SKILL_MD), _admin_request(), config)

    assert excinfo.value.status_code == 404


async def test_delete_does_not_block_event_loop() -> None:
    """Delete builds its user-scoped storage off the loop before the drained removal."""
    await asyncio.to_thread(_install_skill)
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    assert await delete_custom_skill(_SKILL_NAME, _admin_request(), config) == {"success": True}
    assert not await asyncio.to_thread(lambda: (_custom_dir() / _SKILL_NAME).exists())
