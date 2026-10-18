import asyncio
import gc
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
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


def _setup_demo_skill_with_binary_asset(monkeypatch, tmp_path):
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
    # A binary support file as a .skill archive install would leave it (the
    # installer only rejects *executable* binaries).
    skill_dir = tmp_path / "users" / "default" / "skills" / "custom" / "demo-skill"
    (skill_dir / "assets" / "nested").mkdir(parents=True)
    (skill_dir / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    (skill_dir / "assets" / "nested" / "inner.txt").write_text("inner", encoding="utf-8")
    return runtime, skill_dir


def _history_records(skill_dir: Path) -> list[dict]:
    import json

    history_file = skill_dir.parent.parent / "history" / "demo-skill.jsonl"
    if not history_file.exists():  # storage layouts differ; fall back to a search
        history_file = next(p for p in skill_dir.parent.parent.rglob("*.jsonl") if "demo-skill" in p.name)
    return [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_skill_manage_remove_file_handles_a_binary_support_file(monkeypatch, tmp_path):
    runtime, skill_dir = _setup_demo_skill_with_binary_asset(monkeypatch, tmp_path)

    result = anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "remove_file", "demo-skill", None, "assets/logo.png")

    assert result == "Removed 'assets/logo.png' from custom skill 'demo-skill'."
    assert not (skill_dir / "assets" / "logo.png").exists()
    record = _history_records(skill_dir)[-1]
    assert record["action"] == "remove_file"
    assert record["file_path"] == "assets/logo.png"
    assert record["prev_content"] is None


def test_skill_manage_write_file_can_overwrite_a_binary_support_file(monkeypatch, tmp_path):
    runtime, skill_dir = _setup_demo_skill_with_binary_asset(monkeypatch, tmp_path)

    result = anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "write_file", "demo-skill", "now text", "assets/logo.png")

    assert result == "Wrote 'assets/logo.png' for custom skill 'demo-skill'."
    assert (skill_dir / "assets" / "logo.png").read_text(encoding="utf-8") == "now text"
    record = _history_records(skill_dir)[-1]
    assert record["action"] == "write_file"
    assert record["prev_content"] is None
    assert record["new_content"] == "now text"


@pytest.mark.parametrize("action, content", [("remove_file", None), ("write_file", "x")])
@pytest.mark.parametrize("path", ["assets", "assets/nested"], ids=["bare-subdir", "nested-dir"])
def test_skill_manage_rejects_a_support_directory_path(monkeypatch, tmp_path, action, content, path):
    runtime, skill_dir = _setup_demo_skill_with_binary_asset(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="file"):
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, action, "demo-skill", content, path)

    assert (skill_dir / "assets" / "logo.png").exists()
    assert (skill_dir / "assets" / "nested" / "inner.txt").read_text(encoding="utf-8") == "inner"


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


# --- per-(user, skill) lock across event loops (#5846) ---


class _ParkingStorage:
    """Skill storage whose first delete parks inside the skill lock until released."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.deleted: list[str] = []
        self.callers: list[str] = []
        self.max_active = 0
        self._active = 0
        self._guard = threading.Lock()

    def delete_custom_skill(self, name: str, *, history_meta: dict) -> None:
        with self._guard:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            if not self.entered.is_set():
                self.entered.set()
                # Bounded so a broken lock cannot hang pytest teardown.
                assert self.release.wait(5), "test never released the parked holder"
            self.deleted.append(name)
            self.callers.append(history_meta["thread_id"])
        finally:
            with self._guard:
                self._active -= 1


class _ObservedSkillLock:
    """Report waits on a held skill lock without replacing its locking behavior."""

    def __init__(self, lock, arrived) -> None:
        self.lock = lock
        self.arrived = arrived

    async def __aenter__(self):
        if self.lock.locked():
            self.arrived()
        return await self.lock.__aenter__()

    async def __aexit__(self, *exc):
        return await self.lock.__aexit__(*exc)


def _park_skill_mutations(monkeypatch, arrived) -> _ParkingStorage:
    storage = _ParkingStorage()
    monkeypatch.setattr(skill_manage_module, "get_or_new_user_skill_storage", lambda _user_id: storage)

    async def _refresh(_user_id: str) -> None:
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    get_lock = skill_manage_module._get_lock
    monkeypatch.setattr(skill_manage_module, "_get_lock", lambda user_id, name: _ObservedSkillLock(get_lock(user_id, name), arrived))
    return storage


def _delete(user_id: str, name: str, *, thread_id: str = "thread-1"):
    return skill_manage_module.skill_manage_tool.coroutine(_make_runtime(thread_id=thread_id, user_id=user_id), "delete", name)


def test_skill_manage_same_skill_sync_calls_do_not_hang_across_event_loops(monkeypatch):
    # ToolNode runs same-turn sync calls on separate threads; the sync wrapper
    # gives each one its own asyncio.run loop.
    arrivals = threading.Semaphore(0)
    storage = _park_skill_mutations(monkeypatch, arrivals.release)
    results = {}

    def call(tag):
        try:
            results[tag] = skill_manage_module.skill_manage_tool.func(runtime=_make_runtime(user_id="alice"), action="delete", name="cross-loop-skill")
        except Exception as exc:
            results[tag] = exc

    threads = [threading.Thread(target=call, args=("holder",), daemon=True)]
    threads[0].start()
    try:
        assert storage.entered.wait(5)
        for tag in ("waiter-1", "waiter-2"):
            threads.append(threading.Thread(target=call, args=(tag,), daemon=True))
            threads[-1].start()
            assert arrivals.acquire(timeout=5), f"{tag} did not wait for the held skill lock"
    finally:
        storage.release.set()
        for thread in threads:
            thread.join(5)

    assert not any(thread.is_alive() for thread in threads), "a same-skill sync call never returned"
    assert results == dict.fromkeys(("holder", "waiter-1", "waiter-2"), "Deleted custom skill 'cross-loop-skill'.")
    assert storage.max_active == 1
    gc.collect()
    assert ("alice", "cross-loop-skill") not in skill_manage_module._skill_locks


def test_skill_manage_lock_waiters_leave_workers_for_other_skills(monkeypatch):
    async def scenario():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2))
        waiters_parked = asyncio.Event()
        arrived = 0

        def on_arrival():
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                waiters_parked.set()

        storage = _park_skill_mutations(monkeypatch, on_arrival)
        holder = asyncio.create_task(_delete("alice", "busy-skill"))
        tasks = [holder]
        try:
            assert await asyncio.to_thread(storage.entered.wait, 5)
            tasks += [asyncio.create_task(_delete("alice", "busy-skill")) for _ in range(2)]
            await asyncio.wait_for(waiters_parked.wait(), 5)
            # The holder parks one worker; the waiters must leave the other free
            # for another skill and for the same skill of another user.
            assert await asyncio.wait_for(_delete("alice", "other-skill"), 5) == "Deleted custom skill 'other-skill'."
            assert await asyncio.wait_for(_delete("bob", "busy-skill"), 5) == "Deleted custom skill 'busy-skill'."
            assert not holder.done()
        finally:
            storage.release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        assert results == ["Deleted custom skill 'busy-skill'."] * 3

    asyncio.run(scenario())


def test_skill_manage_cancelled_lock_waiter_neither_waits_nor_strands_the_skill(monkeypatch):
    async def scenario():
        lock = skill_manage_module._get_lock("alice", "cancel-skill")
        await lock.__aenter__()
        held = True
        all_parked = asyncio.Event()
        arrived = 0

        def on_arrival():
            nonlocal arrived
            arrived += 1
            if arrived == 3:
                all_parked.set()

        storage = _park_skill_mutations(monkeypatch, on_arrival)
        storage.entered.set()
        waiters = [asyncio.create_task(_delete("alice", "cancel-skill")) for _ in range(3)]
        try:
            await asyncio.wait_for(all_parked.wait(), 5)
            waiters[0].cancel()
            # asyncio.wait, not wait_for: a waiter that shields its wait from
            # cancellation must fail this test, not deadlock against the lock we hold.
            await asyncio.wait({waiters[0]}, timeout=5)
            assert waiters[0].cancelled(), "cancellation waited for the holder"
            # Cancel the next waiter in the same step as the release, before it can re-acquire.
            held = False
            await lock.__aexit__(None, None, None)
            waiters[1].cancel()
            await asyncio.wait({waiters[1]}, timeout=5)
            assert waiters[1].cancelled()
            assert await asyncio.wait_for(waiters[2], 5) == "Deleted custom skill 'cancel-skill'."
        finally:
            if held:
                await lock.__aexit__(None, None, None)
            for task in waiters:
                task.cancel()
            await asyncio.wait_for(asyncio.gather(*waiters, return_exceptions=True), 5)
        assert storage.deleted == ["cancel-skill"]

    asyncio.run(scenario())
    gc.collect()
    assert ("alice", "cancel-skill") not in skill_manage_module._skill_locks


def test_skill_manage_lock_rejects_release_when_unlocked():
    # Like asyncio.Lock: releasing a lock nobody holds is an error, not a no-op.
    lock = skill_manage_module._get_lock("alice", "unlocked-skill")
    with pytest.raises(RuntimeError):
        asyncio.run(lock.__aexit__(None, None, None))


def test_skill_manage_same_skill_waiters_keep_arrival_order(monkeypatch):
    # Same-turn calls on one skill can depend on each other (patch a->b, then
    # b->c). The gateway runs them on one loop, where they must take the lock in
    # the order they reached it, as asyncio.Lock did.
    async def scenario():
        lock = skill_manage_module._get_lock("alice", "ordered-skill")
        await lock.__aenter__()
        arrived = asyncio.Event()
        storage = _park_skill_mutations(monkeypatch, arrived.set)
        storage.entered.set()
        # The thread id only tags each call in the storage record.
        calls = [f"call-{i}" for i in range(8)]
        waiters = []
        try:
            for call in calls:
                arrived.clear()
                waiters.append(asyncio.create_task(_delete("alice", "ordered-skill", thread_id=call)))
                await asyncio.wait_for(arrived.wait(), 5)
        finally:
            await lock.__aexit__(None, None, None)
            await asyncio.wait_for(asyncio.gather(*waiters, return_exceptions=True), 5)
        assert storage.callers == calls

    asyncio.run(scenario())


def test_skill_manage_later_call_does_not_overtake_a_parked_waiter(monkeypatch):
    # The storage lookup runs before the lock, so a later call can reach the
    # lock in the same loop step as a release. As with asyncio.Lock, it must
    # queue behind the call already waiting instead of taking the lock first.
    async def scenario():
        lock = skill_manage_module._get_lock("alice", "fair-skill")
        await lock.__aenter__()
        arrived = asyncio.Event()
        storage = _park_skill_mutations(monkeypatch, arrived.set)
        storage.entered.set()
        to_thread = skill_manage_module._to_thread
        lookup_parked = asyncio.Event()
        finish_lookup = asyncio.Event()
        late = None

        async def gated_to_thread(func, /, *args, **kwargs):
            if func is skill_manage_module.get_or_new_user_skill_storage and asyncio.current_task() is late:
                lookup_parked.set()
                await finish_lookup.wait()
                # Resume straight into the lock, with no thread hop in between.
                return func(*args, **kwargs)
            return await to_thread(func, *args, **kwargs)

        monkeypatch.setattr(skill_manage_module, "_to_thread", gated_to_thread)
        waiter = asyncio.create_task(_delete("alice", "fair-skill", thread_id="queued"))
        tasks = [waiter]
        held = True
        try:
            await asyncio.wait_for(arrived.wait(), 5)
            late = asyncio.create_task(_delete("alice", "fair-skill", thread_id="late"))
            tasks.append(late)
            await asyncio.wait_for(lookup_parked.wait(), 5)
            # Release while the later call's lookup completes in the same step.
            finish_lookup.set()
            held = False
            await lock.__aexit__(None, None, None)
            await asyncio.wait_for(asyncio.gather(*tasks), 5)
        finally:
            if held:
                await lock.__aexit__(None, None, None)
            finish_lookup.set()
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        assert storage.callers == ["queued", "late"]

    asyncio.run(scenario())
