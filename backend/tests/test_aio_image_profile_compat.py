"""Compatibility of managed image profiles with old local AIO containers."""

import threading
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_module
from deerflow.community.aio_sandbox import local_backend as local_backend_module
from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
from deerflow.community.aio_sandbox.backend import SandboxCreationError
from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
from deerflow.config.app_config import AppConfig
from deerflow.config.image_generation import ImageGenerationDefaultStore, ManagedImageGenerationProfile, ManagedImageGenerationProfileStore, bind_image_generation_source, image_profile_container_identity


@pytest.mark.parametrize("failure", ["catalog", "default", "provider"])
def test_generic_aio_identity_and_binding_ignore_image_configuration_failures(monkeypatch, tmp_path, failure):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    provider = object.__new__(AioSandboxProvider)
    provider._config = {"skills_container_path": "/mnt/skills"}
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_thread_skill_projection_active", lambda *_args: False)
    environment = {"IMAGE_GENERATION_PROVIDER": "openai", "IMAGE_GENERATION_MODEL": "synthetic-model", "IMAGE_GENERATION_API_KEY": "synthetic-key"}
    if failure == "provider":
        environment["IMAGE_GENERATION_PROVIDER"] = "invalid-provider"
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    if failure == "catalog":
        monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: (_ for _ in ()).throw(ValueError("unreadable catalog")))
    elif failure == "default":
        web = ManagedImageGenerationProfile(name="web", provider="openai", model="web-model", base_url="https://web.example/v1", api_key="synthetic-web-key", revision="revision-1")
        monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: [web])
        monkeypatch.setattr(ImageGenerationDefaultStore, "read", lambda _self: (_ for _ in ()).throw(ValueError("malformed default")))
    else:
        monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: [])

    base = provider._base_sandbox_id_for_thread("thread", "user")
    assert provider._sandbox_id_for_thread("thread", "user") == base
    sandbox = SimpleNamespace(id=base)
    provider._bind_image_profile_context(sandbox, "thread", "user")
    assert sandbox._deerflow_image_profile_revision is None
    assert sandbox._deerflow_server_image_storage_identity is None

    monkeypatch.setattr(image_tool, "get_app_config", lambda: config)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = image_tool.generate_image_tool.func(SimpleNamespace(context={}, state={}), "/mnt/user-data/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result.startswith("Error: IMAGE_PROVIDER_INVALID_CONFIG")


def test_generic_aio_typed_server_profile_ignores_unreadable_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    provider = object.__new__(AioSandboxProvider)
    provider._backend = object.__new__(LocalContainerBackend)
    config = AppConfig.model_validate({"sandbox": {"use": "test"}, "image_generation": {"provider": "openai", "model": "synthetic-model", "base_url": "https://server.example/v1", "api_key": "synthetic-key"}})
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: (_ for _ in ()).throw(ValueError("unreadable catalog")))
    assert provider._typed_server_image_profile() is None


def test_valid_typed_server_image_keeps_its_separate_aio_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: [])
    config = AppConfig.model_validate({"sandbox": {"use": "test"}, "image_generation": {"provider": "openai", "model": "synthetic-model", "base_url": "https://server.example/v1", "api_key": "synthetic-key"}})
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    provider = object.__new__(AioSandboxProvider)
    provider._config = {"skills_container_path": "/mnt/skills"}
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_thread_skill_projection_active", lambda *_args: False)

    base = provider._base_sandbox_id_for_thread("thread", "user")
    identity = image_profile_container_identity(config.image_generation)
    sandbox_id = provider._image_config_sandbox_id(base, identity)
    assert provider._sandbox_id_for_thread("thread", "user") == sandbox_id
    sandbox = SimpleNamespace(id=sandbox_id)
    provider._bind_image_profile_context(sandbox, "thread", "user")
    assert sandbox._deerflow_server_image_storage_identity == identity
    assert provider._typed_server_image_profile() == config.image_generation


def test_profile_revision_changes_local_sandbox_identity_without_changing_base(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(provider_module, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test", "environment": {}}}))
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


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_generic_aio_capacity_ignores_image_configuration_failures(monkeypatch, tmp_path, async_mode):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: [])
    provider, _, calls, _, _ = _creation_provider(monkeypatch, tmp_path, supports_env=True)
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: None)
    monkeypatch.setattr(provider, "_typed_server_image_profile", lambda: None)
    monkeypatch.setattr(provider, "_replica_count", lambda: (1, 1))
    monkeypatch.setattr(provider, "_evict_oldest_warm", lambda *, protected_thread=None: None)
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"IMAGE_GENERATION_PROVIDER": "invalid-provider"}}})
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready_async", ready)
    if async_mode:
        assert await provider._create_sandbox_async("thread", "base-id", user_id="user") == "base-id"
    else:
        assert provider._create_sandbox("thread", "base-id", user_id="user") == "base-id"
    assert len(calls) == 1
    assert calls[0][1] == "base-id"


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
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("failed_stage", ["probe", "final"])
async def test_image_creation_rejection_cleans_up_the_failed_identity(monkeypatch, tmp_path, async_mode, failed_stage):
    provider, sandbox_id, calls, destroyed, _ = _creation_provider(monkeypatch, tmp_path, supports_env=True)
    original_create = provider._backend.create

    def reject_stage(thread_id, created_id, **kwargs):
        info = original_create(thread_id, created_id, **kwargs)
        if (failed_stage == "probe" and len(calls) == 1) or (failed_stage == "final" and len(calls) == 2):
            raise SandboxCreationError("synthetic rejection", info=info)
        return info

    provider._backend.create = reject_stage

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready_async", ready)
    with pytest.raises(SandboxCreationError, match="synthetic rejection"):
        if async_mode:
            await provider._create_sandbox_async("thread", sandbox_id, user_id="user")
        else:
            provider._create_sandbox("thread", sandbox_id, user_id="user")

    assert len(calls) == (1 if failed_stage == "probe" else 2)
    assert [created_id for created_id, _ in destroyed] == [created_id for _, created_id, _ in calls]


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


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_chat_image_choice_does_not_evict_the_prior_thread_container(monkeypatch, tmp_path, async_mode):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true")
    config = AppConfig.model_validate(
        {
            "sandbox": {
                "use": "test",
                "environment": {
                    "IMAGE_GENERATION_PROVIDER": "openai",
                    "IMAGE_GENERATION_MODEL": "synthetic-model",
                    "IMAGE_GENERATION_API_KEY": "synthetic-key",
                },
            }
        }
    )
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    monkeypatch.setattr(ManagedImageGenerationProfileStore, "list", lambda _self: (_ for _ in ()).throw(ValueError("unreadable catalog")))
    provider, _, calls, destroyed, _ = _creation_provider(monkeypatch, tmp_path, supports_env=True)
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: None)
    monkeypatch.setattr(provider, "_replica_count", lambda: (1, 1))
    protected = []
    monkeypatch.setattr(provider, "_evict_oldest_warm", lambda *, protected_thread=None: protected.append(protected_thread) or None)

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready_async", ready)
    with bind_image_generation_source("sandbox_environment"):
        if async_mode:
            assert await provider._create_sandbox_async("thread", "server-choice-id", user_id="user") == "server-choice-id"
        else:
            assert provider._create_sandbox("thread", "server-choice-id", user_id="user") == "server-choice-id"
    assert protected == [("user", "thread")]
    assert len(calls) == 1
    assert destroyed == []


def test_capacity_eviction_skips_a_chat_choice_thread(monkeypatch):
    provider = object.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    prior = SandboxInfo(sandbox_id="prior", sandbox_url="http://sandbox", container_id="prior")
    other = SandboxInfo(sandbox_id="other", sandbox_url="http://sandbox", container_id="other")
    provider._warm_pool = {"prior": (prior, 1), "other": (other, 2)}
    provider._warm_pool_identity = {"prior": ("user", "thread"), "other": ("other-user", "other-thread")}
    removed = []
    monkeypatch.setattr(provider, "_destroy_warm_entry", lambda sandbox_id, _entry, **_kwargs: removed.append(sandbox_id) or True)
    assert provider._evict_oldest_warm(protected_thread=("user", "thread")) == "other"
    assert removed == ["other"]


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
