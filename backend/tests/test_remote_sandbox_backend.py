from __future__ import annotations

import pytest
import requests

import deerflow.skills.storage as storage_mod
from deerflow.community.aio_sandbox import remote_backend as remote_backend_mod
from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
from deerflow.skills.types import SkillCategory


class _StubResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object | None = None,
        json_exc: Exception | None = None,
    ):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self._json_exc = json_exc
        self.ok = 200 <= status_code < 400
        self.text = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def test_list_running_delegates_to_provisioner_list(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    sandbox_info = SandboxInfo(sandbox_id="test-id", sandbox_url="http://localhost:8080")

    def mock_list():
        return [sandbox_info]

    monkeypatch.setattr(backend, "_provisioner_list", mock_list)

    assert backend.list_running() == [sandbox_info]


def test_provisioner_list_returns_sandbox_infos_and_filters_invalid_entries(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert timeout == 10
        assert headers == {}
        return _StubResponse(
            payload={
                "sandboxes": [
                    {"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"},
                    {"sandbox_id": "missing-url"},
                    {"sandbox_url": "http://k3s:31002"},
                ]
            }
        )

    monkeypatch.setattr(requests, "get", mock_get)

    infos = backend._provisioner_list()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc123"
    assert infos[0].sandbox_url == "http://k3s:31001"


def test_provisioner_list_sends_auth_header_when_api_key_set(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002", api_key="secret")
    captured: list[dict] = []

    def mock_get(url: str, timeout: int, headers=None):
        captured.append({"headers": headers})
        return _StubResponse(payload={"sandboxes": []})

    monkeypatch.setattr(requests, "get", mock_get)

    backend._provisioner_list()
    assert captured[0]["headers"] == {"X-API-Key": "secret"}


def test_provisioner_list_returns_empty_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        raise requests.RequestException("network down")

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_returns_empty_when_payload_is_not_dict(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(payload=[{"sandbox_id": "abc", "sandbox_url": "http://k3s:31001"}])

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_returns_empty_when_sandboxes_is_not_list(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(payload={"sandboxes": {"sandbox_id": "abc"}})

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_skips_non_dict_sandbox_entries(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(
            payload={
                "sandboxes": [
                    {"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"},
                    "bad-entry",
                    123,
                    None,
                ]
            }
        )

    monkeypatch.setattr(requests, "get", mock_get)

    infos = backend._provisioner_list()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc123"
    assert infos[0].sandbox_url == "http://k3s:31001"


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        ([SkillCategory.LEGACY], True),
        (["legacy"], True),
        ([SkillCategory.CUSTOM], False),
    ],
)
def test_user_should_see_legacy_skills_follows_storage_visibility_rule(monkeypatch, categories, expected):
    class _Storage:
        def load_skills(self, *, enabled_only: bool = False):
            assert enabled_only is False
            return [type("SkillStub", (), {"category": category})() for category in categories]

    monkeypatch.setattr(storage_mod, "get_or_new_user_skill_storage", lambda user_id: _Storage())

    assert storage_mod.user_should_see_legacy_skills("user-1") is expected


@pytest.mark.parametrize("expected_user_id", [None, "owner-1"])
def test_create_delegates_to_provisioner_create(monkeypatch, expected_user_id):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    expected = SandboxInfo(sandbox_id="abc123", sandbox_url="http://k3s:31001")

    def mock_create(thread_id: str, sandbox_id: str, extra_mounts=None, *, user_id=None, provision_lark_cli_runtime=False):
        assert thread_id == "thread-1"
        assert sandbox_id == "abc123"
        assert extra_mounts == [("/host", "/container", False)]
        assert user_id == expected_user_id
        assert provision_lark_cli_runtime is True
        return expected

    monkeypatch.setattr(backend, "_provisioner_create", mock_create)

    result = backend.create(
        "thread-1",
        "abc123",
        extra_mounts=[("/host", "/container", False)],
        user_id=expected_user_id,
        provision_lark_cli_runtime=True,
    )
    assert result == expected


def test_provisioner_create_returns_sandbox_info(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: True)

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert json == {
            "sandbox_id": "abc123",
            "thread_id": "thread-1",
            "user_id": "test-user-autouse",
            "include_legacy_skills": True,
            "provision_lark_cli_runtime": False,
        }
        assert timeout == 30
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "post", mock_post)

    info = backend._provisioner_create("thread-1", "abc123")
    assert info.sandbox_id == "abc123"
    assert info.sandbox_url == "http://k3s:31001"


def test_provisioner_create_forwards_supported_extra_mounts(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: False)

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert json["include_legacy_skills"] is False
        assert json["extra_mounts"] == [
            {
                "host_path": "/state/users/alice/skills/integrations",
                "container_path": "/mnt/skills/integrations",
                "read_only": True,
            },
            {
                "host_path": "/state/users/alice/integrations/lark-cli/config",
                "container_path": "/mnt/integrations/lark-cli/config",
                "read_only": False,
            },
        ]
        assert timeout == 30
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "post", mock_post)

    backend._provisioner_create(
        "thread-1",
        "abc123",
        extra_mounts=[
            ("/state/users/alice/threads/thread-1/user-data/workspace", "/mnt/user-data/workspace", False),
            ("/skills", "/mnt/skills", True),
            ("/state/users/alice/skills/integrations", "/mnt/skills/integrations", True),
            ("/state/users/alice/integrations/lark-cli/config", "/mnt/integrations/lark-cli/config", False),
        ],
        user_id="alice",
    )


def test_provisioner_create_strips_runtime_mount_when_init_container_enabled(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: False)

    captured: dict = {}

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        captured.update(json)
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "post", mock_post)

    backend._provisioner_create(
        "thread-1",
        "abc123",
        extra_mounts=[
            ("/state/users/alice/integrations/lark-cli/config", "/mnt/integrations/lark-cli/config", False),
            ("/state/users/alice/integrations/lark-cli/data", "/mnt/integrations/lark-cli/data", False),
            ("/state/integrations/lark-cli/sandbox-cli", "/mnt/integrations/lark-cli/runtime", True),
        ],
        user_id="alice",
        provision_lark_cli_runtime=True,
    )

    assert captured["provision_lark_cli_runtime"] is True
    container_paths = {mount["container_path"] for mount in captured["extra_mounts"]}
    # The init container supplies the runtime, so its mount is dropped, but the
    # per-user credential mounts are still forwarded.
    assert "/mnt/integrations/lark-cli/runtime" not in container_paths
    assert "/mnt/integrations/lark-cli/config" in container_paths
    assert "/mnt/integrations/lark-cli/data" in container_paths


def test_provisioner_create_keeps_runtime_mount_when_init_container_disabled(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: False)

    captured: dict = {}

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        captured.update(json)
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "post", mock_post)

    backend._provisioner_create(
        "thread-1",
        "abc123",
        extra_mounts=[
            ("/state/integrations/lark-cli/sandbox-cli", "/mnt/integrations/lark-cli/runtime", True),
        ],
        user_id="alice",
        provision_lark_cli_runtime=False,
    )

    assert captured["provision_lark_cli_runtime"] is False
    container_paths = {mount["container_path"] for mount in captured["extra_mounts"]}
    assert "/mnt/integrations/lark-cli/runtime" in container_paths


def test_provisioner_create_accepts_anonymous_thread_id(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: False)

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert json == {
            "sandbox_id": "anon123",
            "thread_id": None,
            "user_id": "test-user-autouse",
            "include_legacy_skills": False,
            "provision_lark_cli_runtime": False,
        }
        assert timeout == 30
        return _StubResponse(payload={"sandbox_id": "anon123", "sandbox_url": "http://k3s:31002"})

    monkeypatch.setattr(requests, "post", mock_post)

    info = backend.create(None, "anon123")
    assert info.sandbox_id == "anon123"
    assert info.sandbox_url == "http://k3s:31002"


def test_provisioner_create_raises_runtime_error_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(remote_backend_mod, "user_should_see_legacy_skills", lambda user_id: False)

    def mock_post(url: str, json: dict, timeout: int, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", mock_post)

    with pytest.raises(RuntimeError, match="Provisioner create failed"):
        backend._provisioner_create("thread-1", "abc123")


def test_destroy_delegates_to_provisioner_destroy(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    called: list[str] = []

    def mock_destroy(sandbox_id: str):
        called.append(sandbox_id)

    monkeypatch.setattr(backend, "_provisioner_destroy", mock_destroy)

    backend.destroy(SandboxInfo(sandbox_id="abc123", sandbox_url="http://k3s:31001"))
    assert called == ["abc123"]


def test_provisioner_destroy_calls_delete(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_delete(url: str, timeout: int, headers=None):
        assert url == "http://provisioner:8002/api/sandboxes/abc123"
        assert timeout == 15
        return _StubResponse(status_code=200)

    monkeypatch.setattr(requests, "delete", mock_delete)

    backend._provisioner_destroy("abc123")


def test_provisioner_destroy_swallows_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_delete(url: str, timeout: int, headers=None):
        raise requests.RequestException("network down")

    monkeypatch.setattr(requests, "delete", mock_delete)

    backend._provisioner_destroy("abc123")


def test_is_alive_delegates_to_provisioner_is_alive(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_is_alive(sandbox_id: str):
        assert sandbox_id == "abc123"
        return True

    monkeypatch.setattr(backend, "_provisioner_is_alive", mock_is_alive)

    alive = backend.is_alive(SandboxInfo(sandbox_id="abc123", sandbox_url="http://k3s:31001"))
    assert alive is True


def test_provisioner_is_alive_true_only_when_status_running(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get_running(url: str, timeout: int, headers=None):
        return _StubResponse(payload={"status": "Running"})

    monkeypatch.setattr(requests, "get", mock_get_running)
    assert backend._provisioner_is_alive("abc123") is True

    def mock_get_pending(url: str, timeout: int, headers=None):
        return _StubResponse(payload={"status": "Pending"})

    monkeypatch.setattr(requests, "get", mock_get_pending)
    assert backend._provisioner_is_alive("abc123") is False


def test_provisioner_is_alive_returns_false_on_404(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(status_code=404)

    monkeypatch.setattr(requests, "get", mock_get)
    assert backend._provisioner_is_alive("abc123") is False


def test_provisioner_is_alive_raises_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", mock_get)
    with pytest.raises(RuntimeError, match="Provisioner health check failed for abc123"):
        backend._provisioner_is_alive("abc123")


def test_provisioner_is_alive_raises_on_server_error(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        response = _StubResponse(status_code=503)
        response.text = "unavailable"
        return response

    monkeypatch.setattr(requests, "get", mock_get)
    with pytest.raises(RuntimeError, match="HTTP 503 unavailable"):
        backend._provisioner_is_alive("abc123")


def test_discover_delegates_to_provisioner_discover(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    expected = SandboxInfo(sandbox_id="abc123", sandbox_url="http://k3s:31001")

    def mock_discover(sandbox_id: str):
        assert sandbox_id == "abc123"
        return expected

    monkeypatch.setattr(backend, "_provisioner_discover", mock_discover)

    result = backend.discover("abc123")
    assert result == expected


def test_provisioner_discover_returns_none_on_404(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(status_code=404)

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_discover("abc123") is None


def test_provisioner_discover_returns_info_on_success(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "get", mock_get)

    info = backend._provisioner_discover("abc123")
    assert info is not None
    assert info.sandbox_id == "abc123"
    assert info.sandbox_url == "http://k3s:31001"


def test_provisioner_discover_returns_none_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_discover("abc123") is None
