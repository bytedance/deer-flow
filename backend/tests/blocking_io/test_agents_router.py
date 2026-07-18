"""Regression anchors: the custom-agent router must not block the event loop.

The async route handlers in ``app.gateway.routers.agents`` resolve agent and
user-profile paths (``Paths.base_dir`` calls ``Path.resolve``), probe them
(``Path.exists``), and create/update/remove them (``mkdir``, config/SOUL/USER.md
writes, ``shutil.rmtree``) — all blocking IO. Every handler offloads that work
via ``asyncio.to_thread``; if any of it regresses back onto the event loop, the
strict Blockbuster gate raises ``BlockingError`` and these tests fail.

Coverage: ``create_agent_endpoint``, ``delete_agent``, ``check_agent_name``,
``update_agent``, ``get_user_profile``, and ``update_user_profile``.

Imports live at module scope so the one-time FastAPI app construction (which
reads files while building OpenAPI schemas) happens at collection time, not on
the event loop under test. Test-side path resolution is itself offloaded with
``asyncio.to_thread`` (matching ``test_uploads_middleware``) so only the
handlers' own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from app.gateway.routers import agents as agents_router
from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    UserProfileUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_user_profile,
    update_agent,
    update_user_profile,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


async def test_create_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await create_agent_endpoint(AgentCreateRequest(name="loop-make-agent", soul="You are a test agent."))
        assert response is not None

        user_id = get_effective_user_id()
        # test-side check (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-make-agent")
        assert await asyncio.to_thread((agent_dir / "config.yaml").exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_delete_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-test-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-test-agent\n", encoding="utf-8")

        await delete_agent("loop-test-agent")

        assert not await asyncio.to_thread(agent_dir.exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_check_agent_name_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        # An unused name in an empty home must come back available without the
        # two ``Path.exists`` probes ever touching the event loop.
        result = await check_agent_name("loop-free-name")
        assert result["available"] is True
        assert result["name"] == "loop-free-name"
    finally:
        load_agents_api_config_from_dict({})


async def test_update_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-update-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-update-agent\n", encoding="utf-8")

        response = await update_agent("loop-update-agent", AgentUpdateRequest(description="updated", soul="New soul."))

        assert response.description == "updated"
        assert response.soul == "New soul."
    finally:
        load_agents_api_config_from_dict({})


async def test_get_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        # test-side seeding (resolution offloaded; not exercised on the loop)
        def _seed() -> None:
            paths = get_paths()
            paths.base_dir.mkdir(parents=True, exist_ok=True)
            paths.user_md_file.write_text("I am a test user.", encoding="utf-8")

        await asyncio.to_thread(_seed)

        response = await get_user_profile()
        assert response.content == "I am a test user."
    finally:
        load_agents_api_config_from_dict({})


async def test_update_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await update_user_profile(UserProfileUpdateRequest(content="Profile body."))
        assert response.content == "Profile body."

        # confirm it landed on disk (resolution offloaded; not on the loop)
        def _read() -> str:
            return get_paths().user_md_file.read_text(encoding="utf-8")

        assert await asyncio.to_thread(_read) == "Profile body."
    finally:
        load_agents_api_config_from_dict({})


async def test_concurrent_partial_updates_do_not_lose_fields(tmp_path: Path, monkeypatch) -> None:
    """Two overlapping partial updates to one agent must both survive.

    ``update_agent`` runs its whole load-modify-write in a worker thread, which
    removed the implicit serialization the single-threaded event loop provided.
    Each request loads a full ``AgentConfig`` snapshot and rewrites the complete
    ``config.yaml``, so without the per-agent lock the later write silently
    restores every field it read before the earlier update landed.

    The instrumented load below widens the load->write window and counts how many
    workers are inside the critical section at once, which also proves the second
    mutation cannot enter until the first worker has exited.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "race-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            (agent_dir / "config.yaml").write_text,
            "name: race-agent\ndescription: base\nmodel: old-model\n",
            encoding="utf-8",
        )

        real_load = agents_router.load_agent_config
        state_lock = threading.Lock()
        counters = {"active": 0, "max": 0, "calls": 0}
        # Rendezvous for the two requests' *initial* loads. Unserialized, both
        # requests meet here and therefore both hold the same starting snapshot
        # — the exact interleaving that loses a field. Serialized, the second
        # request cannot reach it while the first holds the agent, so the first
        # simply times out and the barrier breaks (harmless).
        initial_load_barrier = threading.Barrier(2, timeout=0.3)

        def _slow_load(*args, **kwargs):
            # Runs inside the offloaded worker, so blocking here stays off the
            # event loop.
            with state_lock:
                call_index = counters["calls"]
                counters["calls"] += 1
                counters["active"] += 1
                counters["max"] = max(counters["max"], counters["active"])
            try:
                if call_index < 2:
                    try:
                        initial_load_barrier.wait()
                    except threading.BrokenBarrierError:
                        pass
                return real_load(*args, **kwargs)
            finally:
                with state_lock:
                    counters["active"] -= 1

        monkeypatch.setattr(agents_router, "load_agent_config", _slow_load)

        await asyncio.gather(
            update_agent("race-agent", AgentUpdateRequest(description="first")),
            update_agent("race-agent", AgentUpdateRequest(model="new-model")),
        )

        text = await asyncio.to_thread((agent_dir / "config.yaml").read_text, encoding="utf-8")
        final = yaml.safe_load(text)

        # Disjoint updates: neither may be rolled back by the other's rewrite.
        assert final["description"] == "first"
        assert final["model"] == "new-model"
        # The second worker cannot enter the section while the first holds it.
        assert counters["max"] == 1
    finally:
        load_agents_api_config_from_dict({})


async def test_agent_write_lock_structure_stays_bounded(tmp_path: Path, monkeypatch) -> None:
    """Missing-agent requests must not retain a lock per name.

    The per-agent lock is taken before the agent's existence is known, so a
    registry keyed by ``(user_id, name)`` would gain an entry for every distinct
    missing name and never release it — repeated 404s with fresh names would grow
    process memory without creating anything on disk. The stripe array is
    fixed-size, so the structure cannot grow at all.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        before = len(agents_router._agent_write_locks)

        for index in range(250):
            with pytest.raises(HTTPException) as deleted:
                await delete_agent(f"missing-delete-{index}")
            assert deleted.value.status_code == 404

            with pytest.raises(HTTPException) as updated:
                await update_agent(f"missing-update-{index}", AgentUpdateRequest(description="x"))
            assert updated.value.status_code == 404

        assert len(agents_router._agent_write_locks) == before == agents_router._AGENT_WRITE_LOCK_STRIPES

        # Nothing was created on disk by those 404s.
        agents_root = await asyncio.to_thread(get_paths().user_agent_dir, get_effective_user_id(), "missing-delete-0")
        assert not await asyncio.to_thread(agents_root.exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_cancelled_update_keeps_the_agent_lock_until_its_worker_finishes(tmp_path: Path, monkeypatch) -> None:
    """Cancelling the awaiting task must not release the agent to another writer.

    The lock is a threading.Lock owned by the worker, so a cancelled request
    cannot hand the critical section to a second writer while its thread is still
    inside the load-modify-write.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "cancel-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            (agent_dir / "config.yaml").write_text,
            "name: cancel-agent\ndescription: base\nmodel: old-model\n",
            encoding="utf-8",
        )

        real_load = agents_router.load_agent_config
        order: list[str] = []
        order_lock = threading.Lock()
        first_inside = threading.Event()
        release_first = threading.Event()
        calls = {"n": 0}

        def _gated_load(*args, **kwargs):
            with order_lock:
                index = calls["n"]
                calls["n"] += 1
                order.append(f"enter-{index}")
            if index == 0:
                first_inside.set()
                release_first.wait(timeout=5)
                with order_lock:
                    order.append("exit-0")
            return real_load(*args, **kwargs)

        monkeypatch.setattr(agents_router, "load_agent_config", _gated_load)

        first = asyncio.create_task(update_agent("cancel-agent", AgentUpdateRequest(description="first")))
        assert await asyncio.to_thread(first_inside.wait, 5), "first worker never entered the critical section"

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        second = asyncio.create_task(update_agent("cancel-agent", AgentUpdateRequest(model="new-model")))
        await asyncio.sleep(0.1)

        # The cancelled request's worker still owns the agent.
        with order_lock:
            assert order == ["enter-0"], f"second writer entered while the cancelled worker held the agent: {order}"

        release_first.set()
        await second

        with order_lock:
            assert order[:2] == ["enter-0", "exit-0"], order
    finally:
        load_agents_api_config_from_dict({})
