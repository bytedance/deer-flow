"""File/JSON + single-fact Markdown storage contract tests."""

import copy
import gc
import hashlib
import json
import os
import shutil
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from deerflow.agents.memory import MemoryCorruptionError
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core import storage as storage_module
from deerflow.agents.memory.backends.deermem.deermem.core.paths import fact_file_path
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    FileMemoryStorage,
    MemoryFactRevisionConflict,
    MemoryManifestRevisionConflict,
    MemoryRevisionConflict,
    MemoryStorageCorruption,
    create_empty_memory,
)


@pytest.fixture
def storage(tmp_path: Path) -> FileMemoryStorage:
    return FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))


def _memory_with_fact(content: str = "Project uses Python 3.12") -> dict:
    memory = create_empty_memory()
    memory["facts"] = [
        {
            "id": "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ",
            "content": content,
            "category": "constraint",
            "topics": ["python", "runtime"],
            "confidence": 0.95,
            "createdAt": "2026-07-17T00:00:00Z",
            "source": {"type": "manual", "threadId": "thread-1"},
            "revision": 1,
        }
    ]
    return memory


def test_agent_scope_uses_fact_directories_but_one_user_memory_file(storage: FileMemoryStorage, tmp_path: Path) -> None:
    assert storage.save(_memory_with_fact("A"), "agent-a", user_id="alice")
    assert storage.save(_memory_with_fact("B"), "agent-b", user_id="alice")

    assert storage.load("agent-a", user_id="alice")["facts"][0]["content"] == "A"
    assert storage.load("agent-b", user_id="alice")["facts"][0]["content"] == "B"
    assert (tmp_path / "users" / "alice" / "memory.json").exists()
    assert not (tmp_path / "users" / "alice" / "agents" / "agent-a" / "memory.json").exists()
    assert list((tmp_path / "users" / "alice" / "agents" / "agent-a" / "facts").glob("**/*.md"))
    assert list((tmp_path / "users" / "alice" / "agents" / "agent-b" / "facts").glob("**/*.md"))


def test_thread_id_is_source_only_not_storage_bucket(storage: FileMemoryStorage) -> None:
    fact = _memory_with_fact()["facts"][0]
    assert fact["source"]["threadId"] == "thread-1"
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    assert "thread-1" not in str(memory_path)


def test_memory_json_contains_only_global_summaries_and_agent_fact_is_markdown(storage: FileMemoryStorage) -> None:
    memory = _memory_with_fact()
    memory["user"]["workContext"] = {"summary": "global profile", "updatedAt": "now"}
    assert storage.save(memory, "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    persisted = json.loads(memory_path.read_text(encoding="utf-8"))

    assert persisted["version"] == "2.0"
    assert "facts" not in persisted
    assert set(persisted) == {"version", "revision", "lastUpdated", "user", "history"}
    fact_path = fact_file_path(memory_path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a")
    text = fact_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "user_id: alice" in text
    assert "agent_name: agent-a" in text
    assert "# Project uses Python 3.12" in text


def test_load_keeps_frontend_shape_but_only_agent_load_returns_facts(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")

    global_memory = storage.load(user_id="alice")
    agent_memory = storage.load("agent-a", user_id="alice")

    assert global_memory["facts"] == []
    assert agent_memory["facts"][0]["topics"] == ["python", "runtime"]
    assert agent_memory["facts"][0]["scope"] == {"userId": "alice", "agentName": "agent-a"}


def test_agent_save_does_not_overwrite_global_summaries(storage: FileMemoryStorage) -> None:
    global_memory = create_empty_memory()
    global_memory["user"]["workContext"] = {"summary": "works remotely", "updatedAt": "global"}
    assert storage.save(global_memory, user_id="alice")

    agent_memory = storage.load("agent-a", user_id="alice")
    agent_memory["user"]["workContext"] = {"summary": "project secret", "updatedAt": "agent"}
    agent_memory["facts"] = _memory_with_fact()["facts"]
    assert storage.save(agent_memory, "agent-a", user_id="alice", expected_revision=1)

    assert storage.load(user_id="alice")["user"]["workContext"]["summary"] == "works remotely"


def test_removed_fact_is_physically_deleted(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    fact_path = fact_file_path(memory_path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a")
    assert fact_path.exists()

    empty = create_empty_memory()
    assert storage.save(empty, "agent-a", user_id="alice")
    assert not fact_path.exists()


def test_cached_document_is_not_mutable_by_caller(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    first = storage.load("agent-a", user_id="alice")
    first["facts"][0]["content"] = "mutated outside storage"
    second = storage.load("agent-a", user_id="alice")
    assert second["facts"][0]["content"] == "Project uses Python 3.12"


def test_cached_load_does_not_scan_all_fact_files(storage: FileMemoryStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    storage.load("agent-a", user_id="alice")

    def fail_fact_scan(*args, **kwargs):
        raise AssertionError("cached load scanned the agent fact directory")

    monkeypatch.setattr(storage_module, "agent_facts_directory", fail_fact_scan)

    assert storage.load("agent-a", user_id="alice")["facts"][0]["content"] == "Project uses Python 3.12"


def test_shared_json_signature_invalidates_cache_after_other_storage_writes(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path))
    first = FileMemoryStorage(config)
    second = FileMemoryStorage(config)
    assert first.save(_memory_with_fact(), "agent-a", user_id="alice")
    cached = first.load("agent-a", user_id="alice")
    changed = copy.deepcopy(cached["facts"][0])
    changed["content"] = "changed by another storage instance"

    second.apply_changes(
        {"upserts": [changed], "upsertRevisions": {changed["id"]: changed["revision"]}},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=cached["revision"],
        allow_manifest_rebase=True,
    )

    assert first.load("agent-a", user_id="alice")["facts"][0]["content"] == "changed by another storage instance"


def test_revision_invalidates_cache_when_file_metadata_signature_collides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A coarse filesystem may report the same mtime/size for two writes."""
    monkeypatch.setattr(storage_module, "_file_signature", lambda path: (1, 1))
    config = DeerMemConfig(storage_path=str(tmp_path))
    first = FileMemoryStorage(config)
    second = FileMemoryStorage(config)
    assert first.save(_memory_with_fact(), "agent-a", user_id="alice")
    cached = first.load("agent-a", user_id="alice")
    changed = copy.deepcopy(cached["facts"][0])
    changed["content"] = "same metadata, newer repository revision"

    second.apply_changes(
        {"upserts": [changed], "upsertRevisions": {changed["id"]: changed["revision"]}},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=cached["revision"],
        allow_manifest_rebase=True,
    )

    assert first.load("agent-a", user_id="alice")["facts"][0]["content"] == "same metadata, newer repository revision"


def test_fact_paths_shard_by_sha256_id_digest(tmp_path: Path) -> None:
    memory_path = tmp_path / "users" / "alice" / "memory.json"
    fact_ids = ["fact_00000000", "fact_11111111", "fact_22222222", "external-123"]

    paths = [fact_file_path(memory_path, fact_id, agent_name="agent-a") for fact_id in fact_ids]

    for fact_id, path in zip(fact_ids, paths, strict=True):
        assert path.parent.name == hashlib.sha256(fact_id.encode("utf-8")).hexdigest()[:2]
    assert len({path.parent.name for path in paths}) > 1


def test_corrupt_manifest_raises_and_is_not_treated_as_empty(storage: FileMemoryStorage) -> None:
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(MemoryStorageCorruption):
        storage.load(user_id="alice")
    assert path.read_text(encoding="utf-8") == "{broken"


def test_manifest_revision_conflict_rejects_stale_write(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    current = storage.load("agent-a", user_id="alice")
    assert current["revision"] == 1
    assert storage.save(_memory_with_fact("new"), "agent-a", user_id="alice", expected_revision=1)
    with pytest.raises(MemoryRevisionConflict):
        storage.save(_memory_with_fact("stale"), "agent-a", user_id="alice", expected_revision=1)


def test_partial_summary_patch_preserves_omitted_sibling_sections(storage: FileMemoryStorage) -> None:
    memory = create_empty_memory()
    memory["user"]["workContext"] = {"summary": "old work", "updatedAt": "old"}
    memory["user"]["personalContext"] = {"summary": "keep personal", "updatedAt": "old"}
    memory["user"]["topOfMind"] = {"summary": "keep focus", "updatedAt": "old"}
    assert storage.save(memory, user_id="alice")

    storage.apply_changes(
        {"summaries": {"user": {"workContext": {"summary": "new work", "updatedAt": "new"}}}},
        user_id="alice",
        expected_manifest_revision=1,
    )

    updated = storage.load(user_id="alice")
    assert updated["user"]["workContext"] == {"summary": "new work", "updatedAt": "new"}
    assert updated["user"]["personalContext"] == {"summary": "keep personal", "updatedAt": "old"}
    assert updated["user"]["topOfMind"] == {"summary": "keep focus", "updatedAt": "old"}


def test_storage_delegates_index_lifecycle_and_search_to_retrieval(tmp_path: Path) -> None:
    class FakeRetrieval:
        def __init__(self) -> None:
            self.upserts = []
            self.removes = []

        def upsert(self, fact, *, scope, path):
            self.upserts.append((fact["id"], scope, path))

        def remove(self, fact_id, *, scope):
            self.removes.append((fact_id, scope))

        def search(self, query, *, scopes, top_k, mode, filters):
            return [{"id": "fact-result", "score": 0.9, "query": query}]

    retrieval = FakeRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    assert scoped.save(_memory_with_fact(), "agent-a", user_id="alice")
    assert retrieval.upserts[0][1] == {"userId": "alice", "agentName": "agent-a"}
    assert scoped.search_facts("python", scopes=[{"userId": "alice", "agentName": "agent-a"}])[0]["score"] == 0.9

    assert scoped.save(create_empty_memory(), "agent-a", user_id="alice")
    assert retrieval.removes == [("fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", {"userId": "alice", "agentName": "agent-a"})]


def test_prepared_journal_restores_previous_manifest_and_fact(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact("original"), "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    fact_id = "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"
    fact_path = fact_file_path(memory_path, fact_id, agent_name="agent-a")
    operation_id = "op-recovery-test"
    recovery = memory_path.parent / ".recovery" / operation_id
    recovery.mkdir(parents=True)
    shutil.copy2(memory_path, recovery / "memory.json")
    shutil.copy2(fact_path, recovery / f"{fact_id}.md")
    relative_fact_path = fact_path.relative_to(memory_path.parent).as_posix()
    journal = {
        "operationId": operation_id,
        "state": "prepared",
        "agentName": "agent-a",
        "expectedRevision": memory["revision"],
        "nextRevision": memory["revision"] + 1,
        "factIds": [fact_id],
        "oldEntries": {fact_id: {"path": relative_fact_path}},
    }
    (memory_path.parent / ".memory.journal.json").write_text(json.dumps(journal), encoding="utf-8")
    fact_path.write_text("corrupt in-progress content", encoding="utf-8")

    loaded = storage.load("agent-a", user_id="alice")

    assert loaded["facts"][0]["content"] == "original"
    assert not (memory_path.parent / ".memory.journal.json").exists()


def test_fact_repository_applies_upsert_and_physical_delete(storage: FileMemoryStorage) -> None:
    first = storage.upsert_fact(
        _memory_with_fact()["facts"][0],
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=0,
        expected_fact_revision=None,
    )
    assert first["revision"] == 1
    assert first["complete"] is False
    assert storage.get_fact("fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", user_id="alice", agent_name="agent-a")["content"] == "Project uses Python 3.12"

    updated = copy.deepcopy(first["upsertedFacts"][0])
    updated["content"] = "Project uses Python 3.13"
    second = storage.apply_changes(
        {"upserts": [updated]},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=1,
    )
    assert second["upsertedFacts"][0]["content"] == "Project uses Python 3.13"

    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    fact_path = fact_file_path(memory_path, updated["id"], agent_name="agent-a")
    assert fact_path.exists()
    third = storage.delete_fact(
        updated["id"],
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=2,
        expected_fact_revision=second["upsertedFacts"][0]["revision"],
    )
    assert third["deletedFactIds"] == [updated["id"]]
    assert not fact_path.exists()


def test_upsert_fact_uses_separate_manifest_and_fact_revisions(storage: FileMemoryStorage) -> None:
    created = storage.upsert_fact(
        _memory_with_fact("first")["facts"][0],
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=0,
        expected_fact_revision=None,
    )
    changed = copy.deepcopy(created["upsertedFacts"][0])
    changed["content"] = "updated"

    updated = storage.upsert_fact(
        changed,
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=created["revision"],
        expected_fact_revision=changed["revision"],
    )

    assert updated["upsertedFacts"][0]["content"] == "updated"


def test_revision_conflicts_have_stable_manifest_and_fact_subtypes(storage: FileMemoryStorage) -> None:
    storage.upsert_fact(
        _memory_with_fact("first")["facts"][0],
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=0,
        expected_fact_revision=None,
    )

    with pytest.raises(MemoryManifestRevisionConflict):
        storage.apply_changes(
            {"summaries": {"user": {}, "history": {}}},
            user_id="alice",
            expected_manifest_revision=0,
        )

    with pytest.raises(MemoryFactRevisionConflict):
        storage.upsert_fact(
            _memory_with_fact("duplicate")["facts"][0],
            user_id="alice",
            agent_name="agent-a",
            expected_manifest_revision=1,
            expected_fact_revision=None,
        )


def test_search_facts_declares_and_uses_substring_fallback(storage: FileMemoryStorage) -> None:
    storage.upsert_fact(_memory_with_fact()["facts"][0], user_id="alice", agent_name="agent-a", expected_manifest_revision=0)

    results = storage.search_facts(
        "python",
        scopes=[{"userId": "alice", "agentName": "agent-a"}],
    )

    assert results[0]["fact"]["content"] == "Project uses Python 3.12"
    assert results[0]["matchType"] == "substring"
    assert storage.retrieval_status()["mode"] == "substring_fallback"
    assert "substring-fallback" in storage.capabilities()


def test_strict_scope_and_custom_manifest_filename(tmp_path: Path) -> None:
    strict = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path), strict_user_scope=True, manifest_filename="index.json"))
    with pytest.raises(ValueError, match="user_id"):
        strict.load()

    strict.upsert_fact(_memory_with_fact()["facts"][0], user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
    assert (tmp_path / "users" / "alice" / "index.json").exists()


def test_explicit_migrate_converts_legacy_json(storage: FileMemoryStorage) -> None:
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_memory_with_fact()), encoding="utf-8")
    original = path.read_bytes()

    report = storage.migrate(user_id="alice", agent_name="agent-a")

    assert report["migrated"] is True
    assert report["fromVersion"] == "1.0"
    assert report["toVersion"] == "2.0"
    assert "facts" not in json.loads(path.read_text(encoding="utf-8"))
    assert fact_file_path(path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a").exists()
    assert path.with_name("memory.json.v1.bak").read_bytes() == original


def test_explicit_migration_notifies_retrieval_adapter(tmp_path: Path) -> None:
    class RecordingRetrieval:
        def __init__(self) -> None:
            self.upserts: list[tuple[str, dict, str]] = []

        def upsert(self, fact, *, scope, path):
            self.upserts.append((fact["id"], scope, path))

        def remove(self, fact_id, *, scope):
            pass

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    retrieval = RecordingRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    path = scoped._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_memory_with_fact("legacy indexed fact")), encoding="utf-8")

    scoped.migrate(user_id="alice", agent_name="agent-a")
    scoped.migrate(user_id="alice", agent_name="agent-a")

    assert [(fact_id, scope) for fact_id, scope, _ in retrieval.upserts] == [("fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", {"userId": "alice", "agentName": "agent-a"})]
    assert retrieval.upserts[0][2].endswith("fact_01HZZZZZZZZZZZZZZZZZZZZZZZ.md")


def test_first_agent_load_removes_legacy_per_agent_memory_json(storage: FileMemoryStorage) -> None:
    user_memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = user_memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(_memory_with_fact("legacy agent fact")), encoding="utf-8")
    original = legacy_path.read_bytes()

    loaded = storage.load("agent-a", user_id="alice")

    assert loaded["facts"][0]["content"] == "legacy agent fact"
    assert not legacy_path.exists()
    assert legacy_path.with_name("memory.json.v1.bak").read_bytes() == original
    assert user_memory_path.exists()
    assert "facts" not in json.loads(user_memory_path.read_text(encoding="utf-8"))


def test_lazy_agent_migration_notifies_retrieval_adapter(tmp_path: Path) -> None:
    class RecordingRetrieval:
        def __init__(self) -> None:
            self.upserts: list[str] = []

        def upsert(self, fact, *, scope, path):
            self.upserts.append(fact["id"])

        def remove(self, fact_id, *, scope):
            pass

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    retrieval = RecordingRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    memory_path = scoped._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(_memory_with_fact("lazy indexed fact")), encoding="utf-8")

    assert scoped.load("agent-a", user_id="alice")["facts"][0]["content"] == "lazy indexed fact"
    assert retrieval.upserts == ["fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"]


def test_clear_all_migrates_and_then_removes_unread_legacy_agent_facts(storage: FileMemoryStorage) -> None:
    global_memory = create_empty_memory()
    global_memory["user"]["workContext"] = {"summary": "canonical summary", "updatedAt": "now"}
    assert storage.save(global_memory, user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy = _memory_with_fact("legacy fact must stay cleared")
    legacy["user"]["workContext"] = {"summary": "conflicting legacy summary", "updatedAt": "then"}
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    config_path = legacy_path.parent / "config.yaml"
    config_path.write_text("name: agent-a\n", encoding="utf-8")

    cleared = storage.clear_all(user_id="alice")

    assert cleared["facts"] == []
    assert not legacy_path.exists()
    assert legacy_path.with_name("memory.json.v1.bak").exists()
    assert storage.load("agent-a", user_id="alice")["facts"] == []
    assert config_path.read_text(encoding="utf-8") == "name: agent-a\n"


def test_clear_all_legacy_migration_leaves_retrieval_fact_removed(tmp_path: Path) -> None:
    class RecordingRetrieval:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def upsert(self, fact, *, scope, path):
            self.events.append(("upsert", fact["id"]))

        def remove(self, fact_id, *, scope):
            self.events.append(("remove", fact_id))

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    retrieval = RecordingRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    memory_path = scoped._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(_memory_with_fact("legacy indexed then cleared")), encoding="utf-8")

    scoped.clear_all(user_id="alice")

    assert retrieval.events == [
        ("upsert", "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"),
        ("remove", "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"),
    ]


def test_migration_rejects_a_different_existing_v1_backup(storage: FileMemoryStorage) -> None:
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_memory_with_fact("source v1")), encoding="utf-8")
    original = path.read_bytes()
    path.with_name("memory.json.v1.bak").write_text(json.dumps(_memory_with_fact("older different v1")), encoding="utf-8")

    with pytest.raises(MemoryStorageCorruption, match="migration backup"):
        storage.migrate(user_id="alice", agent_name="agent-a")

    assert path.read_bytes() == original
    assert not fact_file_path(path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a").exists()


def test_migration_does_not_modify_v1_source_when_backup_write_fails(
    storage: FileMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_memory_with_fact("source v1")), encoding="utf-8")
    original = path.read_bytes()
    real_atomic_write = storage_module._atomic_write

    def fail_backup(path_to_write: Path, raw: bytes) -> None:
        if path_to_write.name.endswith(".v1.bak"):
            raise OSError("backup disk unavailable")
        real_atomic_write(path_to_write, raw)

    monkeypatch.setattr(storage_module, "_atomic_write", fail_backup)

    with pytest.raises(OSError, match="backup disk unavailable"):
        storage.migrate(user_id="alice", agent_name="agent-a")

    assert path.read_bytes() == original
    assert not fact_file_path(path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a").exists()


def test_fact_repository_requires_agent_name(storage: FileMemoryStorage) -> None:
    with pytest.raises(ValueError, match="agent_name"):
        storage.upsert_fact(_memory_with_fact()["facts"][0], user_id="alice", expected_manifest_revision=0)


def test_full_save_rejects_non_object_facts_without_deleting_existing(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact("keep me"), "agent-a", user_id="alice")
    invalid = storage.load("agent-a", user_id="alice")
    invalid["facts"] = [None]

    assert storage.save(invalid, "agent-a", user_id="alice", expected_revision=1) is False
    assert storage.load("agent-a", user_id="alice")["facts"][0]["content"] == "keep me"


def test_agent_full_save_requires_facts_field_without_deleting_existing(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact("keep me"), "agent-a", user_id="alice")

    assert storage.save({"user": {}, "history": {}}, "agent-a", user_id="alice", expected_revision=1) is False
    assert storage.load("agent-a", user_id="alice")["facts"][0]["content"] == "keep me"


def test_legacy_agent_migration_merges_existing_canonical_facts(storage: FileMemoryStorage) -> None:
    canonical = _memory_with_fact("canonical")
    canonical["facts"][0]["id"] = "fact_canonical"
    assert storage.save(canonical, "agent-a", user_id="alice")

    legacy = _memory_with_fact("legacy")
    legacy["facts"][0]["id"] = "fact_legacy"
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = storage.load("agent-a", user_id="alice")

    assert {fact["content"] for fact in loaded["facts"]} == {"canonical", "legacy"}


def test_legacy_agent_migration_rejects_same_id_content_conflict(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact("canonical"), "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.write_text(json.dumps(_memory_with_fact("conflicting legacy")), encoding="utf-8")

    with pytest.raises(MemoryStorageCorruption, match="migration conflict"):
        storage.load("agent-a", user_id="alice")

    legacy_path.unlink()
    assert storage.reload("agent-a", user_id="alice")["facts"][0]["content"] == "canonical"


def test_concurrent_legacy_agent_migration_is_idempotent(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path))
    first = FileMemoryStorage(config)
    second = FileMemoryStorage(config)
    memory_path = first._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(_memory_with_fact("legacy")), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        loaded = list(pool.map(lambda store: store.load("agent-a", user_id="alice"), (first, second)))

    assert all([fact["content"] for fact in document["facts"]] == ["legacy"] for document in loaded)
    assert not legacy_path.exists()


def test_default_manager_read_auto_migrates_global_legacy_facts(storage: FileMemoryStorage, tmp_path: Path) -> None:
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    legacy = _memory_with_fact("old global fact")
    legacy["user"]["workContext"] = {"summary": "keep global profile", "updatedAt": "2026-01-01T00:00:00Z"}
    path.write_text(json.dumps(legacy), encoding="utf-8")

    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    loaded = manager.get_memory(user_id="alice")
    loaded_again = manager.reload_memory(user_id="alice")

    assert [fact["content"] for fact in loaded["facts"]] == ["old global fact"]
    assert [fact["content"] for fact in loaded_again["facts"]] == ["old global fact"]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "facts" not in persisted
    assert persisted["user"]["workContext"]["summary"] == "keep global profile"
    assert fact_file_path(path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="__default__").exists()


@pytest.mark.parametrize("custom_first", [True, False])
def test_default_bucket_is_isolated_from_custom_lead_agent(tmp_path: Path, custom_first: bool) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    custom_dir = tmp_path / "users" / "alice" / "agents" / "lead-agent"
    custom_dir.mkdir(parents=True)
    (custom_dir / "config.yaml").write_text("name: lead-agent\n", encoding="utf-8")

    if custom_first:
        manager.create_fact("custom fact", agent_name="lead-agent", user_id="alice")
        manager.create_fact("default fact", user_id="alice")
    else:
        manager.create_fact("default fact", user_id="alice")
        manager.create_fact("custom fact", agent_name="lead-agent", user_id="alice")

    assert [fact["content"] for fact in manager.get_memory(user_id="alice")["facts"]] == ["default fact"]
    assert [fact["content"] for fact in manager.get_memory(agent_name="lead-agent", user_id="alice")["facts"]] == ["custom fact"]
    assert list((tmp_path / "users" / "alice" / "agents" / "__default__" / "facts").glob("**/*.md"))
    assert list((tmp_path / "users" / "alice" / "agents" / "lead-agent" / "facts").glob("**/*.md"))


def test_deermem_canonicalizes_agent_names_to_lowercase(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})

    manager.create_fact("case-insensitive fact", agent_name="Lead-Agent", user_id="alice")

    lower = manager.get_memory(agent_name="lead-agent", user_id="alice")
    upper = manager.get_memory(agent_name="LEAD-AGENT", user_id="alice")
    stored = manager._storage.load("lead-agent", user_id="alice")["facts"][0]
    assert [fact["id"] for fact in lower["facts"]] == [fact["id"] for fact in upper["facts"]]
    assert stored["scope"]["agentName"] == "lead-agent"


def test_old_implicit_lead_agent_bucket_moves_to_reserved_default(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path))
    old_storage = FileMemoryStorage(config)
    old_storage.upsert_fact(
        _memory_with_fact("fact written by the previous PR version")["facts"][0],
        user_id="alice",
        agent_name="lead-agent",
        expected_manifest_revision=0,
    )

    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    loaded = manager.get_memory(user_id="alice")

    assert [fact["content"] for fact in loaded["facts"]] == ["fact written by the previous PR version"]
    assert not (tmp_path / "users" / "alice" / "agents" / "lead-agent").exists()
    assert list((tmp_path / "users" / "alice" / "agents" / "__default__" / "facts").glob("**/*.md"))


def test_old_implicit_bucket_with_unknown_files_is_preserved(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "users" / "alice" / "agents" / "lead-agent"
    legacy_dir.mkdir(parents=True)
    unknown = legacy_dir / "SOUL.md"
    unknown.write_text("possibly a partially created custom agent", encoding="utf-8")
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})

    with pytest.raises(MemoryCorruptionError, match="unexpected entries"):
        manager.get_memory(user_id="alice")

    assert unknown.read_text(encoding="utf-8") == "possibly a partially created custom agent"


def test_create_returns_fresh_full_view_after_disjoint_rebase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    competing_storage = FileMemoryStorage(manager._config)
    real_apply_changes = manager._storage.apply_changes
    injected = False

    def apply_with_competing_create(change_set, **scope):
        nonlocal injected
        if not injected:
            injected = True
            competing_fact = _memory_with_fact("competing fact")["facts"][0]
            competing_fact["id"] = "fact_competing"
            competing_storage.apply_changes(
                {"upserts": [competing_fact], "upsertRevisions": {"fact_competing": None}},
                agent_name=scope["agent_name"],
                user_id=scope["user_id"],
                expected_manifest_revision=scope["expected_manifest_revision"],
            )
        return real_apply_changes(change_set, **scope)

    monkeypatch.setattr(manager._storage, "apply_changes", apply_with_competing_create)

    returned, created_id = manager.create_fact("requested fact", user_id="alice")
    fresh = manager.reload_memory(user_id="alice")

    assert created_id is not None
    assert {fact["id"] for fact in returned["facts"]} == {fact["id"] for fact in fresh["facts"]}
    assert {fact["content"] for fact in returned["facts"]} == {"competing fact", "requested fact"}


def test_scoped_clear_recomputes_after_competing_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    manager.create_fact("existing fact", agent_name="agent-a", user_id="alice")
    competing_storage = FileMemoryStorage(manager._config)
    real_apply_changes = manager._storage.apply_changes
    injected = False

    def apply_with_competing_create(change_set, **scope):
        nonlocal injected
        if not injected:
            injected = True
            competing_fact = _memory_with_fact("competing fact")["facts"][0]
            competing_fact.update({"id": "fact_competing", "revision": 1})
            competing_storage.apply_changes(
                {"upserts": [competing_fact], "upsertRevisions": {"fact_competing": None}},
                agent_name=scope["agent_name"],
                user_id=scope["user_id"],
                expected_manifest_revision=scope["expected_manifest_revision"],
            )
        return real_apply_changes(change_set, **scope)

    monkeypatch.setattr(manager._storage, "apply_changes", apply_with_competing_create)

    returned = manager.clear_memory(agent_name="agent-a", user_id="alice")
    fresh = manager.reload_memory(agent_name="agent-a", user_id="alice")

    assert returned["facts"] == []
    assert fresh["facts"] == []


def test_max_facts_is_recomputed_after_competing_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "max_facts": 10})
    initial = create_empty_memory()
    initial["facts"] = []
    for index in range(9):
        fact = copy.deepcopy(_memory_with_fact(f"existing {index}")["facts"][0])
        fact.update({"id": f"fact_existing_{index}", "confidence": 0.9})
        initial["facts"].append(fact)
    assert manager._storage.save(initial, "agent-a", user_id="alice")

    competing_storage = FileMemoryStorage(manager._config)
    real_apply_changes = manager._storage.apply_changes
    injected = False

    def apply_with_competing_create(change_set, **scope):
        nonlocal injected
        if not injected:
            injected = True
            competing_fact = copy.deepcopy(_memory_with_fact("competing fact")["facts"][0])
            competing_fact.update({"id": "fact_competing", "confidence": 0.9})
            competing_storage.apply_changes(
                {"upserts": [competing_fact], "upsertRevisions": {"fact_competing": None}},
                agent_name=scope["agent_name"],
                user_id=scope["user_id"],
                expected_manifest_revision=scope["expected_manifest_revision"],
            )
        return real_apply_changes(change_set, **scope)

    monkeypatch.setattr(manager._storage, "apply_changes", apply_with_competing_create)

    returned, created_id = manager.create_fact(
        "requested fact",
        confidence=0.95,
        agent_name="agent-a",
        user_id="alice",
    )
    fresh = manager.reload_memory(agent_name="agent-a", user_id="alice")

    assert created_id is not None
    assert len(returned["facts"]) <= 10
    assert len(fresh["facts"]) <= 10
    assert {fact["id"] for fact in returned["facts"]} == {fact["id"] for fact in fresh["facts"]}


def test_agent_fact_scope_must_match_requested_directory(storage: FileMemoryStorage) -> None:
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    fact_path = fact_file_path(memory_path, "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ", agent_name="agent-a")
    fact_path.write_text(fact_path.read_text(encoding="utf-8").replace("agent_name: agent-a", "agent_name: agent-b"), encoding="utf-8")

    with pytest.raises(MemoryStorageCorruption, match="scope mismatch"):
        storage.reload("agent-a", user_id="alice")


def test_legacy_fact_path_must_remain_below_user_directory(storage: FileMemoryStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("do not read", encoding="utf-8")
    path = storage._get_memory_file_path(user_id="alice")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": "2.0",
                "revision": 0,
                "user": {},
                "history": {},
                "facts": {"fact_escape": {"path": "../../outside.md"}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MemoryStorageCorruption, match="escapes"):
        storage.migrate(user_id="alice", agent_name="agent-a")


def test_fact_schema_rejects_invalid_collection_and_revision_types(storage: FileMemoryStorage) -> None:
    invalid_topics = _memory_with_fact()["facts"][0]
    invalid_topics["topics"] = "python"
    with pytest.raises(ValueError, match="topics"):
        storage.upsert_fact(invalid_topics, user_id="alice", agent_name="agent-a", expected_manifest_revision=0)

    invalid_revision = _memory_with_fact()["facts"][0]
    invalid_revision["revision"] = []
    with pytest.raises(ValueError, match="revision"):
        storage.upsert_fact(invalid_revision, user_id="alice", agent_name="agent-a", expected_manifest_revision=0)


def test_changed_fact_increments_revision_and_updated_at(storage: FileMemoryStorage) -> None:
    created = storage.upsert_fact(_memory_with_fact()["facts"][0], user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
    original = created["upsertedFacts"][0]
    updated = copy.deepcopy(original)
    updated["content"] = "Project uses Python 3.13"

    result = storage.apply_changes({"upserts": [updated]}, user_id="alice", agent_name="agent-a", expected_manifest_revision=1)
    changed = result["upsertedFacts"][0]

    assert changed["revision"] == original["revision"] + 1
    assert changed["updatedAt"] > original["updatedAt"]
    assert changed["createdAt"] == original["createdAt"]


def test_single_fact_change_writes_and_notifies_only_that_fact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingRetrieval:
        def __init__(self) -> None:
            self.upserts: list[str] = []

        def upsert(self, fact, *, scope, path):
            self.upserts.append(fact["id"])

        def remove(self, fact_id, *, scope):
            pass

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    retrieval = RecordingRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    memory = create_empty_memory()
    first = _memory_with_fact("first")["facts"][0]
    second = copy.deepcopy(first)
    second.update({"id": "fact_second", "content": "second"})
    memory["facts"] = [first, second]
    assert scoped.save(memory, "agent-a", user_id="alice")
    retrieval.upserts.clear()

    markdown_writes: list[Path] = []
    real_atomic_write = storage_module._atomic_write

    def record_atomic_write(path: Path, raw: bytes) -> None:
        if path.suffix == ".md":
            markdown_writes.append(path)
        real_atomic_write(path, raw)

    monkeypatch.setattr(storage_module, "_atomic_write", record_atomic_write)
    loaded = scoped.load("agent-a", user_id="alice")
    changed = copy.deepcopy(next(fact for fact in loaded["facts"] if fact["id"] == first["id"]))
    changed["content"] = "first changed"

    scoped.apply_changes({"upserts": [changed]}, user_id="alice", agent_name="agent-a", expected_manifest_revision=1)

    assert [path.stem for path in markdown_writes] == [first["id"]]
    assert retrieval.upserts == [first["id"]]


def test_incremental_change_does_not_scan_all_fact_files(storage: FileMemoryStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    memory = create_empty_memory()
    first = _memory_with_fact("first")["facts"][0]
    second = copy.deepcopy(first)
    second.update({"id": "fact_second", "content": "second"})
    memory["facts"] = [first, second]
    assert storage.save(memory, "agent-a", user_id="alice")
    changed = copy.deepcopy(storage.get_fact(first["id"], user_id="alice", agent_name="agent-a"))
    changed["content"] = "first changed"

    def fail_full_scan(*args, **kwargs):
        raise AssertionError("incremental change attempted to scan all facts")

    monkeypatch.setattr(storage, "_load_agent_facts", fail_full_scan)
    result = storage.apply_changes(
        {"upserts": [changed]},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=1,
    )

    assert result["complete"] is False
    assert [fact["id"] for fact in result["upsertedFacts"]] == [first["id"]]
    assert result["upsertedFacts"][0]["content"] == "first changed"


def test_fresh_storage_incremental_result_does_not_hide_untouched_sibling(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path))
    writer = FileMemoryStorage(config)
    memory = create_empty_memory()
    first = _memory_with_fact("first")["facts"][0]
    second = copy.deepcopy(first)
    second.update({"id": "fact_second", "content": "second"})
    memory["facts"] = [first, second]
    assert writer.save(memory, "agent-a", user_id="alice")

    fresh = FileMemoryStorage(config)
    changed = copy.deepcopy(fresh.get_fact(first["id"], user_id="alice", agent_name="agent-a"))
    changed["content"] = "first changed"
    result = fresh.apply_changes(
        {"upserts": [changed]},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=1,
    )

    assert result["complete"] is False
    assert [fact["id"] for fact in result["upsertedFacts"]] == [first["id"]]
    reloaded = fresh.load("agent-a", user_id="alice")
    assert {fact["content"] for fact in reloaded["facts"]} == {"first changed", "second"}


def test_stale_user_revision_rebases_disjoint_fact_change_but_not_same_fact(storage: FileMemoryStorage) -> None:
    memory = create_empty_memory()
    first = _memory_with_fact("first")["facts"][0]
    second = copy.deepcopy(first)
    second.update({"id": "fact_second", "content": "second"})
    memory["facts"] = [first, second]
    assert storage.save(memory, "agent-a", user_id="alice")
    snapshot = storage.load("agent-a", user_id="alice")
    first_update = copy.deepcopy(next(fact for fact in snapshot["facts"] if fact["id"] == first["id"]))
    second_update = copy.deepcopy(next(fact for fact in snapshot["facts"] if fact["id"] == second["id"]))
    first_update["content"] = "first changed"
    second_update["content"] = "second changed"

    storage.apply_changes({"upserts": [first_update]}, user_id="alice", agent_name="agent-a", expected_manifest_revision=1)
    rebased = storage.apply_changes(
        {"upserts": [second_update]},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=1,
        allow_manifest_rebase=True,
    )
    assert [fact["content"] for fact in rebased["upsertedFacts"]] == ["second changed"]
    assert {fact["content"] for fact in storage.load("agent-a", user_id="alice")["facts"]} == {"first changed", "second changed"}

    first_update["content"] = "stale overwrite"
    with pytest.raises(MemoryRevisionConflict):
        storage.apply_changes(
            {"upserts": [first_update]},
            user_id="alice",
            agent_name="agent-a",
            expected_manifest_revision=1,
            allow_manifest_rebase=True,
        )


def test_rebuild_index_continues_after_adapter_exception(tmp_path: Path) -> None:
    class FlakyRetrieval:
        def upsert(self, fact, *, scope, path):
            if fact["id"] == "fact_bad":
                raise RuntimeError("index unavailable")

        def remove(self, fact_id, *, scope):
            pass

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=FlakyRetrieval())
    memory = create_empty_memory()
    good = _memory_with_fact("good")["facts"][0]
    bad = copy.deepcopy(good)
    bad.update({"id": "fact_bad", "content": "bad"})
    memory["facts"] = [good, bad]
    assert scoped.save(memory, "agent-a", user_id="alice")

    result = scoped.rebuild_index([{"userId": "alice", "agentName": "agent-a"}])

    assert result == {"supported": True, "indexed": 1, "failed": 1}


def test_full_rebuild_index_accepts_original_email_user_scope(tmp_path: Path) -> None:
    class RecordingRetrieval:
        def __init__(self) -> None:
            self.fact_ids: list[str] = []

        def upsert(self, fact, *, scope, path):
            self.fact_ids.append(fact["id"])

        def remove(self, fact_id, *, scope):
            pass

        def search(self, query, *, scopes, top_k, mode, filters):
            return []

    retrieval = RecordingRetrieval()
    scoped = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)
    scoped.upsert_fact(
        _memory_with_fact("email user fact")["facts"][0],
        user_id="test@example.com",
        agent_name="agent-a",
        expected_manifest_revision=0,
        expected_fact_revision=None,
    )
    retrieval.fact_ids.clear()

    result = scoped.rebuild_index()

    assert result == {"supported": True, "indexed": 1, "failed": 0}
    assert retrieval.fact_ids == ["fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"]


def test_scope_lock_cache_releases_unused_entries(storage: FileMemoryStorage) -> None:
    key = storage._cache_key("agent-a", user_id="alice")
    lock = storage._scope_lock(key)
    lock_ref = weakref.ref(lock)
    del lock
    gc.collect()

    assert lock_ref() is None
    assert key not in storage._scope_locks


def test_atomic_write_syncs_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[Path] = []
    monkeypatch.setattr(storage_module, "_fsync_parent_directory", lambda path: synced.append(path))
    target = tmp_path / "nested" / "memory.json"

    storage_module._atomic_write(target, b"{}")

    assert synced == [target.parent]


def test_migrate_reports_legacy_agent_file(storage: FileMemoryStorage) -> None:
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(_memory_with_fact("legacy")), encoding="utf-8")

    report = storage.migrate(user_id="alice", agent_name="agent-a")

    assert report["migrated"] is True
    assert not legacy_path.exists()


def test_migrate_preserves_legacy_summaries_before_deleting_agent_file(storage: FileMemoryStorage) -> None:
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy = _memory_with_fact("legacy")
    legacy["user"]["workContext"] = {"summary": "legacy profile", "updatedAt": "2026-01-01T00:00:00Z"}
    legacy["history"]["recentMonths"] = {"summary": "legacy history", "updatedAt": "2026-01-01T00:00:00Z"}
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

    storage.migrate(user_id="alice", agent_name="agent-a")

    global_memory = storage.load(user_id="alice")
    assert global_memory["user"]["workContext"]["summary"] == "legacy profile"
    assert global_memory["history"]["recentMonths"]["summary"] == "legacy history"
    assert not legacy_path.exists()


def test_migrate_keeps_legacy_file_when_summary_conflicts(storage: FileMemoryStorage) -> None:
    global_memory = create_empty_memory()
    global_memory["user"]["workContext"] = {"summary": "canonical profile", "updatedAt": "now"}
    assert storage.save(global_memory, user_id="alice")
    memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
    legacy_path = memory_path.parent / "agents" / "agent-a" / "memory.json"
    legacy_path.parent.mkdir(parents=True)
    legacy = _memory_with_fact("legacy")
    legacy["user"]["workContext"] = {"summary": "different profile", "updatedAt": "then"}
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.raises(MemoryStorageCorruption, match="summary migration conflict"):
        storage.migrate(user_id="alice", agent_name="agent-a")

    assert legacy_path.exists()
    assert not fact_file_path(memory_path, legacy["facts"][0]["id"], agent_name="agent-a").exists()


def test_two_storage_instances_cannot_create_the_same_fact_id(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path))
    first_storage = FileMemoryStorage(config)
    second_storage = FileMemoryStorage(config)
    new_fact = _memory_with_fact("first writer")["facts"][0]
    new_fact.pop("revision")

    first_storage.apply_changes(
        {"upserts": [copy.deepcopy(new_fact)]},
        user_id="alice",
        agent_name="agent-a",
        expected_manifest_revision=0,
    )
    competing = copy.deepcopy(new_fact)
    competing["content"] = "second writer"

    with pytest.raises(MemoryRevisionConflict, match="must not already exist"):
        second_storage.apply_changes(
            {"upserts": [competing]},
            user_id="alice",
            agent_name="agent-a",
            expected_manifest_revision=0,
            allow_manifest_rebase=True,
        )

    stored = first_storage.get_fact(new_fact["id"], user_id="alice", agent_name="agent-a")
    assert stored["content"] == "first writer"


def test_stale_summary_change_is_not_rebased_over_newer_summary(storage: FileMemoryStorage) -> None:
    newer = create_empty_memory()
    newer["user"]["workContext"] = {"summary": "newer", "updatedAt": "now"}
    assert storage.save(newer, user_id="alice", expected_revision=0)
    stale = create_empty_memory()
    stale["user"]["workContext"] = {"summary": "stale", "updatedAt": "before"}
    fact = _memory_with_fact("should not be committed")["facts"][0]
    fact.pop("revision")

    with pytest.raises(MemoryRevisionConflict):
        storage.apply_changes(
            {"upserts": [fact], "upsertRevisions": {fact["id"]: None}, "summaries": {"user": stale["user"], "history": stale["history"]}},
            user_id="alice",
            agent_name="agent-a",
            expected_manifest_revision=0,
        )

    assert storage.load(user_id="alice")["user"]["workContext"]["summary"] == "newer"
    assert not fact_file_path(storage._get_memory_file_path("agent-a", user_id="alice"), fact["id"], agent_name="agent-a").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows append-mode lock behavior")
def test_windows_lock_file_does_not_grow_per_acquisition(storage: FileMemoryStorage) -> None:
    for _ in range(5):
        assert storage.save(create_empty_memory(), user_id="alice")
    lock_path = storage._get_memory_file_path(user_id="alice").parent / ".memory.lock"
    assert lock_path.stat().st_size == 1
