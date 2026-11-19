"""Regression test: skill loading must remain releasable to a worker thread.

Anchors the production offload from `subagents/executor.py:_load_skills`,
where both `get_or_new_skill_storage` and the sync `storage.load_skills(...)`
method are dispatched via `asyncio.to_thread`. That fix addressed #1917,
where `os.walk` inside `load_skills` blocked the LangGraph async event loop.

This test invokes the production `_load_skills()` call path under the strict
Blockbuster context against a real `LocalSkillStorage` instance pointed at
a tmp directory. If the production `asyncio.to_thread` offload is removed,
Blockbuster raises `BlockingError` and this test fails.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio

_MISSING = object()
_EXECUTOR_IMPORT_MOCKS = (
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.models",
)


def _seed_skill(skills_root: Path) -> None:
    skill = skills_root / "public" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: regression-test skill\n---\n# demo\n",
        encoding="utf-8",
    )


@contextmanager
def _real_subagent_executor() -> Iterator[type]:
    """Import the real executor despite the suite-level circular-import mock."""
    original_modules = {name: sys.modules.get(name, _MISSING) for name in _EXECUTOR_IMPORT_MOCKS}
    original_executor = sys.modules.get("deerflow.subagents.executor", _MISSING)
    parent_module = sys.modules.get("deerflow.subagents")
    original_parent_executor = getattr(parent_module, "executor", _MISSING) if parent_module is not None else _MISSING

    sys.modules.pop("deerflow.subagents.executor", None)
    for name in _EXECUTOR_IMPORT_MOCKS:
        sys.modules[name] = MagicMock()

    try:
        executor_module = importlib.import_module("deerflow.subagents.executor")
        yield executor_module.SubagentExecutor
    finally:
        if original_executor is _MISSING:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = original_executor

        if parent_module is not None:
            if original_parent_executor is _MISSING:
                try:
                    delattr(parent_module, "executor")
                except AttributeError:
                    pass
            else:
                parent_module.executor = original_parent_executor

        for name, module in original_modules.items():
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


async def test_load_skills_via_to_thread_does_not_block_event_loop(tmp_path: Path) -> None:
    from deerflow.config.skills_config import SkillsConfig
    from deerflow.subagents.config import SubagentConfig

    _seed_skill(tmp_path)

    with _real_subagent_executor() as SubagentExecutor:
        executor = SubagentExecutor(
            config=SubagentConfig(
                name="demo",
                description="Loads skills through the production async path.",
            ),
            tools=[],
            app_config=SimpleNamespace(skills=SkillsConfig(path=str(tmp_path))),
            parent_model="test-model",
        )

        skills = await executor._load_skills()

    assert isinstance(skills, list)
    assert any(s.name == "demo" for s in skills)
