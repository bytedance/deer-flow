"""Team store ownership and reads run outside the Gateway event loop."""

import asyncio
import threading
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_team_storage_lifecycle_and_queries_stay_offloop(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "examples/deerflow-extension-agent-teams"))
    from deerflow_extension_agent_teams.service import Teams
    from deerflow_extension_agent_teams.store import Store

    store = await asyncio.to_thread(Store, tmp_path / "teams.sqlite")
    loop_thread = threading.get_ident()
    threads = []
    acquire, check, snapshot = store.acquire_service_lock, store.check_service_lock, store.scheduling_snapshots

    class Lock:
        def __init__(self, connection):
            self.connection = connection

        def close(self):
            threads.append(threading.get_ident())
            self.connection.close()

    def record_acquire():
        threads.append(threading.get_ident())
        return Lock(acquire())

    def record_check():
        threads.append(threading.get_ident())
        return check()

    def record_snapshot():
        threads.append(threading.get_ident())
        return snapshot()

    monkeypatch.setattr(store, "acquire_service_lock", record_acquire)
    monkeypatch.setattr(store, "check_service_lock", record_check)
    monkeypatch.setattr(store, "scheduling_snapshots", record_snapshot)
    service = Teams(store=store)
    await service.start(None)
    try:
        await service.ensure_available()
        assert await service.db("scheduling_snapshots") == {}
    finally:
        await service.stop()
    assert len(threads) >= 5
    assert all(thread != loop_thread for thread in threads)
