"""Actual declared plugin actions/assets with native SQLite and host admission."""

import httpx
import pytest
import pytest_asyncio

from deerflow.persistence.engine import close_engine
from extension_test_fixtures.batch_review_gateway import THREAD, create_app

ACTION = "/api/plugins/community.batch-review/actions/"


@pytest_asyncio.fixture
async def client(tmp_path):
    app = await create_app(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as value:
            yield value
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_declared_plugin_http_reads_and_saved_evidence(client):
    response = await client.post(ACTION + "batches", json={"thread_id": THREAD})
    assert response.status_code == 200
    assert response.json()[0]["id"] == "research-batch"
    assert "DO NOT EXPOSE" not in response.text
    response = await client.post(ACTION + "items", json={"thread_id": THREAD, "batch_id": "research-batch"})
    assert response.status_code == 200 and len(response.json()) == 50
    assert all("result" not in row and "evidence" not in row for row in response.json())
    response = await client.post(ACTION + "result", json={"thread_id": THREAD, "batch_id": "research-batch", "position": 0})
    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "succeeded" and "Full saved report" in saved["result"]
    assert saved["evidence"]["sources"][0]["document_name"] == "Captured.pdf"
    assert saved["evidence"]["sources"][0]["text"] == "Original source <script>window.PWNED = true</script>"
    assert len(saved["revision"]) == 64
    assert "DO NOT EXPOSE" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,status", [({"x-test-user": "bob"}, 404), ({"x-test-denied": "1"}, 403), ({"x-deerflow-plugin-viewer": "old-account"}, 409)])
async def test_http_owner_permission_and_viewer_fences(client, headers, status):
    response = await client.post(ACTION + "result", headers=headers, json={"thread_id": THREAD, "batch_id": "research-batch", "position": 0})
    assert response.status_code == status
    assert "Full saved report" not in response.text and "Captured.pdf" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates,status", [({"thread_id": "other-thread"}, 404), ({"batch_id": "missing"}, 404), ({"position": 100}, 404), ({"position": -1}, 422), ({"position": True}, 422), ({"position": "0"}, 422), ({"user_id": "bob"}, 422)]
)
async def test_http_bad_scope_and_invalid_payload_do_not_expose_results(client, updates, status):
    response = await client.post(ACTION + "result", json={"thread_id": THREAD, "batch_id": "research-batch", "position": 0, **updates})
    assert response.status_code == status
    assert "Full saved report" not in response.text


@pytest.mark.asyncio
async def test_http_page_end_and_pending_item_are_not_completed_or_verified(client):
    response = await client.post(ACTION + "items", json={"thread_id": THREAD, "batch_id": "research-batch", "offset": 50})
    assert len(response.json()) == 1 and response.json()[0]["position"] == 50
    response = await client.post(ACTION + "items", json={"thread_id": THREAD, "batch_id": "research-batch", "offset": 51})
    assert response.json() == []
    response = await client.post(ACTION + "result", json={"thread_id": THREAD, "batch_id": "research-batch", "position": 50})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["result"] is None and response.json()["evidence"] is None
    assert response.json()["acceptance_verdict"] is None


@pytest.mark.asyncio
async def test_actual_manifest_and_assets_load_through_host_plugin_router(client):
    response = await client.get("/api/plugins")
    assert response.status_code == 200
    contributions = response.json()
    assert len(contributions) == 1
    entry = contributions[0]
    assert entry["namespace"] == "community.batch-review" and entry["transport"] == "assets-v1"
    response = await client.get(entry["entry"])
    assert response.status_code == 200 and "mountReview" in response.text
    relative = entry["entry"].rsplit("/", 1)[0] + "/review.mjs"
    response = await client.get(relative)
    assert response.status_code == 200 and "textContent" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_real_thread_owner_change_blocks_read_even_when_batch_owner_matches(tmp_path):
    app = await create_app(tmp_path)
    try:
        await app.state.preview_thread_store.update_owner(THREAD, "bob", user_id="alice")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            batches = await client.post(ACTION + "batches", json={"thread_id": THREAD})
            assert batches.status_code == 200 and batches.json() == []
            for action, extra in (("items", {}), ("result", {"position": 0})):
                response = await client.post(ACTION + action, json={"thread_id": THREAD, "batch_id": "research-batch", **extra})
                assert response.status_code == 404
                assert "Full saved report" not in response.text and "Captured.pdf" not in response.text
    finally:
        await close_engine()
