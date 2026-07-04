"""Concurrency regression tests for the skill storage singleton lifecycle.

These guard the unsynchronized check-then-create in ``get_or_new_skill_storage``
and ``get_or_new_user_skill_storage``, and the unlocked ``reset_skill_storage``:
before the lock was added, concurrent cold-start callers could each construct a
separate ``SkillStorage`` and overwrite the global, and a ``reset_skill_storage``
racing a get could hand a caller ``None``.

This mirrors ``test_sandbox_provider_lifecycle.py`` — the sibling singleton that
``skills/storage/__init__.py`` documents itself as patterned after — adapted to
the fact that ``SkillStorage`` has no teardown hook, so the fix constructs the
singleton *inside* the lock (like ``get_memory_storage``) and never builds an
orphan to clean up.

Each test resets the process-global singleton on entry and in a ``finally`` so
tests never leak storage into one another.
"""

import threading
import time
from pathlib import Path

import deerflow.skills.storage as skill_storage
from deerflow.config.paths import Paths
from deerflow.skills.storage import SkillStorage


class SlowSkillStorage(SkillStorage):
    """Storage whose constructor is slow, to widen the check-then-create gap."""

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self, **kwargs) -> None:
        super().__init__(container_path=kwargs.get("container_path", "/mnt/skills"))
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def get_skills_root_path(self) -> Path:
        return Path("/tmp/skills")

    def _iter_skill_files(self):
        return []

    def read_custom_skill(self, name: str) -> str:
        return ""

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        pass

    async def ainstall_skill_from_archive(self, archive_path) -> dict:
        return {}

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        pass

    def custom_skill_exists(self, name: str) -> bool:
        return False

    def public_skill_exists(self, name: str) -> bool:
        return False

    def append_history(self, name: str, record: dict) -> None:
        pass

    def read_history(self, name: str) -> list[dict]:
        return []


class _SkillsConfig:
    use = "SlowSkillStorage"
    container_path = "/mnt/skills"

    def get_skills_path(self) -> Path:
        return Path("/tmp/skills")


class _AppConfig:
    skills = _SkillsConfig()


# A single, stable AppConfig identity: the singleton keys its cache on the
# identity of the object returned by get_app_config(), so all threads must see
# the same instance for the singleton path to engage.
_APP_CONFIG = _AppConfig()


def _patch_storage_resolution(monkeypatch, cls=SlowSkillStorage) -> None:
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _APP_CONFIG)
    monkeypatch.setattr("deerflow.reflection.resolve_class", lambda *args, **kwargs: cls)


def test_get_or_new_skill_storage_constructs_one_singleton_under_concurrent_access(monkeypatch):
    """Eight threads racing on a cold start must construct exactly one instance.

    The fix builds the singleton inside the lock, so unlike the sandbox provider
    (which builds outside the lock and tears orphans down) no second instance is
    ever constructed — every caller observes the one that was built.
    """
    skill_storage.reset_skill_storage()
    SlowSkillStorage.instances_created = 0
    _patch_storage_resolution(monkeypatch)

    n_threads = 8
    storages: list[SkillStorage] = []
    storages_lock = threading.Lock()
    # Barrier makes all threads enter get_or_new_skill_storage() at the same
    # moment, so the race is triggered deterministically rather than by chance.
    barrier = threading.Barrier(n_threads)

    def get_storage() -> None:
        barrier.wait()
        storage = skill_storage.get_or_new_skill_storage()
        with storages_lock:
            storages.append(storage)

    threads = [threading.Thread(target=get_storage) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len({id(storage) for storage in storages}) == 1
        assert SlowSkillStorage.instances_created == 1
        installed = skill_storage.get_or_new_skill_storage()
        assert all(storage is installed for storage in storages)
    finally:
        skill_storage.reset_skill_storage()


def test_reset_racing_get_of_live_singleton_never_returns_none(monkeypatch):
    """A reset racing concurrent gets of a live singleton must never hand back
    ``None``: every returned value is a real storage instance.

    The singleton is populated before the barrier so the resetter nulls a live
    instance while the getters read it — the interleaving that the unlocked
    check-then-return path could turn into a ``None`` return.
    """
    skill_storage.reset_skill_storage()
    SlowSkillStorage.instances_created = 0
    _patch_storage_resolution(monkeypatch)

    # Populate the singleton up front so the reset races a live instance.
    skill_storage.get_or_new_skill_storage()

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        barrier.wait()
        storage = skill_storage.get_or_new_skill_storage()
        with results_lock:
            results.append(storage)

    def resetter() -> None:
        barrier.wait()
        skill_storage.reset_skill_storage()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=resetter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results, "every getter recorded a result"
        assert all(isinstance(storage, SlowSkillStorage) for storage in results)
    finally:
        skill_storage.reset_skill_storage()


# ---------------------------------------------------------------------------
# Per-user skill storage lifecycle
# ---------------------------------------------------------------------------


class SlowUserSkillStorage(SkillStorage):
    """Storage whose constructor is slow, to widen the check-then-create gap.

    Signature mirrors ``UserScopedSkillStorage.__init__(user_id, **kwargs)``
    so the module-level factory can call it as ``cls(user_id, **kwargs)``.
    """

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self, user_id: str = "default", **kwargs) -> None:
        super().__init__(container_path=kwargs.get("container_path", "/mnt/skills"))
        self._user_id = user_id
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def get_skills_root_path(self) -> Path:
        return Path("/tmp/skills")

    def _iter_skill_files(self):
        return []

    def read_custom_skill(self, name: str) -> str:
        return ""

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        pass

    async def ainstall_skill_from_archive(self, archive_path) -> dict:
        return {}

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        pass

    def custom_skill_exists(self, name: str) -> bool:
        return False

    def public_skill_exists(self, name: str) -> bool:
        return False

    def append_history(self, name: str, record: dict) -> None:
        pass

    def read_history(self, name: str) -> list[dict]:
        return []


def _patch_user_storage_resolution(monkeypatch, cls=SlowUserSkillStorage) -> None:
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _APP_CONFIG)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=Path("/tmp")))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    # get_or_new_user_skill_storage calls UserScopedSkillStorage(user_id, **kwargs)
    # directly — not via resolve_class. Patch the class reference in the module.
    monkeypatch.setattr("deerflow.skills.storage.UserScopedSkillStorage", cls)


def test_get_or_new_user_skill_storage_constructs_one_per_user_under_concurrent_access(monkeypatch):
    """Eight threads racing on a cold start for the same user_id must construct
    exactly one instance per user. Different user_ids get different instances.
    """
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    n_threads = 8
    storages: list[SkillStorage] = []
    storages_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def get_storage() -> None:
        barrier.wait()
        storage = skill_storage.get_or_new_user_skill_storage("alice")
        with storages_lock:
            storages.append(storage)

    threads = [threading.Thread(target=get_storage) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len({id(storage) for storage in storages}) == 1
        assert SlowUserSkillStorage.instances_created == 1
    finally:
        skill_storage.reset_skill_storage()


def test_different_users_get_different_storages(monkeypatch):
    """Concurrent calls for different user_ids must produce distinct instances."""
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    s_alice = skill_storage.get_or_new_user_skill_storage("alice")
    s_bob = skill_storage.get_or_new_user_skill_storage("bob")

    try:
        assert s_alice is not s_bob
        assert s_alice._user_id == "alice"
        assert s_bob._user_id == "bob"
    finally:
        skill_storage.reset_skill_storage()


def test_reset_user_skill_storage_only_clears_target_user(monkeypatch):
    """Resetting alice's storage must not invalidate bob's."""
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    s_alice = skill_storage.get_or_new_user_skill_storage("alice")
    s_bob = skill_storage.get_or_new_user_skill_storage("bob")

    skill_storage.reset_user_skill_storage("alice")

    # Alice's storage is gone
    s_alice_new = skill_storage.get_or_new_user_skill_storage("alice")
    assert s_alice_new is not s_alice

    # Bob's is still cached
    s_bob_cached = skill_storage.get_or_new_user_skill_storage("bob")
    assert s_bob_cached is s_bob


def test_reset_user_skill_storage_normalises_cache_key(monkeypatch):
    """reset_user_skill_storage must normalise the user_id so that the cache
    key matches the one used by get_or_new_user_skill_storage.

    Without normalisation, an IM-style user ID like ``feishu:ou_xxx`` would
    fail to clear its stale cache entry because ``get_or_new`` stores by
    ``make_safe_user_id(user_id)`` but ``reset`` would try to pop by the raw
    ID — a silent cache-invalidation failure.
    """
    from deerflow.config.paths import make_safe_user_id

    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    raw_id = "feishu:ou_abc123"
    safe_id = make_safe_user_id(raw_id)

    # Create storage via the normal flow (which normalises the key)
    s = skill_storage.get_or_new_user_skill_storage(raw_id)
    assert s._user_id == safe_id

    # Reset using the raw ID — must successfully clear the cache
    skill_storage.reset_user_skill_storage(raw_id)

    # A new storage should be created (old one was evicted)
    s_new = skill_storage.get_or_new_user_skill_storage(raw_id)
    assert s_new is not s
