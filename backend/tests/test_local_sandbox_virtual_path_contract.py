"""Issue #2873 regression — the public Sandbox API must honor the documented
/mnt/user-data contract uniformly across implementations.

Today AIO sandbox already accepts /mnt/user-data/... paths directly because the
container has those paths bind-mounted per-thread. LocalSandbox, however,
externalises that translation to ``deerflow.sandbox.tools`` via ``thread_data``,
so any caller that bypasses tools.py (e.g. ``uploads.py`` syncing files into a
remote sandbox via ``sandbox.update_file(virtual_path, ...)``) sees inconsistent
behaviour.

These tests pin down the **public Sandbox API boundary**: when a caller obtains
a ``LocalSandbox`` from ``LocalSandboxProvider.acquire(thread_id)`` and invokes
its abstract methods with documented virtual paths, those paths must resolve to
the thread's user-data directory automatically — no tools.py / thread_data
shim required.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider


def _build_config(skills_dir: Path) -> SimpleNamespace:
    """Minimal app config covering what ``LocalSandboxProvider`` reads at init."""
    return SimpleNamespace(
        skills=SimpleNamespace(
            container_path="/mnt/skills",
            get_skills_path=lambda: skills_dir,
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider", mounts=[]),
    )


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """Redirect ``get_paths().base_dir`` to ``tmp_path`` and reset its singleton.

    Without this, per-thread directories would be created under the developer's
    real ``.deer-flow/`` tree.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    yield tmp_path
    monkeypatch.setattr(paths_module, "_paths", None)


@pytest.fixture
def provider(isolated_paths, tmp_path):
    """Provider with a real skills dir and no custom mounts."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)
    with patch("deerflow.config.get_app_config", return_value=cfg):
        yield LocalSandboxProvider()


# ──────────────────────────────────────────────────────────────────────────
# 1. Direct Sandbox API accepts the virtual path contract for ``acquire(tid)``
# ──────────────────────────────────────────────────────────────────────────


def test_acquire_with_thread_id_returns_per_thread_id(provider):
    sandbox_id = provider.acquire("alpha")
    assert sandbox_id == "local:alpha"


def test_acquire_without_thread_id_remains_legacy_local_id(provider):
    """Backward-compat: ``acquire()`` with no thread keeps the singleton id."""
    assert provider.acquire() == "local"
    assert provider.acquire(None) == "local"


def test_write_then_read_via_public_api_with_virtual_path(provider):
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    assert sbx is not None

    virtual = "/mnt/user-data/workspace/hello.txt"
    sbx.write_file(virtual, "hi there")
    assert sbx.read_file(virtual) == "hi there"


def test_list_dir_via_public_api_with_virtual_path(provider):
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/workspace/foo.txt", "x")
    entries = sbx.list_dir("/mnt/user-data/workspace")
    # entries should be reverse-resolved back to the virtual prefix
    assert any("/mnt/user-data/workspace/foo.txt" in e for e in entries)


def test_execute_command_with_virtual_path(provider):
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/uploads/note.txt", "payload")
    output = sbx.execute_command("ls /mnt/user-data/uploads")
    assert "note.txt" in output


def test_glob_with_virtual_path(provider):
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/outputs/report.md", "# r")
    matches, _ = sbx.glob("/mnt/user-data/outputs", "*.md")
    assert any(m.endswith("/mnt/user-data/outputs/report.md") for m in matches)


def test_grep_with_virtual_path(provider):
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/workspace/findme.txt", "needle line\nother line")
    matches, _ = sbx.grep("/mnt/user-data/workspace", "needle", literal=True)
    assert matches
    assert matches[0].path.endswith("/mnt/user-data/workspace/findme.txt")


def test_execute_command_lists_aggregate_user_data_root(provider):
    """``ls /mnt/user-data`` (the parent prefix itself) must list the three
    subdirs — matching the AIO container's natural filesystem view."""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    # Touch all three subdirs so they materialise on disk
    sbx.write_file("/mnt/user-data/workspace/.keep", "")
    sbx.write_file("/mnt/user-data/uploads/.keep", "")
    sbx.write_file("/mnt/user-data/outputs/.keep", "")
    output = sbx.execute_command("ls /mnt/user-data")
    assert "workspace" in output
    assert "uploads" in output
    assert "outputs" in output


def test_update_file_with_virtual_path_for_remote_sync_scenario(provider):
    """This is the exact code path used by ``uploads.py:282`` and ``feishu.py:389``.

    They build a ``virtual_path`` like ``/mnt/user-data/uploads/foo.pdf`` and hand
    raw bytes to the sandbox. Before this fix LocalSandbox would try to write to
    the literal host path ``/mnt/user-data/uploads/foo.pdf`` and fail.
    """
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.update_file("/mnt/user-data/uploads/blob.bin", b"\x00\x01\x02binary")
    assert sbx.read_file("/mnt/user-data/uploads/blob.bin").startswith("\x00\x01\x02")


# ──────────────────────────────────────────────────────────────────────────
# 2. Per-thread isolation (no cross-thread state leaks)
# ──────────────────────────────────────────────────────────────────────────


def test_two_threads_get_distinct_sandboxes(provider):
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    assert sid_a != sid_b

    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)
    assert sbx_a is not sbx_b


def test_per_thread_user_data_mapping_isolated(provider, isolated_paths):
    """Files written via one thread's sandbox must not be visible through another."""
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)

    sbx_a.write_file("/mnt/user-data/workspace/secret.txt", "alpha-only")
    # The same virtual path resolves to a different host path in thread "beta"
    with pytest.raises(FileNotFoundError):
        sbx_b.read_file("/mnt/user-data/workspace/secret.txt")


def test_agent_written_paths_per_thread_isolation(provider):
    """``_agent_written_paths`` tracks files this sandbox wrote so reverse-resolve
    runs on read. The set must not leak across threads."""
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)
    sbx_a.write_file("/mnt/user-data/workspace/in-a.txt", "marker")
    assert sbx_a._agent_written_paths
    assert not sbx_b._agent_written_paths


# ──────────────────────────────────────────────────────────────────────────
# 3. Lifecycle: get / release / reset
# ──────────────────────────────────────────────────────────────────────────


def test_get_returns_cached_instance_for_known_id(provider):
    sid = provider.acquire("alpha")
    assert provider.get(sid) is provider.get(sid)


def test_get_unknown_id_returns_none(provider):
    assert provider.get("local:nonexistent") is None


def test_release_is_noop_keeps_instance_available(provider):
    """Local has no resources to release; the cached instance stays alive across
    turns so ``_agent_written_paths`` persists for reverse-resolve on later reads."""
    sid = provider.acquire("alpha")
    sbx_before = provider.get(sid)
    provider.release(sid)
    sbx_after = provider.get(sid)
    assert sbx_before is sbx_after


def test_reset_clears_both_generic_and_per_thread_caches(provider):
    provider.acquire()  # populate generic
    provider.acquire("alpha")  # populate per-thread
    assert provider._generic_sandbox is not None
    assert provider._thread_sandboxes

    provider.reset()
    assert provider._generic_sandbox is None
    assert not provider._thread_sandboxes


# ──────────────────────────────────────────────────────────────────────────
# 4. is_local_sandbox detects both legacy and per-thread ids
# ──────────────────────────────────────────────────────────────────────────


def test_is_local_sandbox_accepts_both_id_formats():
    from deerflow.sandbox.tools import is_local_sandbox

    legacy = SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}}, context={})
    per_thread = SimpleNamespace(state={"sandbox": {"sandbox_id": "local:alpha"}}, context={})
    foreign = SimpleNamespace(state={"sandbox": {"sandbox_id": "aio-12345"}}, context={})
    unset = SimpleNamespace(state={}, context={})

    assert is_local_sandbox(legacy) is True
    assert is_local_sandbox(per_thread) is True
    assert is_local_sandbox(foreign) is False
    assert is_local_sandbox(unset) is False


# ──────────────────────────────────────────────────────────────────────────
# 5. Concurrency safety (Copilot review feedback)
# ──────────────────────────────────────────────────────────────────────────


def test_concurrent_acquire_same_thread_yields_single_instance(provider):
    """Two threads racing on ``acquire("alpha")`` must share one LocalSandbox.

    Without the provider lock the check-then-act in ``acquire`` is non-atomic:
    both racers would see an empty cache, both would build their own
    LocalSandbox, and one would overwrite the other — losing the loser's
    ``_agent_written_paths`` and any in-flight state on it.
    """
    import threading
    import time

    from deerflow.sandbox.local import local_sandbox as local_sandbox_module

    # Force a wide race window by slowing the LocalSandbox constructor down.
    original_init = local_sandbox_module.LocalSandbox.__init__

    def slow_init(self, *args, **kwargs):
        time.sleep(0.05)
        original_init(self, *args, **kwargs)

    barrier = threading.Barrier(8)
    results: list[str] = []
    results_lock = threading.Lock()

    def racer():
        barrier.wait()
        sid = provider.acquire("alpha")
        with results_lock:
            results.append(sid)

    with patch.object(local_sandbox_module.LocalSandbox, "__init__", slow_init):
        threads = [threading.Thread(target=racer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # Every racer must observe the same ``sandbox_id``…
    assert len(set(results)) == 1, f"Racers saw different ids: {results}"
    # …and the cache must hold exactly one instance for ``alpha``.
    assert len(provider._thread_sandboxes) == 1
    assert "alpha" in provider._thread_sandboxes


def test_concurrent_acquire_distinct_threads_yields_distinct_instances(provider):
    """Different thread_ids race-acquired in parallel each get their own sandbox."""
    import threading

    barrier = threading.Barrier(6)
    sids: dict[str, str] = {}
    lock = threading.Lock()

    def racer(name: str):
        barrier.wait()
        sid = provider.acquire(name)
        with lock:
            sids[name] = sid

    threads = [threading.Thread(target=racer, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(sids.values()) == {f"local:t{i}" for i in range(6)}
    assert set(provider._thread_sandboxes.keys()) == {f"t{i}" for i in range(6)}


# ──────────────────────────────────────────────────────────────────────────
# 6. Bounded memory growth (Copilot review feedback)
# ──────────────────────────────────────────────────────────────────────────


def test_thread_sandbox_cache_is_bounded(isolated_paths, tmp_path):
    """The LRU cap must evict the least-recently-used thread sandboxes once
    exceeded — otherwise long-running gateways would accumulate cache entries
    for every distinct ``thread_id`` ever served."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)

    with patch("deerflow.config.get_app_config", return_value=cfg):
        provider = LocalSandboxProvider(max_cached_threads=3)

    for i in range(5):
        provider.acquire(f"t{i}")

    # Only the 3 most-recent thread_ids should be retained.
    assert set(provider._thread_sandboxes.keys()) == {"t2", "t3", "t4"}
    assert provider.get("local:t0") is None
    assert provider.get("local:t4") is not None


def test_lru_promotes_recently_used_thread(isolated_paths, tmp_path):
    """``get`` on a cached thread should mark it as most-recently used so a
    later acquire-storm doesn't evict an active thread that is being polled."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)

    with patch("deerflow.config.get_app_config", return_value=cfg):
        provider = LocalSandboxProvider(max_cached_threads=3)

    for name in ["a", "b", "c"]:
        provider.acquire(name)
    # Touch "a" via ``get`` so it becomes most-recently used.
    provider.get("local:a")
    # Adding a fourth thread should evict "b" (the new LRU), not "a".
    provider.acquire("d")

    assert "a" in provider._thread_sandboxes
    assert "b" not in provider._thread_sandboxes
    assert {"a", "c", "d"} == set(provider._thread_sandboxes.keys())
