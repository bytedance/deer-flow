from __future__ import annotations

import pytest
import requests

from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


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

    def mock_get(url: str, timeout: int):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert timeout == 10
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


def test_provisioner_list_returns_empty_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        raise requests.RequestException("network down")

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_returns_empty_when_payload_is_not_dict(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        return _StubResponse(payload=[{"sandbox_id": "abc", "sandbox_url": "http://k3s:31001"}])

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_returns_empty_when_sandboxes_is_not_list(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        return _StubResponse(payload={"sandboxes": {"sandbox_id": "abc"}})

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_list() == []


def test_provisioner_list_skips_non_dict_sandbox_entries(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
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


def test_create_delegates_to_provisioner_create(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")
    expected = SandboxInfo(sandbox_id="abc123", sandbox_url="http://k3s:31001")

    def mock_create(thread_id: str, sandbox_id: str, extra_mounts=None):
        assert thread_id == "thread-1"
        assert sandbox_id == "abc123"
        assert extra_mounts == [("/host", "/container", False)]
        return expected

    monkeypatch.setattr(backend, "_provisioner_create", mock_create)

    result = backend.create("thread-1", "abc123", extra_mounts=[("/host", "/container", False)])
    assert result == expected


def test_provisioner_create_returns_sandbox_info(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_post(url: str, json: dict, timeout: int):
        assert url == "http://provisioner:8002/api/sandboxes"
        assert json == {"sandbox_id": "abc123", "thread_id": "thread-1"}
        assert timeout == 30
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "post", mock_post)

    info = backend._provisioner_create("thread-1", "abc123")
    assert info.sandbox_id == "abc123"
    assert info.sandbox_url == "http://k3s:31001"


def test_provisioner_create_raises_runtime_error_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_post(url: str, json: dict, timeout: int):
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

    def mock_delete(url: str, timeout: int):
        assert url == "http://provisioner:8002/api/sandboxes/abc123"
        assert timeout == 15
        return _StubResponse(status_code=200)

    monkeypatch.setattr(requests, "delete", mock_delete)

    backend._provisioner_destroy("abc123")


def test_provisioner_destroy_swallows_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_delete(url: str, timeout: int):
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

    def mock_get_running(url: str, timeout: int):
        return _StubResponse(payload={"status": "Running"})

    monkeypatch.setattr(requests, "get", mock_get_running)
    assert backend._provisioner_is_alive("abc123") is True

    def mock_get_pending(url: str, timeout: int):
        return _StubResponse(payload={"status": "Pending"})

    monkeypatch.setattr(requests, "get", mock_get_pending)
    assert backend._provisioner_is_alive("abc123") is False


def test_provisioner_is_alive_returns_false_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", mock_get)
    assert backend._provisioner_is_alive("abc123") is False


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

    def mock_get(url: str, timeout: int):
        return _StubResponse(status_code=404)

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_discover("abc123") is None


def test_provisioner_discover_returns_info_on_success(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        return _StubResponse(payload={"sandbox_id": "abc123", "sandbox_url": "http://k3s:31001"})

    monkeypatch.setattr(requests, "get", mock_get)

    info = backend._provisioner_discover("abc123")
    assert info is not None
    assert info.sandbox_id == "abc123"
    assert info.sandbox_url == "http://k3s:31001"


def test_provisioner_discover_returns_none_on_request_exception(monkeypatch):
    backend = RemoteSandboxBackend("http://provisioner:8002")

    def mock_get(url: str, timeout: int):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", mock_get)

    assert backend._provisioner_discover("abc123") is None
