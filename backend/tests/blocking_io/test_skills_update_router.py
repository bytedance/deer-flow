"""Regression anchors for ``update_skill``: no event-loop blocking + serialized writes.

``app.gateway.routers.skills.update_skill`` toggles a skill's enabled state by
rewriting ``extensions_config.json``. The skill enumeration, the config
read-modify-write, and the reload are blocking filesystem IO; they are offloaded
via ``asyncio.to_thread`` and serialized with a module-level ``asyncio.Lock`` so
concurrent ``PUT /skills/{name}`` calls cannot clobber each other's toggle on the
shared ``extensions_config`` singleton.

- ``test_update_skill_does_not_block_event_loop``: the strict Blockbuster gate
  fails if the config write regresses back onto the loop (teeth: red pre-fix).
- ``test_update_skill_serializes_concurrent_writes``: two concurrent calls observe
  a max in-flight RMW count of 1 — red if the lock is removed.

Only the config-infra boundaries (storage / ``get_extensions_config`` / reload /
path resolution) are stubbed; the real ``open(config_path, "w")`` write to a tmp
file is exercised.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.routers import skills as skills_router
from app.gateway.routers.skills import SkillUpdateRequest, update_skill
from deerflow.skills import Skill

pytestmark = pytest.mark.asyncio


def _make_skill(name: str, *, enabled: bool) -> Skill:
    skill_dir = Path(f"/tmp/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category="public",
        enabled=enabled,
    )


def _patch_config_infra(monkeypatch, config_path: Path, *, reload_hook=None) -> None:
    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("demo-skill", enabled=True)])
    monkeypatch.setattr("app.gateway.routers.skills.get_or_new_skill_storage", lambda **kwargs: mock_storage)
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", reload_hook or (lambda: None))
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda: config_path))

    async def _refresh():
        return None

    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)


async def test_update_skill_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    _patch_config_infra(monkeypatch, config_path)

    result = await update_skill("demo-skill", SkillUpdateRequest(enabled=False), SimpleNamespace())

    assert result.name == "demo-skill"
    # the real config write ran off the loop
    assert await asyncio.to_thread(config_path.exists)


@pytest.mark.allow_blocking_io  # gate-exempt: needs real worker-thread overlap to observe serialization
async def test_update_skill_serializes_concurrent_writes(tmp_path: Path, monkeypatch) -> None:
    state_lock = threading.Lock()
    counters = {"active": 0, "max": 0}

    def _tracking_reload() -> None:
        # Runs inside the offloaded RMW worker (off the loop), so the sleep that
        # widens the overlap window is allowed under the gate.
        with state_lock:
            counters["active"] += 1
            counters["max"] = max(counters["max"], counters["active"])
        time.sleep(0.02)
        with state_lock:
            counters["active"] -= 1

    _patch_config_infra(monkeypatch, tmp_path / "extensions_config.json", reload_hook=_tracking_reload)

    await asyncio.gather(
        update_skill("demo-skill", SkillUpdateRequest(enabled=False), SimpleNamespace()),
        update_skill("demo-skill", SkillUpdateRequest(enabled=True), SimpleNamespace()),
    )

    # The module-level asyncio.Lock must serialize the offloaded read-modify-write.
    assert counters["max"] == 1
