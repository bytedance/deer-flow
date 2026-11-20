"""Regression anchors: authenticated routers must read the live config off the loop.

``get_app_config()`` stats and hashes ``config.yaml`` and
``extensions_config.json`` on every call and reparses them after an edit, and
``get_config()``, ``get_memory_config()`` and ``safe_app_config()`` go through
it. Each route below calls one of them, or a router helper built on one, through
``asyncio.to_thread``.

Several of those helpers catch ``Exception`` so a config problem degrades the
answer instead of failing the request (no prices, no model check, browser off).
The gate's ``BlockingError`` is an ``Exception`` too, so a read left on the loop
would pass the gate unnoticed. Each case therefore replaces the read with a
recorder that notes whether it ran on the event loop before reading a real
file, and asserts the route used the recorder's answer.
"""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from blockbuster import BlockingError
from fastapi import HTTPException

# Import every module up front: importing on the loop is itself blocking IO.
import deerflow.authz.sandbox_authz as sandbox_authz
import deerflow.community.browser_automation  # noqa: F401  (imported lazily by browser_stream)
import deerflow.config as deerflow_config
from app.gateway.authz import Permissions
from app.gateway.routers import agents, artifacts, browser, channel_connections, console, memory, projects, scheduled_tasks
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.paths import get_paths
from deerflow.config.projects_config import ProjectsConfig
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


class _ConfigRead:
    """Stands in for one config read and records whether it ran on the loop."""

    def __init__(self, result: Any = None) -> None:
        self.on_loop: list[bool] = []
        self._result = result

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.on_loop.append(False)
        else:
            self.on_loop.append(True)
        # Record before reading: a read the gate stops on the loop still counts.
        Path(__file__).read_bytes()
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _Stop(Exception):
    """Ends a route right after the config read under test."""


def _request(**state: Any) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)), state=SimpleNamespace(), headers={}, cookies={})


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalars(self) -> _EmptyResult:
        return self


class _EmptySession:
    async def scalar(self, *_args: Any, **_kwargs: Any) -> int:
        return 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> _EmptyResult:
        return _EmptyResult()


@asynccontextmanager
async def _empty_session():
    yield _EmptySession()


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: unwrap(console.console_stats)(_request()), id="stats"),
        pytest.param(lambda: unwrap(console.console_runs)(_request(), limit=20, offset=0, status=None), id="runs"),
        pytest.param(lambda: unwrap(console.console_usage)(_request(), days=14, tz_offset_minutes=0), id="usage"),
    ],
)
async def test_console_routes_read_model_pricing_off_the_loop(call, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reads = _ConfigRead({})
    monkeypatch.setattr(console, "_build_pricing_map", reads)
    monkeypatch.setattr(console, "_session_factory_or_503", lambda: _empty_session)
    monkeypatch.setattr(console, "get_current_user", AsyncMock(return_value="user-1"))

    await call()

    assert reads.on_loop == [False]


@pytest.fixture
def agents_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.app_config._legacy_config_candidates", lambda: ())
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    reads = _ConfigRead(HTTPException(status_code=422, detail="Unknown model 'missing'."))
    monkeypatch.setattr(agents, "_validate_model_exists", reads)
    try:
        yield reads
    finally:
        load_agents_api_config_from_dict({})


async def _seed_agent(name: str) -> None:
    agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, get_effective_user_id(), name)
    await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((agent_dir / "config.yaml").write_text, f"name: {name}\n", encoding="utf-8")


@pytest.mark.parametrize("route", ["create", "import", "update"])
async def test_agent_writes_check_the_model_off_the_loop(route: str, agents_api: _ConfigRead) -> None:
    fields = {"name": "loop-agent", "soul": "You are a test agent.", "model": "missing"}
    with pytest.raises(HTTPException) as exc_info:
        if route == "create":
            await agents.create_agent_endpoint(agents.AgentCreateRequest(**fields))
        elif route == "import":
            await agents.import_agent_package(agents.AgentPackage(format="deerflow.custom-agent", version=1, agent=agents.AgentPackageAgent(**fields)))
        else:
            await _seed_agent("loop-agent")
            await agents.update_agent("loop-agent", agents.AgentUpdateRequest(model="missing"))

    assert exc_info.value.status_code == 422
    assert agents_api.on_loop == [False]


@pytest.fixture
def browser_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "_browser_thread_owned_by", AsyncMock(return_value=True))
    monkeypatch.setattr(browser, "_authenticate_ws", AsyncMock(return_value=SimpleNamespace(id="user-1")))
    monkeypatch.setattr(browser, "_ws_origin_allowed", lambda _websocket: True)
    monkeypatch.setattr(browser, "resolve_route_permissions", AsyncMock(return_value={Permissions.THREADS_WRITE}))


def _websocket() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=object())), close=AsyncMock())


async def test_browser_navigate_checks_the_tool_switch_off_the_loop(browser_access, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(False)
    monkeypatch.setattr(browser, "_browser_tools_enabled", reads)
    request = _request(thread_store=object())
    request.state.auth = SimpleNamespace(user=SimpleNamespace(id="user-1"))

    with pytest.raises(HTTPException) as exc_info:
        await unwrap(browser.navigate_browser)("thread-1", browser.BrowserNavigateRequest(url="https://example.com/"), request)

    assert exc_info.value.status_code == 404
    assert reads.on_loop == [False]


async def test_browser_stream_checks_the_tool_switch_off_the_loop(browser_access, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(False)
    monkeypatch.setattr(browser, "_browser_tools_enabled", reads)
    websocket = _websocket()

    await browser.browser_stream(websocket, "thread-1")

    websocket.close.assert_awaited_once_with(code=4404)
    assert reads.on_loop == [False]


async def test_browser_stream_reads_the_session_config_off_the_loop(browser_access, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(_Stop())
    monkeypatch.setattr(browser, "_browser_tools_enabled", lambda: True)
    monkeypatch.setattr(browser, "_negotiate_browser_frame_format", AsyncMock(return_value=False))
    monkeypatch.setattr(deerflow_config, "get_app_config", reads)

    with pytest.raises(_Stop):
        await browser.browser_stream(_websocket(), "thread-1")

    assert reads.on_loop == [False]


@pytest.fixture
def small_projects_config(monkeypatch: pytest.MonkeyPatch) -> _ConfigRead:
    reads = _ConfigRead(ProjectsConfig(instructions_max_bytes=256))
    monkeypatch.setattr(projects, "_projects_config", reads)
    return reads


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: unwrap(projects.create_project)(projects.ProjectCreateRequest(name="p", instructions="x" * 257), _request()), id="create"),
        pytest.param(lambda: unwrap(projects.patch_project)("project-1", projects.ProjectPatchRequest(instructions="x" * 257), _request()), id="patch"),
    ],
)
async def test_project_writes_read_the_instructions_cap_off_the_loop(call, small_projects_config: _ConfigRead) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call()

    assert exc_info.value.status_code == 422
    assert "256-byte" in exc_info.value.detail
    assert small_projects_config.on_loop == [False]


async def test_project_memory_promotion_reads_the_instructions_cap_off_the_loop(small_projects_config: _ConfigRead, monkeypatch: pytest.MonkeyPatch) -> None:
    memory_call = AsyncMock(side_effect=ValueError("instructions changed"))
    monkeypatch.setattr(projects, "_memory_call", memory_call)

    with pytest.raises(HTTPException) as exc_info:
        await unwrap(projects.promote_project_memory)("project-1", "fact-1", projects.ProjectMemoryPromotion(expected_instructions=""), _request())

    assert exc_info.value.status_code == 409
    assert memory_call.await_args.kwargs["max_bytes"] == 256
    assert small_projects_config.on_loop == [False]


async def test_channel_runtime_store_resolves_from_a_config_read_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    app_config = object()
    store = object()
    reads = _ConfigRead(app_config)
    resolved: list[object] = []

    def resolve(config: object, *, cipher: object) -> object:
        resolved.append(config)
        return store

    monkeypatch.setattr(channel_connections, "_get_app_config", reads)
    monkeypatch.setattr(channel_connections, "resolve_runtime_config_store", resolve)

    assert await channel_connections._get_runtime_config_store(_request()) is store
    assert resolved == [app_config]
    assert reads.on_loop == [False]


async def test_channel_connections_config_is_read_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ChannelConnectionsConfig()
    reads = _ConfigRead(SimpleNamespace(channel_connections=config))
    monkeypatch.setattr(channel_connections, "_get_app_config", reads)

    assert await channel_connections._get_channel_connections_config(_request()) is config
    assert reads.on_loop == [False]


async def test_channels_config_is_read_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(SimpleNamespace(model_extra={"channels": {"slack": {"enabled": True}}}))
    monkeypatch.setattr(channel_connections, "_get_app_config", reads)
    monkeypatch.setattr(channel_connections, "merge_runtime_channel_configs", lambda *_args, **_kwargs: None)

    result = await channel_connections._load_channels_config(_request(channel_runtime_config_store=object()), ChannelConnectionsConfig())

    assert result == {"slack": {"enabled": True}}
    assert reads.on_loop == [False]


async def test_wechat_qr_login_reads_the_deployment_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(object())
    monkeypatch.setattr(channel_connections, "_get_app_config", reads)
    monkeypatch.setattr(channel_connections, "require_admin_user", AsyncMock())
    monkeypatch.setattr(channel_connections, "multi_instance_declaration", lambda _config: "deployment.multi_instance")
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    config = ChannelConnectionsConfig(enabled=True, wechat={"enabled": True})

    with pytest.raises(HTTPException) as exc_info:
        await channel_connections._require_wechat_qr_login(_request(channel_connections_config=config))

    assert exc_info.value.status_code == 503
    assert reads.on_loop == [False]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda: unwrap(scheduled_tasks.create_scheduled_task)(
                _request(),
                scheduled_tasks.ScheduledTaskCreateRequest(title="t", prompt="p", schedule_type="once", schedule_spec={}, timezone="UTC"),
            ),
            id="create",
        ),
        pytest.param(lambda: unwrap(scheduled_tasks.update_scheduled_task)("task-1", _request(), scheduled_tasks.ScheduledTaskUpdateRequest()), id="update"),
    ],
)
async def test_scheduled_task_writes_read_the_config_off_the_loop(call, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(_Stop())
    monkeypatch.setattr(scheduled_tasks, "get_config", reads)

    with pytest.raises(_Stop):
        await call()

    assert reads.on_loop == [False]


async def test_memory_config_endpoint_reads_the_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(MemoryConfig(enabled=False, injection_enabled=False))
    monkeypatch.setattr(memory, "get_memory_config", reads)

    response = await unwrap(memory.get_memory_config_endpoint)(_request())

    assert (response.enabled, response.injection_enabled) == (False, False)
    assert reads.on_loop == [False]


async def test_memory_status_reads_the_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigRead(_Stop())
    monkeypatch.setattr(memory, "get_memory_config", reads)

    with pytest.raises(_Stop):
        await unwrap(memory.get_memory_status)(_request())

    assert reads.on_loop == [False]


async def test_artifact_update_reads_the_sandbox_policy_off_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    vpath = "/mnt/user-data/outputs/notes.txt"
    target = await asyncio.to_thread(artifacts.resolve_outputs_confined_path, "t1", vpath, user_id=get_effective_user_id())
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, b"hello")

    @asynccontextmanager
    async def allow_write(*_args, **_kwargs):
        yield

    app_config = object()
    reads = _ConfigRead(app_config)
    acquire = AsyncMock(side_effect=HTTPException(status_code=403, detail="stop after the policy read"))
    monkeypatch.setattr(sandbox_authz, "safe_app_config", reads)
    monkeypatch.setattr(artifacts, "reserve_artifact_write", allow_write)
    monkeypatch.setattr(artifacts, "get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr(artifacts, "try_acquire_sandbox_for_request", acquire)

    with pytest.raises(HTTPException) as exc_info:
        await unwrap(artifacts.update_artifact)(
            "t1",
            vpath,
            artifacts.ArtifactUpdateRequest(content="updated", expected_sha256=hashlib.sha256(b"hello").hexdigest()),
            request=None,
        )

    assert exc_info.value.status_code == 403
    assert acquire.await_args.kwargs["app_config"] is app_config
    assert reads.on_loop == [False]


async def test_config_read_recorder_trips_the_gate_on_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta-check: a read left on the loop inside router code fails the gate and is recorded.

    The gate only flags IO whose stack passes through ``app.*`` or
    ``deerflow.*``, so the probe goes through a router's own sync helper.
    """
    reads = _ConfigRead(SimpleNamespace(projects=ProjectsConfig()))
    monkeypatch.setattr(projects, "get_app_config", reads)

    with pytest.raises(BlockingError):
        projects._projects_config()

    assert reads.on_loop == [True]
