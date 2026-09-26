"""Compatibility of managed image profiles with old local AIO containers."""

import threading
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_module
from deerflow.community.aio_sandbox import local_backend as local_backend_module
from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


def test_profile_revision_changes_local_sandbox_identity_without_changing_base(monkeypatch):
    provider = object.__new__(AioSandboxProvider)
    provider._config = {"skills_container_path": "/mnt/skills"}
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_thread_skill_projection_active", lambda *_args: False)
    revisions = iter(("first", "second"))
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: SimpleNamespace(revision=next(revisions), usable=lambda: True))

    base = provider._base_sandbox_id_for_thread("thread", "user")
    first = provider._sandbox_id_for_thread("thread", "user")
    second = provider._sandbox_id_for_thread("thread", "user")

    assert first != second
    assert first != base
    assert second != base


@pytest.mark.parametrize("policy_active", [True, False])
def test_active_container_survives_image_profile_rotation(monkeypatch, policy_active):
    provider = object.__new__(AioSandboxProvider)
    provider._config = {"skills_container_path": "/mnt/skills"}
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_thread_skill_projection_active", lambda *_args: policy_active)
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: SimpleNamespace(revision="new", usable=lambda: True))
    base = provider._base_sandbox_id_for_thread("thread", "user")
    sandbox = SimpleNamespace(_deerflow_base_identity=base)
    provider._thread_sandboxes = {("user", "thread"): "old-id"}
    provider._sandboxes = {"old-id": sandbox}
    provider._sandbox_infos = {"old-id": None}
    provider._lock = threading.Lock()
    provider._local_teardown = set()
    provider._last_activity = {}
    monkeypatch.setattr(provider, "_check_tracked_sandbox_alive", lambda *_args: True)
    monkeypatch.setattr(provider, "_publish_ownership", lambda *_args: None)
    monkeypatch.setattr(provider, "destroy", lambda *_args: pytest.fail("active container was destroyed"))

    assert provider._reuse_in_process_sandbox("thread", user_id="user") == "old-id"


def test_bound_container_records_only_its_matching_profile_revision(monkeypatch):
    provider = object.__new__(AioSandboxProvider)
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_base_sandbox_id_for_thread", lambda *_args: "base-id")
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: SimpleNamespace(revision="revision-1"))
    current = SimpleNamespace(id=provider._image_profile_sandbox_id("base-id", "revision-1"))
    previous = SimpleNamespace(id=provider._image_profile_sandbox_id("base-id", "previous"))

    provider._bind_image_profile_context(current, "thread", "user")
    provider._bind_image_profile_context(previous, "thread", "user")

    assert current._deerflow_image_profile_revision == "revision-1"
    assert previous._deerflow_image_profile_revision is None


@pytest.mark.parametrize("supported", [True, False])
def test_command_environment_capability_is_probed_without_a_secret(monkeypatch, supported):
    sandbox = object.__new__(AioSandbox)
    sandbox._bash_exec_unsupported = False
    commands = []

    def execute(command, env=None, timeout=None):
        commands.append((command, env, timeout))
        if not supported:
            sandbox._bash_exec_unsupported = True
            return "Error: /v1/bash/exec returned 404"
        return "__DEERFLOW_ENV_PROBE__\n"

    monkeypatch.setattr(sandbox, "execute_command", execute)
    assert sandbox.supports_command_environment() is supported
    assert sandbox.supports_command_environment() is supported
    assert commands == [("printf '%s\\n' \"$DEERFLOW_ENV_PROBE\"", {"DEERFLOW_ENV_PROBE": "__DEERFLOW_ENV_PROBE__"}, 10)]


def test_command_environment_probe_does_not_treat_network_error_as_old_version(monkeypatch):
    sandbox = object.__new__(AioSandbox)
    sandbox._bash_exec_unsupported = False
    monkeypatch.setattr(sandbox, "execute_command", lambda *_args, **_kwargs: "Error: connection timed out")
    with pytest.raises(RuntimeError, match="capability probe failed"):
        sandbox.supports_command_environment()


def test_actual_missing_bash_route_is_classified_as_legacy(caplog):
    from agent_sandbox.core.api_error import ApiError

    sandbox = AioSandbox(id="synthetic", base_url="http://127.0.0.1:18080")
    try:
        sandbox._client.bash.create_session = lambda **_kwargs: (_ for _ in ()).throw(ApiError(status_code=404, body={"message": "Not Found"}))
        assert sandbox.supports_command_environment() is False
        assert "upgraded" not in caplog.text
    finally:
        sandbox.close()


def _creation_provider(monkeypatch, tmp_path, *, supports_env):
    provider = object.__new__(AioSandboxProvider)
    provider._config = {"replicas": 3, "command_timeout": 600}
    backend = object.__new__(LocalContainerBackend)
    calls = []
    backend.create = lambda thread_id, sandbox_id, **kwargs: calls.append((thread_id, sandbox_id, kwargs)) or SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox", container_id=f"container-{len(calls)}")
    backend.discover = lambda _sandbox_id: None
    provider._backend = backend
    user_file = tmp_path / "workspace" / "slide.json"
    user_file.parent.mkdir()
    user_file.write_text("persistent plan", encoding="utf-8")
    mounts = [(str(user_file.parent), "/mnt/user-data/workspace", False)]
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: mounts)
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: False)
    monkeypatch.setattr(provider, "_lark_broker_active", lambda *_args: False)
    monkeypatch.setattr(provider, "_local_config_mount_exclusion_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider, "_replica_count", lambda: (3, 0))
    monkeypatch.setattr(provider, "_probe_command_environment", lambda _info: supports_env)
    monkeypatch.setattr(provider, "_base_sandbox_id_for_thread", lambda *_args: "base-id")
    profile = SimpleNamespace(revision="revision-1", command_environment=lambda: {"IMAGE_GENERATION_API_KEY": "synthetic-secret"})
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: profile)
    destroyed = []
    monkeypatch.setattr(provider, "_destroy_unready_sandbox", lambda sandbox_id, info: destroyed.append((sandbox_id, info)))
    monkeypatch.setattr(provider, "_register_created_sandbox", lambda _thread, sandbox_id, _info, **_kwargs: sandbox_id)
    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)

    return provider, provider._image_profile_sandbox_id("base-id", profile.revision), calls, destroyed, user_file


@pytest.mark.parametrize("supports_env", [True, False])
def test_local_image_creation_uses_capability_and_preserves_mounts(monkeypatch, tmp_path, supports_env):
    provider, sandbox_id, calls, destroyed, user_file = _creation_provider(monkeypatch, tmp_path, supports_env=supports_env)

    assert provider._create_sandbox("thread", sandbox_id, user_id="user") == sandbox_id
    assert user_file.read_text(encoding="utf-8") == "persistent plan"
    assert len(calls) == 2
    assert calls[0][1].startswith("probe-")
    assert calls[0][1] != sandbox_id
    assert calls[1][1] == sandbox_id
    assert calls[0][2]["extra_mounts"] == calls[-1][2]["extra_mounts"]
    assert len(destroyed) == 1
    assert destroyed[0][0] == calls[0][1]
    if supports_env:
        assert "extra_environment" not in calls[0][2]
        assert "extra_environment" not in calls[1][2]
    else:
        assert "extra_environment" not in calls[0][2]
        assert calls[1][2]["extra_environment"]["IMAGE_GENERATION_API_KEY"] == "synthetic-secret"


@pytest.mark.asyncio
async def test_async_legacy_image_creation_replaces_only_unregistered_container(monkeypatch, tmp_path):
    provider, sandbox_id, calls, destroyed, user_file = _creation_provider(monkeypatch, tmp_path, supports_env=False)

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready_async", ready)
    assert await provider._create_sandbox_async("thread", sandbox_id, user_id="user") == sandbox_id
    assert len(calls) == 2
    assert len(destroyed) == 1
    assert calls[0][2]["extra_mounts"] == calls[1][2]["extra_mounts"]
    assert user_file.read_text(encoding="utf-8") == "persistent plan"


def test_probe_container_cannot_be_discovered_as_profile_container_even_if_teardown_fails(monkeypatch, tmp_path):
    provider, sandbox_id, calls, destroyed, _ = _creation_provider(monkeypatch, tmp_path, supports_env=False)
    assert provider._create_sandbox("thread", sandbox_id, user_id="user") == sandbox_id
    assert len(calls) == 2
    assert destroyed[0][0] != sandbox_id
    assert calls[1][1] == sandbox_id


@pytest.mark.parametrize("network_mode", ["open", "restricted"])
def test_local_backend_forwards_legacy_image_environment(monkeypatch, network_mode):
    backend = object.__new__(LocalContainerBackend)
    backend._container_prefix = "sandbox"
    backend._base_port = 8080
    backend._network_mode = network_mode
    backend._runtime = "docker"
    monkeypatch.setattr(local_backend_module, "get_free_port", lambda **_kwargs: 18080)
    monkeypatch.setattr(backend, "_sandbox_labels", lambda _sandbox_id: {})
    observed = []
    monkeypatch.setattr(backend, "_start_container", lambda *_args, **kwargs: observed.append(kwargs) or "container-id")
    if network_mode == "restricted":
        monkeypatch.setattr(backend, "_resource_names", lambda _sandbox_id: ("proxy", "internal"))
        monkeypatch.setattr(backend, "_egress_network_name", lambda _sandbox_id: "egress")
        monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id: "missing")
        monkeypatch.setattr(backend, "_create_internal_network", lambda *_args: None)
        monkeypatch.setattr(backend, "_create_egress_network", lambda *_args: None)
        monkeypatch.setattr(backend, "_start_network_proxy", lambda *_args: None)
        monkeypatch.setattr(backend, "_restricted_labels", lambda *_args: {})

    backend.create("thread", "id", extra_environment={"IMAGE_GENERATION_API_KEY": "synthetic-secret"})

    assert observed[0]["extra_environment"]["IMAGE_GENERATION_API_KEY"] == "synthetic-secret"
    if network_mode == "restricted":
        assert observed[0]["extra_environment"]["HTTP_PROXY"] == "http://proxy:3128"
