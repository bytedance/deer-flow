"""Third-party completion stores must opt into the strict metadata contract."""

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore


class AbsorbingStore(MemoryRunStore):
    async def update_run_completion(self, run_id, *, status, **kwargs):
        self.completion_calls = getattr(self, "completion_calls", 0) + 1
        self._runs[run_id].update(status=status, **kwargs)
        return True


class FlagOnlyChild(AbsorbingStore):
    supports_terminal_completion_kwargs = True


class OptedInStore(MemoryRunStore):
    supports_terminal_completion_kwargs = True

    async def update_run_completion(self, run_id, *, status, **kwargs):
        self.completion_calls = getattr(self, "completion_calls", 0) + 1
        return await super().update_run_completion(run_id, status=status, **kwargs)


class InheritedOptIn(OptedInStore):
    pass


class UnoptedOverride(OptedInStore):
    async def update_run_completion(self, run_id, *, status, **kwargs):
        self.completion_calls = getattr(self, "completion_calls", 0) + 1
        return await MemoryRunStore.update_run_completion(self, run_id, status=status, **kwargs)


class ExplicitStore(MemoryRunStore):
    async def update_run_completion(self, run_id, *, status, require_terminal=False, owner_worker_id=None, **kwargs):
        self.completion_calls = getattr(self, "completion_calls", 0) + 1
        return await super().update_run_completion(run_id, status=status, require_terminal=require_terminal, owner_worker_id=owner_worker_id, **kwargs)


class PartialContract(AbsorbingStore):
    async def update_run_completion(self, run_id, *, status, require_terminal=False, **kwargs):
        return await super().update_run_completion(run_id, status=status, require_terminal=require_terminal, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("store_type", [AbsorbingStore, FlagOnlyChild, UnoptedOverride, PartialContract])
async def test_unproven_kwargs_completion_is_skipped(store_type, caplog):
    store = store_type()
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread")
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    proof = record.terminal_commit_proof
    assert proof is not None
    await manager.update_run_completion(record.run_id, status="success", total_tokens=7)
    assert getattr(store, "completion_calls", 0) == 0
    row = await store.get(record.run_id)
    assert row.get("total_tokens", 0) == 0
    assert "require_terminal" not in row
    assert record.terminal_commit_proof is proof
    assert not record.ownership_lost
    assert "require_terminal" in caplog.text
    assert "owner_worker_id" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("store_type", [MemoryRunStore, ExplicitStore, OptedInStore, InheritedOptIn])
async def test_declared_completion_contract_updates_metadata(store_type):
    store = store_type()
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread")
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    await manager.update_run_completion(record.run_id, status="success", total_tokens=7)
    row = await store.get(record.run_id)
    assert row["total_tokens"] == 7
    assert "require_terminal" not in row
    assert row["owner_worker_id"] == "owner"


@pytest.mark.anyio
async def test_single_worker_preserves_legacy_kwargs_completion():
    store = AbsorbingStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("thread")
    await manager.update_run_completion(record.run_id, status="success", total_tokens=7)
    assert store.completion_calls == 1
    row = await store.get(record.run_id)
    assert row["total_tokens"] == 7
    assert "require_terminal" not in row
