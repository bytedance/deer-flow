"""Backup restoration through DeerMem and its canonical file repository."""

import copy
from collections.abc import Iterator
from pathlib import Path

import pytest

from deerflow.agents.memory import MemoryConflictError
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.paths import fact_file_path
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    MemoryFactRevisionConflict,
    MemoryManifestRevisionConflict,
    _render_fact_markdown,
)


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[DeerMem]:
    backend = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    try:
        yield backend
    finally:
        backend.close()


@pytest.mark.parametrize("agent_name", [None, "researcher"])
@pytest.mark.parametrize("backup_revision", [1, None, 20], ids=["older", "omitted", "newer"])
def test_import_restores_backup_with_current_fact_revision(manager: DeerMem, agent_name: str | None, backup_revision: int | None) -> None:
    scope = {"user_id": "alice", "agent_name": agent_name}
    initial, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    manager.import_memory(initial, user_id="alice", agent_name="other-agent")
    manager.import_memory(initial, user_id="bob", agent_name=agent_name)
    other_agent = manager.get_memory(user_id="alice", agent_name="other-agent")["facts"]
    other_user = manager.get_memory(user_id="bob", agent_name=agent_name)
    backup = manager.get_memory(**scope)
    if backup_revision is None:
        backup["facts"][0].pop("revision")
    else:
        backup["facts"][0]["revision"] = backup_revision
    original = copy.deepcopy(backup)

    edited = manager.update_fact(fact_id, content="Use SQLite", **scope)
    manager._storage.update_summaries(
        {
            "user": {"workContext": {"summary": "Current work", "updatedAt": "2026-10-01T00:00:00Z"}},
            "history": {"recentMonths": {"summary": "Current history", "updatedAt": "2026-10-01T00:00:00Z"}},
        },
        user_id="alice",
    )
    before = manager.get_memory(**scope)

    restored = manager.import_memory(backup, **scope)

    assert restored["facts"][0]["id"] == fact_id
    assert restored["facts"][0]["content"] == "Use PostgreSQL"
    assert restored["facts"][0]["revision"] == edited["facts"][0]["revision"] + 1
    assert restored["facts"][0]["createdAt"] == initial["facts"][0]["createdAt"]
    assert restored["facts"][0]["scope"] == {"userId": "alice", "agentName": agent_name or "__default__"}
    expected_summaries = before if agent_name else backup
    assert restored["user"] == expected_summaries["user"]
    assert restored["history"] == expected_summaries["history"]
    assert manager.reload_memory(**scope) == restored
    assert manager.get_memory(user_id="alice", agent_name="other-agent")["facts"] == other_agent
    assert manager.get_memory(user_id="bob", agent_name=agent_name) == other_user
    assert backup == original


@pytest.mark.parametrize("agent_name", [None, "researcher"])
def test_import_current_backup_is_idempotent(manager: DeerMem, agent_name: str | None) -> None:
    scope = {"user_id": "alice", "agent_name": agent_name}
    _, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    manager.update_fact(fact_id, content="Use SQLite", **scope)
    backup = manager.get_memory(**scope)
    original = copy.deepcopy(backup)

    assert manager.import_memory(backup, **scope) == original
    assert manager.import_memory(backup, **scope) == original
    assert manager.reload_memory(**scope) == original
    assert backup == original


@pytest.mark.parametrize("agent_name", [None, "researcher"])
@pytest.mark.parametrize("existing_id", [True, False], ids=["existing", "new"])
@pytest.mark.parametrize("revision", [0, -1, True, False, 1.5, "1", None], ids=["zero", "negative", "true", "false", "float", "string", "null"])
def test_import_rejects_invalid_backup_revision(manager: DeerMem, agent_name: str | None, existing_id: bool, revision: object) -> None:
    scope = {"user_id": "alice", "agent_name": agent_name}
    _, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    backup = manager.get_memory(**scope)
    backup["facts"][0]["revision"] = revision
    if not existing_id:
        backup["facts"][0]["id"] = "new_fact"
    original = copy.deepcopy(backup)
    manager.update_fact(fact_id, content="Use SQLite", **scope)
    manager.create_fact("Keep the post-backup fact", **scope)
    before = manager.get_memory(**scope)

    with pytest.raises(ValueError, match=r"fact\.revision must be an integer >= 1"):
        manager.import_memory(backup, **scope)

    assert manager.reload_memory(**scope) == before
    assert backup == original


def test_import_validates_revisions_before_capacity_selection(manager: DeerMem) -> None:
    scope = {"user_id": "alice"}
    _, fact_id = manager.create_fact("Keep the current preference", **scope)
    assert fact_id is not None
    before = manager.get_memory(**scope)
    backup = copy.deepcopy(before)
    backup["facts"].append({"id": "invalid", "content": "Low-confidence fact", "confidence": 0.1, "revision": 0})
    manager._updater._config.max_facts = 1

    with pytest.raises(ValueError, match=r"fact\.revision must be an integer >= 1"):
        manager.import_memory(backup, **scope)

    assert manager.reload_memory(**scope) == before


@pytest.mark.parametrize("agent_name", [None, "researcher"])
def test_import_recreates_deleted_fact_and_removes_post_backup_fact(manager: DeerMem, agent_name: str | None) -> None:
    scope = {"user_id": "alice", "agent_name": agent_name}
    _, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    manager.update_fact(fact_id, content="Use SQLite", **scope)
    backup = manager.get_memory(**scope)
    original = copy.deepcopy(backup)
    manager.delete_fact(fact_id, **scope)
    _, extra_id = manager.create_fact("Added after the backup", **scope)
    assert extra_id is not None

    restored = manager.import_memory(backup, **scope)

    assert restored["facts"] == original["facts"]
    assert manager.reload_memory(**scope)["facts"] == original["facts"]
    assert backup == original


@pytest.mark.parametrize("agent_name", [None, "researcher"])
@pytest.mark.parametrize("concurrent_change", ["update", "delete", "create", "summaries"])
def test_import_rejects_concurrent_write(manager: DeerMem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_name: str | None, concurrent_change: str) -> None:
    scope = {"user_id": "alice", "agent_name": agent_name}
    _, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    backup = manager.get_memory(**scope)
    backup["facts"].append({"id": "restored_fact", "content": "Another saved preference"})
    original = copy.deepcopy(backup)
    manager.update_fact(fact_id, content="Use SQLite", **scope)
    _, extra_id = manager.create_fact("Post-backup fact", **scope)
    assert extra_id is not None
    before = manager.get_memory(**scope)
    peer = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    real_apply = manager._storage.apply_changes
    committed: list[dict] = []

    def apply_after_concurrent_write(change_set: dict, **kwargs) -> dict:
        assert not committed, "A replacement import must not replay a stale snapshot"
        assert kwargs["expected_manifest_revision"] == before["revision"]
        assert not kwargs.get("allow_manifest_rebase", False)
        assert change_set["upsertRevisions"] == {fact_id: 2, "restored_fact": None}
        assert change_set["deleteRevisions"] == {extra_id: 1}
        assert change_set["deletes"] == [extra_id]
        if concurrent_change == "update":
            peer.update_fact(fact_id, content="Concurrent preference", **scope)
        elif concurrent_change == "delete":
            peer.delete_fact(fact_id, **scope)
        elif concurrent_change == "create":
            peer.create_fact("Concurrent new fact", **scope)
        else:
            peer._storage.update_summaries({"user": {"workContext": {"summary": "Concurrent work", "updatedAt": "now"}}}, user_id="alice")
        committed.append(peer.get_memory(**scope))
        return real_apply(change_set, **kwargs)

    monkeypatch.setattr(manager._storage, "apply_changes", apply_after_concurrent_write)
    try:
        with pytest.raises(MemoryConflictError) as error:
            manager.import_memory(backup, **scope)

        assert isinstance(error.value.__cause__, MemoryManifestRevisionConflict)
        assert len(committed) == 1
        assert manager.reload_memory(**scope) == committed[0]
        assert backup == original
    finally:
        peer.close()


@pytest.mark.parametrize("changed_fact", ["upsert", "delete", "create"])
def test_import_keeps_fact_preconditions_when_manifest_is_unchanged(manager: DeerMem, monkeypatch: pytest.MonkeyPatch, changed_fact: str) -> None:
    scope = {"user_id": "alice", "agent_name": "researcher"}
    _, fact_id = manager.create_fact("Use PostgreSQL", **scope)
    assert fact_id is not None
    backup = manager.get_memory(**scope)
    new_fact = {**copy.deepcopy(backup["facts"][0]), "id": "restored_fact", "content": "Saved preference"}
    backup["facts"].append(new_fact)
    original = copy.deepcopy(backup)
    manager.update_fact(fact_id, content="Use SQLite", **scope)
    _, extra_id = manager.create_fact("Post-backup fact", **scope)
    assert extra_id is not None
    before = manager.get_memory(**scope)
    by_id = {fact["id"]: fact for fact in before["facts"]}
    target = {"upsert": by_id[fact_id], "delete": by_id[extra_id], "create": new_fact}[changed_fact]
    # Matching revisions isolate the expected-absence check for a new fact.
    changed_revision = target["revision"] if changed_fact == "create" else target["revision"] + 1
    changed = {**copy.deepcopy(target), "content": "Concurrent file edit", "revision": changed_revision}
    manifest = manager._storage._get_memory_file_path(**scope)
    manifest_bytes = manifest.read_bytes()
    path = fact_file_path(manifest, changed["id"], agent_name="researcher")
    real_apply = manager._storage.apply_changes
    observed: list[dict] = []

    def apply_after_file_edit(change_set: dict, **kwargs) -> dict:
        assert not observed
        assert change_set["upsertRevisions"] == {fact_id: 2, "restored_fact": None}
        assert change_set["deleteRevisions"] == {extra_id: 1}
        # An out-of-band Markdown edit leaves the shared manifest unchanged.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_render_fact_markdown(changed))
        observed.append(manager.reload_memory(**scope))
        return real_apply(change_set, **kwargs)

    monkeypatch.setattr(manager._storage, "apply_changes", apply_after_file_edit)

    with pytest.raises(MemoryConflictError) as error:
        manager.import_memory(backup, **scope)

    assert isinstance(error.value.__cause__, MemoryFactRevisionConflict)
    assert len(observed) == 1
    assert manager.reload_memory(**scope) == observed[0]
    assert manifest.read_bytes() == manifest_bytes
    assert backup == original
