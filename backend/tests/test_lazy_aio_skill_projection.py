"""Offline integration of lazy Agent skill views and AIO acquisition."""

from __future__ import annotations

import atexit
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.community.aio_sandbox import aio_sandbox_provider as aio_mod
from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.tools import ensure_sandbox_initialized, ensure_sandbox_initialized_async


class _RecordingContainerBackend(LocalContainerBackend):
    """Replace container I/O, retaining the provider's real mount/identity code."""

    def __init__(self) -> None:
        self.created: list[tuple[str | None, str, dict]] = []
        self.discovered: list[str] = []
        self.running: dict[str, SandboxInfo] = {}

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        self.discovered.append(sandbox_id)
        return self.running.get(sandbox_id)

    def create(self, thread_id: str | None, sandbox_id: str, **kwargs) -> SandboxInfo:
        self.created.append((thread_id, sandbox_id, kwargs))
        info = SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox.invalid")
        self.running[sandbox_id] = info
        return info

    def is_alive(self, info: SandboxInfo) -> bool:
        return info.sandbox_id in self.running

    def destroy(self, info: SandboxInfo) -> None:
        self.running.pop(info.sandbox_id, None)

    def is_absent(self, sandbox_id: str) -> bool:
        return sandbox_id not in self.running

    def complete_absent_teardown(self, sandbox_id: str) -> None:
        assert self.is_absent(sandbox_id)


def _write_skill(root: Path, name: str) -> None:
    target = root / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nname: {name}\ndescription: Test skill\n---\n\n# {name}\n", encoding="utf-8")


@pytest.fixture
def lazy_aio_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = Paths(base_dir=tmp_path / "state")
    skills_root = tmp_path / "skills"
    config = SimpleNamespace(
        sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider", idle_timeout=0),
        skills=SkillsConfig(path=str(skills_root)),
        stream_bridge=None,
    )
    extensions = ExtensionsConfig()
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.extensions_config.ExtensionsConfig.from_file", lambda *a, **kw: extensions)
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: extensions)

    for name in ("public-allowed", "public-denied"):
        _write_skill(skills_root / "public", name)
    for name in ("custom-allowed", "custom-denied"):
        _write_skill(paths.user_custom_skills_dir("alice"), name)
    for name in ("integration-allowed", "integration-denied"):
        _write_skill(paths.integration_skills_dir() / "test-provider", name)
    _write_skill(skills_root / "custom", "legacy-denied")

    backend = _RecordingContainerBackend()
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_create_backend", lambda self: backend)
    # No daemon, signal handler, or startup orphan probe is needed for the
    # deterministic single-provider lifecycle under test.
    for method in ("_register_signal_handlers", "_reconcile_orphans", "_start_lease_renewal"):
        monkeypatch.setattr(aio_mod.AioSandboxProvider, method, lambda self: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *a, **kw: True)

    async def ready(*args, **kwargs):
        return True

    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", ready)
    provider = aio_mod.AioSandboxProvider()
    set_sandbox_provider(provider)
    try:
        yield SimpleNamespace(paths=paths, provider=provider, backend=backend)
    finally:
        try:
            provider.shutdown()
        finally:
            atexit.unregister(provider.shutdown)
            reset_sandbox_provider()


def _tool_runtime(state: dict, context: dict) -> ToolRuntime:
    return ToolRuntime(
        state=state,
        context=context,
        config={"configurable": {}},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="first-sandbox-tool",
        store=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("async_init", [False, True], ids=["sync", "async"])
async def test_lazy_aio_projects_before_first_tool_and_reuses_filtered_mounts(lazy_aio_env, async_init):
    env = lazy_aio_env
    thread_id = "thread-policy"
    shared_id = env.provider._sandbox_id_for_thread(thread_id, "alice")
    allowed = {"public-allowed", "custom-allowed", "integration-allowed"}
    middleware = SandboxMiddleware(lazy_init=True, available_skills=allowed)
    context = {"thread_id": thread_id, "user_id": "alice"}
    state = {"messages": [HumanMessage(content="Hello, how are you?")]}
    runtime = Runtime(context=context)

    if async_init:
        update = await middleware.abefore_agent(state, runtime)
    else:
        update = middleware.before_agent(state, runtime)

    projection = env.paths.thread_skills_view_dir(thread_id, user_id="alice")
    assert update is None
    assert "sandbox" not in state
    assert "sandbox_id" not in context
    assert env.backend.created == []
    assert env.backend.discovered == []
    assert (projection / "public/public-allowed/SKILL.md").is_file()
    assert (projection / "custom/custom-allowed/SKILL.md").is_file()
    assert (projection / "integrations/test-provider/integration-allowed/SKILL.md").is_file()
    assert not any(projection.rglob("*-denied"))

    tool_runtime = _tool_runtime(state, context)
    if async_init:
        sandbox = await ensure_sandbox_initialized_async(tool_runtime)
    else:
        sandbox = ensure_sandbox_initialized(tool_runtime)

    policy_id = env.provider._sandbox_id_for_thread(thread_id, "alice")
    assert sandbox.id == policy_id != shared_id
    assert env.backend.discovered == [policy_id]
    assert len(env.backend.created) == 1
    created_thread, created_id, kwargs = env.backend.created[0]
    assert (created_thread, created_id) == (thread_id, policy_id)
    skill_mounts = {destination: (Path(source), read_only) for source, destination, read_only in kwargs["extra_mounts"] if destination.startswith("/mnt/skills/")}
    assert skill_mounts == {f"/mnt/skills/{category}": (projection / category, True) for category in ("public", "custom", "legacy", "integrations")}
    assert kwargs["config_mount_exclusion_root"] == "/mnt/skills"
    assert state["sandbox"] == {"sandbox_id": policy_id}
    assert context["sandbox_id"] == policy_id

    # A later run can narrow the stable mounted view before claiming this
    # thread's warm sandbox. It must not fall back to shared-view discovery.
    if async_init:
        await middleware.aafter_agent(state, runtime)
    else:
        middleware.after_agent(state, runtime)
    assert policy_id in env.provider._warm_pool
    narrowed = SandboxMiddleware(lazy_init=True, available_skills={"public-allowed"})
    next_context = {"thread_id": thread_id, "user_id": "alice"}
    next_state = {"messages": [HumanMessage(content="Hello again")]}
    next_runtime = Runtime(context=next_context)
    if async_init:
        assert await narrowed.abefore_agent(next_state, next_runtime) is None
        reused = await ensure_sandbox_initialized_async(_tool_runtime(next_state, next_context))
    else:
        assert narrowed.before_agent(next_state, next_runtime) is None
        reused = ensure_sandbox_initialized(_tool_runtime(next_state, next_context))
    assert reused.id == policy_id
    assert len(env.backend.created) == 1
    assert env.backend.discovered == [policy_id]
    assert (skill_mounts["/mnt/skills/public"][0] / "public-allowed/SKILL.md").is_file()
    assert not (skill_mounts["/mnt/skills/custom"][0] / "custom-allowed").exists()
    assert not (skill_mounts["/mnt/skills/integrations"][0] / "test-provider/integration-allowed").exists()
