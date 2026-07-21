"""Regression anchors for ``update_skill``: no event-loop blocking + serialized writes.

``app.gateway.routers.skills.update_skill`` toggles a skill's enabled state. For a
PUBLIC skill that rewrites the shared ``extensions_config.json``; the skill
enumeration, the config read-modify-write, and the reload are blocking filesystem
IO, so they are offloaded via ``asyncio.to_thread``. Offloading removes the
implicit serialization the single-threaded event loop provided, so the RMW is
guarded by ``extensions_config_write_lock`` — shared with the MCP router, which
performs the same RMW on the same file.

- ``test_update_skill_does_not_block_event_loop``: the strict Blockbuster gate
  fails if the config write regresses back onto the loop (teeth: red pre-fix).
- ``test_update_skill_writes_from_snapshot_without_mutating_singleton``: the write
  payload is built from a snapshot, so the cached ``extensions_config`` singleton
  is never mutated in place while the write is still in flight.
- ``test_update_skill_serializes_concurrent_writes``: two concurrent calls observe
  a max in-flight RMW count of 1 — red if the lock is removed.
- ``test_skill_and_mcp_config_writes_are_serialized``: a skill toggle and an MCP
  config update never overlap inside the shared-file RMW — red if the two routers
  go back to separate module-local locks.

Only the config-infra boundaries (storage / ``get_extensions_config`` / reload /
path resolution) are stubbed; the real ``open(config_path, "w")`` write to a tmp
file is exercised.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers import skills as skills_router
from app.gateway.routers.mcp import McpConfigUpdateRequest
from app.gateway.routers.skills import SkillUpdateRequest, update_skill
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig
from deerflow.skills import Skill

pytestmark = pytest.mark.asyncio


def _admin_request() -> SimpleNamespace:
    # ``require_admin_user`` reads ``request.state.user``; AuthMiddleware normally
    # stamps it. A SimpleNamespace is enough for the direct-call tests.
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return SimpleNamespace(state=SimpleNamespace(user=user))


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


def _patch_config_infra(monkeypatch, config_path: Path, *, reload_hook=None) -> ExtensionsConfig:
    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("demo-skill", enabled=True)])
    shared_config = ExtensionsConfig()
    monkeypatch.setattr("app.gateway.routers.skills._get_user_skill_storage", lambda _config: mock_storage)
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: shared_config)
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", reload_hook or (lambda: None))
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda _path=None: config_path))
    # PUBLIC toggles drop every user's prompt cache; the handler offloads this
    # sync call, so a no-op keeps the test focused on the config write.
    monkeypatch.setattr("app.gateway.routers.skills.clear_skills_system_prompt_cache", lambda: None)
    return shared_config


async def test_update_skill_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    _patch_config_infra(monkeypatch, config_path)

    result = await update_skill("demo-skill", SkillUpdateRequest(enabled=False), _admin_request(), SimpleNamespace())

    assert result.name == "demo-skill"
    # the real config write ran off the loop
    assert await asyncio.to_thread(config_path.exists)


async def test_update_skill_writes_from_snapshot_without_mutating_singleton(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("demo-skill", enabled=True)])
    shared_config = ExtensionsConfig(skills={"existing-skill": SkillStateConfig(enabled=True)})

    monkeypatch.setattr("app.gateway.routers.skills._get_user_skill_storage", lambda _config: mock_storage)
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: shared_config)
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda _path=None: config_path))
    monkeypatch.setattr("app.gateway.routers.skills.clear_skills_system_prompt_cache", lambda: None)

    result = await update_skill("demo-skill", SkillUpdateRequest(enabled=False), _admin_request(), SimpleNamespace())

    assert result.name == "demo-skill"
    # The cached singleton must not have been mutated: the new skill only exists
    # in the deep copy that was serialized to disk.
    assert "demo-skill" not in shared_config.skills
    config_text = await asyncio.to_thread(config_path.read_text, encoding="utf-8")
    written = json.loads(config_text)
    assert written["skills"] == {
        "existing-skill": {"enabled": True},
        "demo-skill": {"enabled": False},
    }
    # to_file_dict() serializes the full shape, so unrelated top-level keys survive.
    assert written["mcpServers"] == {}
    assert "middlewares" in written


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
        update_skill("demo-skill", SkillUpdateRequest(enabled=False), _admin_request(), SimpleNamespace()),
        update_skill("demo-skill", SkillUpdateRequest(enabled=True), _admin_request(), SimpleNamespace()),
    )

    # The shared asyncio.Lock must serialize the offloaded read-modify-write.
    assert counters["max"] == 1


@pytest.mark.allow_blocking_io  # gate-exempt: needs real worker-thread overlap to observe serialization
async def test_skill_and_mcp_config_writes_are_serialized(tmp_path: Path, monkeypatch) -> None:
    """A skill toggle and an MCP update must not interleave on extensions_config.json.

    Both routers read-modify-write the same file from a worker thread. With
    separate locks the loop is free to run the MCP RMW inside the skills RMW's
    read→write window, and the later write silently drops the other's change. The
    shared ``extensions_config_write_lock`` closes that window.

    Both sides are instrumented *inside* their real workers (via each module's
    ``reload_extensions_config``, the last step under the lock) rather than by
    stubbing the workers out — the lock lives in the worker, so replacing it would
    bypass the thing under test.
    """
    config_path = tmp_path / "extensions_config.json"
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    state_lock = threading.Lock()
    counters = {"active": 0, "max": 0}

    def _enter_rmw() -> None:
        with state_lock:
            counters["active"] += 1
            counters["max"] = max(counters["max"], counters["active"])
        time.sleep(0.02)
        with state_lock:
            counters["active"] -= 1

    # Skills side: real _write_extensions_skill_state (and its lock) runs.
    _patch_config_infra(monkeypatch, config_path, reload_hook=_enter_rmw)

    # MCP side: real _apply_mcp_config_update (and its lock) runs; only admin,
    # validation and the reload are stubbed.
    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    def _tracking_reload(*_args, **_kwargs):
        _enter_rmw()
        return SimpleNamespace(mcp_servers={})

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda _body: None)
    monkeypatch.setattr(mcp_router, "reset_mcp_tools_cache", lambda: None)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", _tracking_reload)

    await asyncio.gather(
        update_skill("demo-skill", SkillUpdateRequest(enabled=False), _admin_request(), SimpleNamespace()),
        mcp_router.update_mcp_configuration(_admin_request(), McpConfigUpdateRequest(mcp_servers={})),
    )

    assert counters["max"] == 1


@pytest.mark.allow_blocking_io  # gate-exempt: needs real worker-thread overlap to observe serialization
async def test_cancelled_writer_keeps_the_lock_until_its_worker_finishes(tmp_path: Path, monkeypatch) -> None:
    """Cancelling the awaiting task must not release the RMW to another writer.

    An ``asyncio.Lock`` held around ``await asyncio.to_thread(...)`` protects only
    the awaiting task: cancelling it releases the lock immediately while Python
    keeps running the worker thread, so a second writer could enter and operate on
    ``extensions_config.json`` concurrently with the first. Owning a
    ``threading.Lock`` from inside the worker keeps the section held until the
    write and reload actually finish.

    Here the skills worker is paused after it has written and is inside the lock;
    its route task is then cancelled and the MCP writer is started. The MCP RMW
    must not enter until the skills worker is released.
    """
    config_path = tmp_path / "extensions_config.json"
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    order: list[str] = []
    order_lock = threading.Lock()
    skills_inside = threading.Event()
    release_skills = threading.Event()
    mcp_cache_reset = threading.Event()

    def _skills_reload() -> None:
        # Inside the real _write_extensions_skill_state, under the lock, after the
        # config write has already been committed to disk.
        with order_lock:
            order.append("skills-enter")
        skills_inside.set()
        release_skills.wait(timeout=5)
        with order_lock:
            order.append("skills-exit")

    def _mcp_reload(*_args, **_kwargs):
        with order_lock:
            order.append("mcp-enter")
        return SimpleNamespace(mcp_servers={})

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    _patch_config_infra(monkeypatch, config_path, reload_hook=_skills_reload)
    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda _body: None)
    monkeypatch.setattr(mcp_router, "reset_mcp_tools_cache", mcp_cache_reset.set)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", _mcp_reload)

    skills_task = asyncio.create_task(update_skill("demo-skill", SkillUpdateRequest(enabled=False), _admin_request(), SimpleNamespace()))
    assert await asyncio.to_thread(skills_inside.wait, 5), "skills worker never entered the critical section"

    # Cancel the awaiting task while its worker thread is still inside the RMW.
    skills_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await skills_task

    mcp_task = asyncio.create_task(mcp_router.update_mcp_configuration(_admin_request(), McpConfigUpdateRequest(mcp_servers={})))
    await asyncio.sleep(0.1)

    # The cancelled request's worker still owns the section.
    with order_lock:
        assert "mcp-enter" not in order, f"MCP writer entered while the cancelled worker was still inside: {order}"

    release_skills.set()
    await mcp_task

    with order_lock:
        assert order == ["skills-enter", "skills-exit", "mcp-enter"], order

    # The non-cancelled writer still completed its cache invalidation.
    assert mcp_cache_reset.is_set()
