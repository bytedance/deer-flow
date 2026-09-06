from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import backend as readiness


class _FakeAsyncClient:
    def __init__(
        self,
        *,
        responses: list[object],
        calls: list[str],
        timeout: float,
        request_timeouts: list[float] | None = None,
        trust_env: bool = True,
    ) -> None:
        self._responses = responses
        self._calls = calls
        self._timeout = timeout
        self._request_timeouts = request_timeouts
        self.trust_env = trust_env

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, *, timeout: float):
        self._calls.append(url)
        if self._request_timeouts is not None:
            self._request_timeouts.append(timeout)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _FakeLoop:
    def __init__(self, times: list[float]) -> None:
        self._times = times
        self._index = 0

    def time(self) -> float:
        value = self._times[self._index]
        self._index += 1
        return value


@pytest.mark.parametrize(
    ("sandbox_url", "expected"),
    [
        ("http://localhost:8080", False),
        ("http://127.0.0.1:8080", False),
        ("http://[::1]:8080", False),
        ("http://host.docker.internal:8080", False),
        ("http://host.containers.internal:8080", False),
        ("http://k3s:30001", False),
        ("http://10.0.0.8:8080", False),
        ("http://8.8.8.8:8080", True),
        ("http://[2606:4700:4700::1111]:8080", True),
        ("https://sandbox.example.com", True),
    ],
)
def test_sandbox_http_trust_env_only_uses_proxy_for_external_urls(sandbox_url: str, expected: bool) -> None:
    assert readiness.sandbox_http_trust_env(sandbox_url) is expected


def test_wait_for_sandbox_ready_bypasses_environment_proxy_for_docker_host(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[object] = []

    class FakeSession:
        trust_env = True

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, *_exc_info) -> None:
            return None

        def get(self, url: str, *, timeout: float):
            assert url == "http://host.docker.internal:8080/v1/sandbox"
            assert timeout == 5
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(readiness.requests, "Session", FakeSession)

    headers = {"X-DeerFlow-Relay-Token": "secret-token"}
    assert (
        readiness.wait_for_sandbox_ready(
            "http://host.docker.internal:8080",
            timeout=1,
            headers=headers,
        )
        is True
    )
    assert len(sessions) == 1
    assert sessions[0].trust_env is False
    assert sessions[0].headers == headers


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_uses_nonblocking_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    clients: list[_FakeAsyncClient] = []
    client_headers: list[dict[str, str]] = []

    def fake_client(*, timeout: float, trust_env: bool, headers: dict[str, str]):
        client_headers.append(headers)
        client = _FakeAsyncClient(
            responses=[SimpleNamespace(status_code=503), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
            trust_env=trust_env,
        )
        clients.append(client)
        return client

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")))
    monkeypatch.setattr(readiness.time, "sleep", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("time.sleep should not be used")))

    headers = {"X-DeerFlow-Relay-Token": "secret-token"}
    assert (
        await readiness.wait_for_sandbox_ready_async(
            "http://sandbox",
            timeout=5,
            poll_interval=0.05,
            headers=headers,
        )
        is True
    )

    assert calls == ["http://sandbox/v1/sandbox", "http://sandbox/v1/sandbox"]
    assert sleeps == [0.05]
    assert clients[0].trust_env is False
    assert client_headers == [headers]


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_retries_request_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float, trust_env: bool):
        return _FakeAsyncClient(
            responses=[readiness.httpx.ConnectError("not ready"), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
            trust_env=trust_env,
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=5, poll_interval=0.01) is True

    assert len(calls) == 2
    assert sleeps == [0.01]


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_clamps_request_and_sleep_to_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    request_timeouts: list[float] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float, trust_env: bool):
        return _FakeAsyncClient(
            responses=[SimpleNamespace(status_code=503)],
            calls=calls,
            timeout=timeout,
            request_timeouts=request_timeouts,
            trust_env=trust_env,
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness.asyncio, "get_running_loop", lambda: _FakeLoop([100.0, 100.5, 101.75, 102.0]))

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=2, poll_interval=1.0) is False

    assert calls == ["http://sandbox/v1/sandbox"]
    assert request_timeouts == [1.5]
    assert sleeps == [0.25]
