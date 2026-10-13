"""Regression anchor: the agent's ``skill_manage`` tool must keep its storage lookup off the loop.

``_skill_manage_impl`` offloads every per-action filesystem step through
``asyncio.to_thread``. The user-scoped storage lookup in front of them resolves
the app config (``get_app_config`` stats ``config.yaml`` on every call) and, on
a cold cache, the project root, so it runs in a worker as well -- the same rule
the Gateway's custom-skill edit route applies.

Only the LLM security scan is stubbed; the app config is pinned so the lookup
needs no ``config.yaml`` on disk, and the edit runs against the real per-user
storage under ``DEER_FLOW_HOME``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import deerflow.tools.skill_manage_tool as skill_manage_module
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths

pytestmark = pytest.mark.asyncio

_SKILL_NAME = "loop-manage-skill"
_SKILL_MD = f"---\nname: {_SKILL_NAME}\ndescription: Anchor fixture skill.\n---\n\n# {_SKILL_NAME}\n"
_RUNTIME = SimpleNamespace(
    context={"thread_id": "thread-1", "user_id": "default"},
    config={"configurable": {"thread_id": "thread-1", "user_id": "default"}},
)


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)


def _install_skill() -> Path:
    skill_dir = get_paths().user_custom_skills_dir("default") / _SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(_SKILL_MD, encoding="utf-8")
    return skill_file


async def test_skill_manage_edit_does_not_block_event_loop(monkeypatch) -> None:
    skill_file = await asyncio.to_thread(_install_skill)
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    async def _allow_scan(*args, **kwargs):
        return SimpleNamespace(decision="allow", reason="anchor stub")

    monkeypatch.setattr(skill_manage_module, "scan_skill_content", _allow_scan)
    edited = _SKILL_MD + "\nEdited.\n"

    result = await skill_manage_module.skill_manage_tool.coroutine(_RUNTIME, "edit", _SKILL_NAME, edited)

    assert result == f"Updated custom skill '{_SKILL_NAME}'."
    assert await asyncio.to_thread(skill_file.read_text, encoding="utf-8") == edited
