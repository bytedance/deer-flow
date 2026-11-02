"""Bounded, request-local detail checks retain WeKnora's authorization gate."""

import asyncio
from collections import Counter
from pathlib import Path

import httpx
import pytest

from deerflow.knowledge import KnowledgeRequestContext


@pytest.fixture
def setup_provider(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    monkeypatch.setenv("WK_CONCURRENCY_KEY", "synthetic")

    def create(*, gate=False, failure=None, hold=False):
        state = {"active": 0, "peak": 0, "calls": Counter(), "searches": 0}
        started, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            assert request.headers["X-API-Key"] == "synthetic"
            assert request.headers["X-Tenant-ID"] == "1"
            path = request.url.path
            if path == "/api/v1/knowledge-bases":
                data = [{"id": "kb", "name": "Synthetic"}]
            elif path.endswith("hybrid-search"):
                state["searches"] += 1
                data = [{"knowledge_id": f"doc-{i}", "content": f"chunk {i}"} for i in range(8)]
                data.insert(1, {"knowledge_id": "doc-0", "content": "second chunk"})
            else:
                doc = path.rsplit("/", 1)[1]
                state["calls"][doc] += 1
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                started.set()
                try:
                    if state["active"] == 4:
                        release.set()
                    if gate:
                        await asyncio.wait_for(release.wait(), 2)
                    if failure and doc == "doc-0":
                        return httpx.Response(failure, json={"success": False})
                    if hold:
                        await asyncio.Event().wait()
                    await asyncio.sleep(0)
                    data = {"id": doc, "knowledge_base_id": "kb", "parse_status": "completed", "enable_status": "enabled", "title": doc}
                finally:
                    state["active"] -= 1
            return httpx.Response(200, json={"success": True, "data": data})

        provider = WeKnoraProvider({"spaces": [{"base_url": "https://weknora.invalid", "tenant_id": "1", "api_key_env": "WK_CONCURRENCY_KEY", "user_ids": ["alice"]}]}, transport=httpx.MockTransport(handle))
        return provider, state, started

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [False, True])
async def test_details_overlap_with_a_bound_and_preserve_hit_order(setup_provider, selected):
    provider, state, _ = setup_provider(gate=True)
    ctx = KnowledgeRequestContext("alice", "lead_agent")
    if selected:
        catalog = await provider.catalog(context=ctx, page=1, page_size=20, search="")
        dataset = catalog.items[0].id
        ctx = KnowledgeRequestContext("alice", "lead_agent", {"version": 1, "mode": "selected", "dataset_ids": [dataset], "document_filters": [{"dataset_id": dataset, "document_ids": [f"doc-{i}" for i in range(8)]}]})
    result = await provider.search_scoped("q", context=ctx)
    assert state["peak"] == 4
    assert state["active"] == 0
    assert state["calls"] == Counter({f"doc-{i}": 1 for i in range(8)})
    assert [h.content for h in result.hits] == ["chunk 0", "second chunk", *[f"chunk {i}" for i in range(1, 8)]]
    assert [h.source.title for h in result.hits] == ["doc-0", "doc-0", *[f"doc-{i}" for i in range(1, 8)]]
    # A second call must revalidate documents rather than reuse authorization.
    await provider.search_scoped("q", context=ctx)
    assert all(n == 2 for n in state["calls"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,error", [(403, PermissionError), (404, FileNotFoundError), (500, RuntimeError)])
async def test_failure_drains_other_detail_requests_before_returning(setup_provider, failure, error):
    provider, state, _ = setup_provider(gate=True, failure=failure, hold=True)
    with pytest.raises(error):
        await asyncio.wait_for(provider.search_scoped("q", context=KnowledgeRequestContext("alice")), 5)
    assert state["peak"] == 4
    assert state["active"] == 0
    assert len(state["calls"]) == 4  # Later batches never start after failure.


@pytest.mark.asyncio
async def test_cancellation_drains_detail_requests(setup_provider):
    provider, state, started = setup_provider(hold=True)
    task = asyncio.create_task(provider.search_scoped("q", context=KnowledgeRequestContext("alice")))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["active"] == 0


@pytest.mark.asyncio
async def test_selected_document_denial_prevents_search(setup_provider):
    provider, state, _ = setup_provider(gate=True, failure=403, hold=True)
    catalog = await provider.catalog(context=KnowledgeRequestContext("alice"), page=1, page_size=20, search="")
    dataset = catalog.items[0].id
    ctx = KnowledgeRequestContext("alice", "lead_agent", {"version": 1, "mode": "selected", "dataset_ids": [dataset], "document_filters": [{"dataset_id": dataset, "document_ids": [f"doc-{i}" for i in range(8)]}]})
    with pytest.raises(PermissionError):
        await asyncio.wait_for(provider.search_scoped("q", context=ctx), 5)
    assert state["searches"] == 0
    assert state["active"] == 0


@pytest.mark.asyncio
async def test_equal_native_ids_in_different_tenants_are_revalidated(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    monkeypatch.setenv("WK_ONE", "key-one")
    monkeypatch.setenv("WK_TWO", "key-two")
    details = []

    async def handle(request):
        tenant = request.headers["X-Tenant-ID"]
        assert request.headers["X-API-Key"] == {"1": "key-one", "2": "key-two"}[tenant]
        if request.url.path == "/api/v1/knowledge-bases":
            data = [{"id": "kb", "name": tenant}]
        elif request.url.path.endswith("hybrid-search"):
            data = [{"knowledge_id": "same-id", "content": f"evidence {tenant}"}]
        else:
            details.append(tenant)
            data = {"id": "same-id", "knowledge_base_id": "kb", "parse_status": "completed", "enable_status": "enabled", "title": tenant}
        return httpx.Response(200, json={"success": True, "data": data})

    provider = WeKnoraProvider(
        {"spaces": [{"base_url": "https://weknora.invalid", "tenant_id": tenant, "api_key_env": key, "user_ids": ["alice"]} for tenant, key in [("1", "WK_ONE"), ("2", "WK_TWO")]]}, transport=httpx.MockTransport(handle)
    )
    result = await provider.search_scoped("q", context=KnowledgeRequestContext("alice"))
    assert details == ["1", "2"]
    assert [hit.source.title for hit in result.hits] == ["1", "2"]


@pytest.mark.asyncio
async def test_result_cap_checks_empty_hits_but_not_the_unconsumed_suffix(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    monkeypatch.setenv("WK_CAP_KEY", "synthetic")
    details = []

    async def handle(request):
        path = request.url.path
        if path == "/api/v1/knowledge-bases":
            data = [{"id": "first", "name": "First"}, {"id": "last", "name": "Last"}]
        elif path.endswith("first/hybrid-search"):
            data = [{"knowledge_id": "first-doc", "content": f"chunk {i}"} for i in range(99)]
        elif path.endswith("last/hybrid-search"):
            data = [{"knowledge_id": "empty-doc", "content": ""}, {"knowledge_id": "last-doc", "content": "last chunk"}, {"knowledge_id": "unsafe/path", "content": "unconsumed"}]
        else:
            doc = path.rsplit("/", 1)[1]
            details.append(doc)
            data = {"id": doc, "knowledge_base_id": "first" if doc == "first-doc" else "last", "parse_status": "completed", "enable_status": "enabled", "title": doc}
        return httpx.Response(200, json={"success": True, "data": data})

    provider = WeKnoraProvider({"spaces": [{"base_url": "https://weknora.invalid", "tenant_id": "1", "api_key_env": "WK_CAP_KEY", "user_ids": ["alice"]}]}, transport=httpx.MockTransport(handle))
    result = await provider.search_scoped("q", context=KnowledgeRequestContext("alice"))
    assert len(result.hits) == 100
    assert result.hits[-1].content == "last chunk"
    assert details == ["first-doc", "empty-doc", "last-doc"]
