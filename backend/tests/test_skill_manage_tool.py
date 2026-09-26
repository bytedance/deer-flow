import asyncio
import importlib
import threading
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from deerflow.skills.security_static_scanner import StaticScannerError

skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


async def _async_result(decision: str, reason: str):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision=decision, reason=reason)


def _make_config(skills_root: Path):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )


def _make_runtime(*, thread_id: str = "thread-1", user_id: str = "default"):
    return SimpleNamespace(
        context={"thread_id": thread_id, "user_id": user_id},
        config={"configurable": {"thread_id": thread_id, "user_id": user_id}},
    )


def test_cancelled_skill_lock_waiter_releases_lock(monkeypatch):
    lock = threading.Lock()
    lock.acquire()
    started = threading.Event()
    executor = skill_manage_module._skill_lock_wait_executor

    class NotifyingExecutor:
        def submit(self, function, *args):
            started.set()
            return executor.submit(function, *args)

    monkeypatch.setattr(skill_manage_module, "_skill_lock_wait_executor", NotifyingExecutor())

    async def run():
        async def wait_for_lock():
            async with skill_manage_module._async_thread_lock(lock):
                pass

        task = asyncio.create_task(wait_for_lock())
        assert await asyncio.to_thread(started.wait, timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        lock.release()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lock.locked()
        async with skill_manage_module._async_thread_lock(lock):
            pass

    try:
        asyncio.run(run())
    finally:
        if lock.locked():
            lock.release()


def test_get_lock_is_shared_across_simultaneous_cold_lookups(monkeypatch):
    class CoordinatedRegistry:
        def __init__(self):
            self.values = {}
            self.values_lock = threading.Lock()
            self.misses = threading.Barrier(2)

        def get(self, key):
            with self.values_lock:
                value = self.values.get(key)
            if value is not None:
                return value
            try:
                self.misses.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
            return None

        def __setitem__(self, key, value):
            with self.values_lock:
                self.values[key] = value

    registry = CoordinatedRegistry()
    monkeypatch.setattr(skill_manage_module, "_skill_locks", registry)
    start = threading.Barrier(3)
    locks = []

    def get_lock():
        start.wait()
        locks.append(skill_manage_module._get_lock("cold-user", "cold-skill"))

    threads = [threading.Thread(target=get_lock, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(locks) == 2
    assert locks[0] is locks[1]


def test_skill_manage_sync_wrapper_serializes_calls_across_event_loops(monkeypatch):
    first_entered_storage = threading.Event()
    second_entered_storage = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_acquire_submitted = threading.Event()
    storage_calls_lock = threading.Lock()
    storage_calls = 0
    second_thread_id = None
    second_acquire_future = None
    results = {}
    executor = skill_manage_module._skill_lock_wait_executor

    class ObservedExecutor:
        def submit(self, function, *args):
            nonlocal second_acquire_future
            future = executor.submit(function, *args)
            if threading.get_ident() == second_thread_id:
                second_acquire_future = future
                second_acquire_submitted.set()
            return future

    class StubStorage:
        def public_skill_exists(self, name):
            nonlocal storage_calls
            with storage_calls_lock:
                storage_calls += 1
                call_number = storage_calls
            if call_number == 1:
                first_entered_storage.set()
                if not release_first.wait(timeout=2):
                    raise AssertionError("first call was not released")
            else:
                second_entered_storage.set()
            return False

    monkeypatch.setattr(skill_manage_module, "_skill_lock_wait_executor", ObservedExecutor())
    monkeypatch.setattr(skill_manage_module, "get_or_new_user_skill_storage", lambda user_id: StubStorage())
    runtime = _make_runtime(user_id="repro-user")

    def call(tag):
        nonlocal second_thread_id
        if tag == "B":
            second_thread_id = threading.get_ident()
            second_started.set()
        try:
            skill_manage_module.skill_manage_tool.func(runtime=runtime, action="bogus", name="same-skill")
        except ValueError as exc:
            results[tag] = exc

    first = threading.Thread(target=call, args=("A",), daemon=True)
    second = threading.Thread(target=call, args=("B",), daemon=True)
    first.start()
    assert first_entered_storage.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    assert second_acquire_submitted.wait(timeout=2)
    assert second_acquire_future is not None
    assert not second_acquire_future.done()
    assert not second_entered_storage.is_set()
    release_first.set()
    assert second_entered_storage.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert set(results) == {"A", "B"}
    assert all(isinstance(error, ValueError) for error in results.values())
    assert all("Unsupported action 'bogus'" in str(error) for error in results.values())


def test_skill_manage_create_and_patch(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    # Patch get_paths so UserScopedSkillStorage resolves user dirs under tmp_path
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    runtime = _make_runtime(user_id="default")

    result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "create",
        "demo-skill",
        _skill_content("demo-skill"),
    )
    assert "Created custom skill" in result

    patch_result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "patch",
        "demo-skill",
        None,
        None,
        "Demo skill",
        "Patched skill",
        1,
    )
    assert "Patched custom skill" in patch_result
    # User-scoped: custom skills written under users/default/skills/custom/
    user_custom = tmp_path / "users" / "default" / "skills" / "custom"
    assert "Patched skill" in (user_custom / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert refresh_calls == [("refresh", "default"), ("refresh", "default")]


def test_skill_manage_patch_replaces_single_occurrence_by_default(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    runtime = _make_runtime(user_id="default")
    content = _skill_content("demo-skill", "Demo skill") + "\nRepeated: Demo skill\n"

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "demo-skill", content)
    patch_result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "patch",
        "demo-skill",
        None,
        None,
        "Demo skill",
        "Patched skill",
    )

    user_custom = tmp_path / "users" / "default" / "skills" / "custom"
    skill_text = (user_custom / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "1 replacement(s) applied, 2 match(es) found" in patch_result
    assert skill_text.count("Patched skill") == 1
    assert skill_text.count("Demo skill") == 1


def test_skill_manage_rejects_public_skill_patch(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    public_dir = skills_root / "public" / "deep-research"
    public_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / "SKILL.md").write_text(_skill_content("deep-research"), encoding="utf-8")
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    runtime = _make_runtime(user_id="default")

    with pytest.raises(ValueError, match="built-in skill"):
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "patch",
            "deep-research",
            None,
            None,
            "Demo skill",
            "Patched",
        )


def test_skill_manage_sync_wrapper_supported(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    runtime = _make_runtime(thread_id="thread-sync", user_id="default")
    result = skill_manage_module.skill_manage_tool.func(
        runtime=runtime,
        action="create",
        name="sync-skill",
        content=_skill_content("sync-skill"),
    )

    assert "Created custom skill" in result
    assert refresh_calls == [("refresh", "default")]


def test_skill_manage_rejects_support_path_traversal(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    runtime = _make_runtime(user_id="default")
    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "demo-skill", _skill_content("demo-skill"))

    with pytest.raises(ValueError, match="parent-directory traversal|selected support directory"):
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "write_file",
            "demo-skill",
            "malicious overwrite",
            "references/../SKILL.md",
        )


def test_skill_manage_remove_file_updates_sandbox_projection_before_return(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    runtime = _make_runtime(user_id="default")
    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "demo-skill", _skill_content("demo-skill"))
    anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        "supporting content",
        "references/guide.md",
    )
    projected_file = tmp_path / "users" / "default" / "skills_view" / "custom" / "demo-skill" / "references" / "guide.md"
    assert projected_file.read_text(encoding="utf-8") == "supporting content"

    result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "remove_file",
        "demo-skill",
        None,
        "references/guide.md",
    )

    assert result == "Removed 'references/guide.md' from custom skill 'demo-skill'."
    assert not projected_file.exists()


def test_skill_manage_static_critical_blocks_create_before_llm(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    refresh_calls = []
    llm_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    async def _scan(*args, **kwargs):
        llm_calls.append({"args": args, "kwargs": kwargs})
        return await _async_result("allow", "ok")

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", _scan)

    runtime = _make_runtime(user_id="default")
    content = _skill_content("blocked-skill") + "\n-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"

    with pytest.raises(ValueError) as excinfo:
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "create",
            "blocked-skill",
            content,
        )

    assert "Static security scan blocked" in str(excinfo.value)
    assert "secret-private-key" in str(excinfo.value)
    assert llm_calls == []
    assert refresh_calls == []
    assert not (tmp_path / "users" / "default" / "skills" / "custom" / "blocked-skill" / "SKILL.md").exists()


def test_skill_manage_static_scan_failure_blocks_create_before_llm(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    refresh_calls = []
    llm_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    async def _scan(*args, **kwargs):
        llm_calls.append({"args": args, "kwargs": kwargs})
        return await _async_result("allow", "ok")

    def _broken_static_scan(skill_dir, *, skill_name=None, app_config=None):
        raise StaticScannerError("native scanner unavailable")

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", _scan)
    monkeypatch.setattr(skill_manage_module, "enforce_static_scan", _broken_static_scan)

    runtime = _make_runtime(user_id="default")

    with pytest.raises(ValueError, match="Static security scan failed.*native scanner unavailable"):
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "create",
            "scanner-failure-skill",
            _skill_content("scanner-failure-skill"),
        )

    assert llm_calls == []
    assert refresh_calls == []
    assert not (tmp_path / "users" / "default" / "skills" / "custom" / "scanner-failure-skill" / "SKILL.md").exists()


def test_skill_manage_per_user_isolation(monkeypatch, tmp_path):
    """Two different users must get separate custom skill directories."""
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *args, **kwargs: _async_result("allow", "ok"))

    # Alice creates a skill
    runtime_alice = _make_runtime(user_id="alice")
    result_a = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime_alice,
        "create",
        "alice-skill",
        _skill_content("alice-skill"),
    )
    assert "Created custom skill" in result_a

    # Bob creates a different skill
    runtime_bob = _make_runtime(user_id="bob")
    result_b = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime_bob,
        "create",
        "bob-skill",
        _skill_content("bob-skill"),
    )
    assert "Created custom skill" in result_b

    # Verify separate directories
    alice_dir = tmp_path / "users" / "alice" / "skills" / "custom" / "alice-skill"
    bob_dir = tmp_path / "users" / "bob" / "skills" / "custom" / "bob-skill"
    assert alice_dir.exists()
    assert bob_dir.exists()
    # No cross-contamination
    assert not (tmp_path / "users" / "alice" / "skills" / "custom" / "bob-skill").exists()
    assert not (tmp_path / "users" / "bob" / "skills" / "custom" / "alice-skill").exists()


# --- tracing wiring: the in-graph choke point (see the INVARIANT in
# packages/harness/deerflow/agents/lead_agent/agent.py) ---


def test_scan_or_raise_does_not_attach_model_tracing(monkeypatch, tmp_path):
    """``_scan_or_raise`` is the in-graph choke point for the skill security scan.

    The graph root already attached the tracing callbacks, so the scan model must
    not attach them again: double-attaching emits duplicate spans and blocks the
    Langfuse handler's ``propagate_attributes`` path, so session_id/user_id never
    reach the trace. Drives the real ``scan_skill_content`` rather than stubbing it,
    so the flag is pinned all the way to the model factory.
    """
    config = _make_config(tmp_path / "skills")
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)

    create_kwargs = {}

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            return SimpleNamespace(content='{"decision":"allow","reason":"ok"}')

    def _fake_create_chat_model(**kwargs):
        create_kwargs.update(kwargs)
        return FakeModel()

    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", _fake_create_chat_model)

    result = anyio.run(
        lambda: skill_manage_module._scan_or_raise(
            _skill_content("demo-skill"),
            executable=False,
            location="demo-skill/SKILL.md",
        )
    )

    assert result["decision"] == "allow"
    assert create_kwargs["attach_tracing"] is False
