"""Native owner-scoped result reads against real SQLite and route admission."""

import asyncio
import threading

import httpx
import pytest
import pytest_asyncio

from deerflow.persistence.engine import close_engine
from extension_test_fixtures.batch_results_gateway import THREAD, create_app

URL = f"/api/threads/{THREAD}/subagent-batches/research-batch"


@pytest_asyncio.fixture
async def client(tmp_path):
    app = await create_app(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as value:
            yield value
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_native_saved_report_and_evidence_without_worker(client):
    response = await client.get(URL + "/items/0/result")
    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "succeeded" and "Full saved report" in saved["result"]
    assert saved["evidence"]["sources"][0]["document_name"] == "Captured.pdf"
    assert saved["evidence"]["sources"][0]["text"] == "Original source <script>window.PWNED = true</script>"
    assert len(saved["revision"]) == 64
    assert "DO NOT EXPOSE" not in response.text
    assert not {"prompt", "lease_owner", "execution_spec", "result_artifact"} & saved.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,status", [({"x-test-user": "bob"}, 404), ({"x-test-denied": "1"}, 403), ({"x-test-anonymous": "1"}, 401)])
async def test_native_owner_and_permission_guard(client, headers, status):
    response = await client.get(URL + "/items/0/result", headers=headers)
    assert response.status_code == status
    assert "Full saved report" not in response.text and "Captured.pdf" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("position,status", [(101, 404), (-1, 422), (100_000, 422), ("true", 422), ("0.5", 422)])
async def test_missing_or_invalid_position(client, position, status):
    response = await client.get(URL + f"/items/{position}/result")
    assert response.status_code == status
    assert "Full saved report" not in response.text


@pytest.mark.asyncio
async def test_summary_paging_and_pending_result(client):
    response = await client.get(URL + "/items?offset=100&limit=100")
    assert len(response.json()) == 1 and response.json()[0]["position"] == 100
    assert "result_artifact" not in response.text and '"result":' not in response.text
    saved = (await client.get(URL + "/items/50/result")).json()
    assert saved["status"] == "pending"
    assert saved["result"] is None and saved["evidence"] is None
    assert saved["acceptance_verdict"] is None


@pytest.mark.asyncio
async def test_thread_owner_change_revokes_historical_read(tmp_path):
    app = await create_app(tmp_path)
    try:
        await app.state.thread_store.update_owner(THREAD, "bob", user_id="alice")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            response = await client.get(URL + "/items/0/result")
            assert response.status_code == 404
            assert "Full saved report" not in response.text
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_missing_batch_wrong_thread_and_unavailable_repository(client):
    for url in (URL.replace("research-batch", "missing"), URL.replace(THREAD, "00000000-0000-0000-0000-000000000002")):
        response = await client.get(url + "/items/0/result")
        assert response.status_code == 404
        assert "Full saved report" not in response.text
    client._transport.app.state.subagent_batch_repo = None
    response = await client.get(URL + "/items/0/result")
    assert response.status_code == 503
    assert "Full saved report" not in response.text


@pytest.mark.asyncio
async def test_exact_position_and_one_row_read(client, monkeypatch):
    from unittest.mock import AsyncMock

    repo = client._transport.app.state.subagent_batch_repo
    read = AsyncMock(return_value=[{"position": 1, "result": "WRONG ROW"}])
    monkeypatch.setattr(repo, "list_items", read)
    response = await client.get(URL + "/items/0/result")
    assert response.status_code == 404
    assert "WRONG ROW" not in response.text
    read.assert_awaited_once_with("research-batch", user_id="alice", offset=0, limit=1, include_result=True)


@pytest.mark.asyncio
async def test_result_projection_keeps_the_request_loop_responsive(client, monkeypatch):
    from app.gateway.routers import subagent_batches

    entered, release = threading.Event(), threading.Event()
    original = subagent_batches.project_batch_result

    def paused(row):
        entered.set()
        assert release.wait(5), "Projection blocked the request loop"
        return original(row)

    monkeypatch.setattr(subagent_batches, "project_batch_result", paused)
    pending = asyncio.create_task(client.get(URL + "/items/0/result"))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        response = await asyncio.wait_for(client.get(URL + "/items?limit=1"), timeout=1)
        assert response.status_code == 200
        release.set()
        assert (await pending).status_code == 200
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
