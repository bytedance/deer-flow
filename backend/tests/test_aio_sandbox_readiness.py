from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import backend as readiness


class _FakeAsyncClient:
    def __init__(self, *, responses: list[object], calls: list[str], timeout: float) -> None:
        self._responses = responses
        self._calls = calls
        self._timeout = timeout

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str):
        self._calls.append(url)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_uses_nonblocking_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float):
        return _FakeAsyncClient(
            responses=[SimpleNamespace(status_code=503), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")))
    monkeypatch.setattr(readiness.time, "sleep", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("time.sleep should not be used")))

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=5, poll_interval=0.05) is True

    assert calls == ["http://sandbox/v1/sandbox", "http://sandbox/v1/sandbox"]
    assert sleeps == [0.05]


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_retries_request_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float):
        return _FakeAsyncClient(
            responses=[readiness.httpx.ConnectError("not ready"), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=5, poll_interval=0.01) is True

    assert len(calls) == 2
    assert sleeps == [0.01]
