"""Regression test: skill loading must remain releasable to a worker thread.

Anchors the production offload from `subagents/executor.py:_load_skills`
(lines around 354-356) where both `get_or_new_skill_storage` and the sync
`storage.load_skills(...)` method are dispatched via `asyncio.to_thread`.
That fix addressed #1917, where `os.walk` inside `load_skills` blocked the
LangGraph async event loop.

This test invokes the same `asyncio.to_thread` pattern under the strict
Blockbuster context against a real `LocalSkillStorage` instance pointed at
a tmp directory. If the underlying implementation introduces blocking IO
that `asyncio.to_thread` cannot release (for example, native-extension calls
that hold the event loop somehow), Blockbuster raises `BlockingError` and
this test fails.

Manual verification that production *callers* also stay offloaded is
captured in the PR body (revert the `asyncio.to_thread` wrappers in
`subagents/executor.py` and observe BlockingError downstream).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


def _seed_skill(skills_root: Path) -> None:
    skill = skills_root / "public" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: regression-test skill\n---\n# demo\n",
        encoding="utf-8",
    )


async def test_load_skills_via_to_thread_does_not_block_event_loop(tmp_path: Path) -> None:
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

    _seed_skill(tmp_path)

    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(tmp_path))
    skills = await asyncio.to_thread(storage.load_skills, enabled_only=False)

    assert isinstance(skills, list)
    assert any(s.name == "demo" for s in skills)
