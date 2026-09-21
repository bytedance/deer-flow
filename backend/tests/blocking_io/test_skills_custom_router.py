"""Regression anchor: the custom-skill rollback route must keep its history reads off the loop.

``rollback_custom_skill`` builds the user-scoped storage, probes whether the
skill exists and parses ``custom/.history/<name>.jsonl`` inline, while every
other filesystem phase in the same handler already runs through
``asyncio.to_thread`` — including ``get_custom_skill_history`` directly above
it, whose own comment states that "storage construction, the existence probes,
and the history-file read are blocking filesystem IO that must stay off the
event loop". The history file grows one entry per edit carrying the full
previous and new content of the skill, so a rollback request parses that whole
edit history on the Gateway loop.

The two branches driven here both return before the awaited security scan, so
the anchor needs no scanner or model stub: the 404 branch covers construction
plus the existence probes, and the out-of-range branch covers the full
history-file read and parse.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.gateway.routers.skills as skills_router
from app.gateway.routers.skills import SkillRollbackRequest, rollback_custom_skill
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

    async def _allow(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(skills_router, "require_admin_user", _allow)


def _install_skill() -> None:
    skill_dir = _custom_dir() / _SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")


def _write_history(records: list[dict]) -> None:
    history_dir = _custom_dir() / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{_SKILL_NAME}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


async def test_rollback_missing_skill_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 404 branch must not resolve paths or probe the filesystem from the loop."""
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=0), SimpleNamespace(), config)

    assert excinfo.value.status_code == 404


async def test_rollback_history_read_does_not_block_event_loop() -> None:
    """The out-of-range branch reads and parses the whole history file first."""
    await asyncio.to_thread(_install_skill)
    await asyncio.to_thread(_write_history, [{"action": "edit", "ts": 1, "prev_content": _SKILL_MD, "new_content": _SKILL_MD}])
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=99), SimpleNamespace(), config)

    assert excinfo.value.status_code == 400
    assert "history_index is out of range" in str(excinfo.value.detail)
