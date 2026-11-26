"""History ordering for independent Gateway processes sharing a skills root.

The skill routes and the agent's ``skill_manage`` tool both mutate custom
skills, so each pair must serialize, not only two routes.
"""

import asyncio
import json
import multiprocessing
from types import SimpleNamespace

import pytest


def _content(description: str) -> str:
    return f"---\nname: demo-skill\ndescription: {description}\n---\n\n# Demo\n"


def _mutate_in_process(base_dir, action, content, gate_phase, ready, start, attempted, parked, release, done):
    # Use spawn, not fork: each worker has its own lock registry and storage.
    from app.gateway.routers import skills as router
    from deerflow.config.paths import Paths
    from deerflow.skills.security_scanner import ScanResult
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: base_dir / "skills", container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("deerflow.config.get_app_config", lambda: config)
        patch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=base_dir))
        patch.setattr("deerflow.config.paths._paths", None)
        storage = UserScopedSkillStorage("default", host_path=str(base_dir / "skills"))
        patch.setattr(router, "_get_user_skill_storage", lambda cfg: storage)
        patch.setattr(router, "get_effective_user_id", lambda: "default")

        async def scan(*args, **kwargs):
            return ScanResult(decision="allow", reason="offline test")

        async def static_scan(*args, **kwargs):
            return []

        async def refresh(*args, **kwargs):
            pass

        patch.setattr(router, "scan_skill_content", scan)
        patch.setattr(router, "_scan_static_skill_markdown_or_raise", static_scan)
        patch.setattr(router, "refresh_user_skills_system_prompt_cache_async", refresh)
        patch.setattr(router, "_publish_skills_cache_reset", refresh)

        from deerflow.tools import skill_manage_tool

        patch.setattr(skill_manage_tool, "scan_skill_content", scan)
        patch.setattr(skill_manage_tool, "refresh_user_skills_system_prompt_cache_async", refresh)
        patch.setattr(skill_manage_tool, "publish_skills_cache_reset", lambda *, user_id=None: None)

        from deerflow.skills import mutation_lock

        original_lock = mutation_lock.custom_skill_mutation_lock

        def observed_lock(storage):
            attempted.set()
            return original_lock(storage)

        patch.setattr(mutation_lock, "custom_skill_mutation_lock", observed_lock)
        if gate_phase:
            method = "write_custom_skill" if gate_phase == "write" else "append_history"
            original = getattr(UserScopedSkillStorage, method)

            def gated(self, *args, **kwargs):
                parked.set()
                assert release.wait(30), "parent did not release the parked mutation"
                return original(self, *args, **kwargs)

            patch.setattr(UserScopedSkillStorage, method, gated)

        request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
        ready.set()
        assert start.wait(30), "parent did not start the mutation"
        if action == "tool_edit":
            runtime = SimpleNamespace(context={"thread_id": "thread-1", "user_id": "default"}, config={"configurable": {"thread_id": "thread-1", "user_id": "default"}})
            asyncio.run(skill_manage_tool.skill_manage_tool.coroutine(runtime, "edit", "demo-skill", content))
        elif action == "edit":
            asyncio.run(router.update_custom_skill("demo-skill", router.CustomSkillUpdateRequest(content=content), request, config))
        else:
            asyncio.run(router.rollback_custom_skill("demo-skill", router.SkillRollbackRequest(history_index=0), request, config))
        done.set()


def _mutate_in_two_processes(tmp_path, first_action, peer_action, gate_phase, prior=()):
    """Park ``first_action`` at ``gate_phase`` and require ``peer_action`` to wait for it.

    Returns the history entries and the final ``SKILL.md``.
    """
    custom_root = tmp_path / "users" / "default" / "skills" / "custom"
    skill_file = custom_root / "demo-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(_content("Initial"), encoding="utf-8")
    history_file = custom_root / ".history" / "demo-skill.jsonl"
    history_file.parent.mkdir()
    history_file.write_text("".join(json.dumps(entry) + "\n" for entry in prior), encoding="utf-8")

    context = multiprocessing.get_context("spawn")
    parked, release = context.Event(), context.Event()
    workers = []
    starts, ready_events, attempted_events, done_events = [], [], [], []
    for worker_action, worker_content, phase in [(first_action, _content("Edited"), gate_phase), (peer_action, _content("Concurrent"), None)]:
        ready, start, attempted, done = (context.Event() for _ in range(4))
        workers.append(context.Process(target=_mutate_in_process, args=(tmp_path, worker_action, worker_content, phase, ready, start, attempted, parked, release, done)))
        ready_events.append(ready)
        starts.append(start)
        attempted_events.append(attempted)
        done_events.append(done)

    try:
        for worker in workers:
            worker.start()
        for ready in ready_events:
            assert ready.wait(30), "worker did not initialize"
        starts[0].set()
        assert parked.wait(10), "first mutation did not reach the gate"
        starts[1].set()
        assert attempted_events[1].wait(10), "peer did not reach the mutation lock"
        assert not done_events[1].wait(2), "peer mutated the skill inside the first process's critical section"
        release.set()
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        assert all(done.is_set() for done in done_events)
    finally:
        release.set()
        for start in starts:
            start.set()
        for worker in workers:
            if worker.pid is not None:
                worker.join(10)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(10)
                worker.close()

    entries = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines()]
    return entries, skill_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("action", ["edit", "rollback"])
@pytest.mark.parametrize("gate_phase", ["write", "history"])
def test_custom_skill_history_serializes_independent_processes(tmp_path, action, gate_phase):
    """A peer must wait through both the predecessor read and history append."""
    initial, restored, edited, concurrent = (_content(label) for label in ("Initial", "Restored", "Edited", "Concurrent"))
    prior = [{"action": "human_edit", "prev_content": restored, "new_content": initial}] if action == "rollback" else []

    entries, final_content = _mutate_in_two_processes(tmp_path, action, "edit", gate_phase, prior)

    first_content = edited if action == "edit" else restored
    assert len(entries) == len(prior) + 2
    assert entries[len(prior)]["action"] == ("human_edit" if action == "edit" else "rollback")
    assert entries[len(prior)]["prev_content"] == initial
    assert entries[len(prior)]["new_content"] == first_content
    assert entries[-1]["prev_content"] == first_content
    assert entries[-1]["new_content"] == concurrent
    assert final_content == concurrent


@pytest.mark.parametrize("first, peer", [("tool_edit", "edit"), ("edit", "tool_edit")], ids=["tool-then-route", "route-then-tool"])
@pytest.mark.parametrize("gate_phase", ["write", "history"])
def test_skill_manage_and_routes_serialize_across_processes(tmp_path, first, peer, gate_phase):
    """The tool and a route in another Gateway process share the owner's mutation lock."""
    initial, edited, concurrent = (_content(label) for label in ("Initial", "Edited", "Concurrent"))

    entries, final_content = _mutate_in_two_processes(tmp_path, first, peer, gate_phase)

    actions = {"edit": "human_edit", "tool_edit": "edit"}
    assert [(entry["action"], entry["prev_content"], entry["new_content"]) for entry in entries] == [
        (actions[first], initial, edited),
        (actions[peer], edited, concurrent),
    ]
    assert final_content == concurrent
