from __future__ import annotations

import ssl
from pathlib import Path
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
        ("http://sandbox-test-svc.deer-flow.svc.cluster.local:8080", False),
        ("http://SANDBOX-TEST-SVC.DEER-FLOW.SVC.CLUSTER.LOCAL.:8080", False),
        ("https://sandbox-test-svc.deer-flow.svc.cluster.local:8443", True),
        ("https://SANDBOX-TEST-SVC.DEER-FLOW.SVC.CLUSTER.LOCAL.:8443", True),
        ("http://10.0.0.8:8080", False),
        ("http://8.8.8.8:8080", True),
        ("http://[2606:4700:4700::1111]:8080", True),
        ("https://sandbox.example.com", True),
        ("https://sandbox.svc.cluster.local.example.com", True),
        ("https://sandbox.not-svc.cluster.local", True),
    ],
)
def test_sandbox_http_trust_env_only_uses_proxy_for_external_urls(sandbox_url: str, expected: bool) -> None:
    assert readiness.sandbox_http_trust_env(sandbox_url) is expected


@pytest.mark.parametrize(
    ("sandbox_url", "uses_proxy"),
    [
        ("http://host.docker.internal:8080", False),
        ("http://sandbox-test-svc.deer-flow.svc.cluster.local:8080", False),
        ("https://sandbox-test-svc.deer-flow.svc.cluster.local:8443", True),
        ("https://sandbox.example.com", True),
    ],
)
def test_wait_for_sandbox_ready_routes_environment_proxy(monkeypatch: pytest.MonkeyPatch, sandbox_url: str, uses_proxy: bool) -> None:
    import requests

    calls = []

    def send(_adapter, request, **kwargs):
        calls.append((request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = b"{}"
        return response

    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(variable, "http://proxy.example:3128")
    for variable in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(variable, "")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)

    headers = {"X-DeerFlow-Relay-Token": "secret-token"}
    assert (
        readiness.wait_for_sandbox_ready(
            sandbox_url,
            timeout=30,
            headers=headers,
        )
        is True
    )
    assert len(calls) == 1
    request, options = calls[0]
    assert request.url == f"{sandbox_url}/v1/sandbox"
    assert request.headers["X-DeerFlow-Relay-Token"] == headers["X-DeerFlow-Relay-Token"]
    assert options["timeout"] == 5
    assert bool(options["proxies"]) is uses_proxy


@pytest.fixture
def kubernetes_ca_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Use one real CA so an environment-selected trust store is distinguishable
    # from the default bundle, without generating keys or contacting a server.
    default_bundle = Path(readiness.requests.certs.where()).read_text(encoding="ascii")
    _, begin, certificate = default_bundle.partition("-----BEGIN CERTIFICATE-----")
    certificate, end, _ = certificate.partition("-----END CERTIFICATE-----")
    bundle = tmp_path / "sandbox-ca.pem"
    bundle.write_text(begin + certificate + end + "\n", encoding="ascii")
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(variable, "http://proxy.example:3128")
    for variable in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(variable, "sandbox-test-svc.deer-flow.svc.cluster.local")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    return bundle


def test_https_kubernetes_readiness_preserves_requests_ca_bundle(monkeypatch: pytest.MonkeyPatch, kubernetes_ca_bundle: Path) -> None:
    calls = []

    def send(_adapter, request, **kwargs):
        calls.append(kwargs)
        response = readiness.requests.Response()
        response.status_code = 200
        response.request = request
        response._content = b"{}"
        return response

    monkeypatch.setattr(readiness.requests.adapters.HTTPAdapter, "send", send)

    assert readiness.wait_for_sandbox_ready("https://sandbox-test-svc.deer-flow.svc.cluster.local:8443") is True
    assert len(calls) == 1
    assert not calls[0]["proxies"]  # NO_PROXY already makes this a direct connection.
    assert calls[0]["verify"] == str(kubernetes_ca_bundle)


@pytest.mark.anyio
async def test_https_kubernetes_readiness_preserves_httpx_ca_bundle(monkeypatch: pytest.MonkeyPatch, kubernetes_ca_bundle: Path) -> None:
    contexts: list[ssl.SSLContext] = []
    requests = []
    create_default_context = ssl.create_default_context

    def create_context(*args, **kwargs):
        context = create_default_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def handle_request(_transport, request):
        requests.append(str(request.url))
        return readiness.httpx.Response(200, request=request, json={})

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(readiness.httpx.AsyncHTTPTransport, "handle_async_request", handle_request)

    assert await readiness.wait_for_sandbox_ready_async("https://sandbox-test-svc.deer-flow.svc.cluster.local:8443") is True
    assert requests == ["https://sandbox-test-svc.deer-flow.svc.cluster.local:8443/v1/sandbox"]
    expected_ca = ssl.PEM_cert_to_DER_cert(kubernetes_ca_bundle.read_text(encoding="ascii"))
    assert contexts
    for context in contexts:
        assert context.get_ca_certs(binary_form=True) == [expected_ca]
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True


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


def test_wait_for_sandbox_ready_times_out_on_the_monotonic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync readiness budget is measured on the monotonic clock.

    Regression for the sync poller measuring its ``timeout`` with wall-clock
    ``time.time()``: a backward wall-clock step (NTP / VM resume / manual change)
    while polling must not stretch the readiness wait past ``timeout`` — on the
    acquisition path that would pin the acquiring thread far past the budget. The
    async twin already deadlines on ``loop.time()``; this pins the sync twin to
    the same monotonic contract.

    The monotonic clock is scripted to advance past the deadline after two polls
    while the wall clock steps backward on every read. With the fix the loop
    exits on the monotonic deadline after exactly two polls; a wall-clock loop
    would never reach ``timeout`` and keep polling until the scripted response
    queue is exhausted, surfacing as a hard failure instead of a hang.
    """
    # start, loop1 top, after get1, loop2 top, after get2, loop3 top (past deadline)
    monotonic_values = iter([100.0, 100.1, 100.2, 100.3, 100.4, 102.5])

    def fake_monotonic() -> float:
        return next(monotonic_values)

    wall = 1_000_000.0

    def fake_wall_time() -> float:
        # Steps backward on every read; a wall-clock loop never reaches timeout.
        nonlocal wall
        wall -= 1_000.0
        return wall

    sleeps: list[float] = []

    class FakeSession:
        trust_env = True

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            # Exactly two "not ready" probes are scripted. The monotonic loop
            # makes two polls before the deadline; a wall-clock loop would make a
            # third and raise StopIteration here.
            self._responses = iter([SimpleNamespace(status_code=503), SimpleNamespace(status_code=503)])

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info) -> None:
            return None

        def get(self, url: str, *, timeout: float):
            return next(self._responses)

    monkeypatch.setattr(readiness.requests, "Session", FakeSession)
    monkeypatch.setattr(readiness.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(readiness.time, "time", fake_wall_time)
    monkeypatch.setattr(readiness.time, "sleep", lambda delay: sleeps.append(delay))

    assert readiness.wait_for_sandbox_ready("http://sandbox", timeout=2) is False
    assert sleeps == [1.0, 1.0]


def test_wait_for_sandbox_ready_clamps_request_and_sleep_to_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync poller clamps the per-probe timeout and sleep to the budget.

    Regression for the sync twin overshooting ``timeout``: it polled with a
    fixed 5s request timeout and slept a fixed 1s, so a single slow probe plus
    its backoff could run the wait up to ~6s past the budget — on the 5s
    acquisition path (``local_backend``) that roughly doubles it. Mirror the
    async twin's clamp (``min(5.0, remaining)`` / ``min(1.0, remaining)``) so the
    budget the readiness comment now promises is actually honored. Scripted
    monotonic values match ``...async_clamps_request_and_sleep_to_deadline``.
    """
    # start, loop top, after get (503), loop top (past deadline)
    monotonic_values = iter([100.0, 100.5, 101.75, 102.0])

    def fake_monotonic() -> float:
        return next(monotonic_values)

    request_timeouts: list[float] = []
    sleeps: list[float] = []

    class FakeSession:
        trust_env = True

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info) -> None:
            return None

        def get(self, url: str, *, timeout: float):
            request_timeouts.append(timeout)
            return SimpleNamespace(status_code=503)

    monkeypatch.setattr(readiness.requests, "Session", FakeSession)
    monkeypatch.setattr(readiness.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(readiness.time, "sleep", lambda delay: sleeps.append(delay))

    # timeout=2 -> deadline at +2. First probe sees remaining 1.5 (clamped under
    # the 5s ceiling); the post-probe remaining is 0.25, clamping the sleep; the
    # next loop check is exactly at the deadline and exits.
    assert readiness.wait_for_sandbox_ready("http://sandbox", timeout=2) is False
    assert request_timeouts == [1.5]
    assert sleeps == [0.25]
