"""Public extension reads complement the existing model-facing batch reader."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api.batch_results import BATCH_RESULTS_RESOLVER_KEY, BatchResultError, require_batch_results, resolve_batch_results

from app.gateway.app import create_app
from deerflow.extensions.batch_results import RepositoryBatchResultReader

SOURCE_ID = "a" * 32 + "-1"


def source(**updates):
    return {
        "id": SOURCE_ID,
        "provider": "ragflow",
        "dataset_id": "dataset",
        "document_id": "document",
        "chunk_id": "chunk",
        "dataset_name": "Original dataset",
        "document_name": "Original.pdf",
        "text": "Saved excerpt <script>not executable</script>",
        "pages": [1, 2],
        "truncated": False,
        **updates,
    }


@pytest.fixture
def storage():
    row = {
        "id": "item",
        "position": 0,
        "item_key": "research",
        "status": "succeeded",
        "attempt": 1,
        "result": f"Report [citation:1](#knowledge-{SOURCE_ID})",
        "result_preview": "Report",
        "result_truncated": False,
        "acceptance_criteria": ["file_exists:report.md"],
        "acceptance_verdict": {"all_hold": False},
        "result_artifact": {"knowledge_sources": {"version": 1, "sources": [source()], "omitted_count": 2}, "secret": "PRIVATE"},
        "prompt": "PRIVATE",
        "lease_owner": "PRIVATE",
        "execution_spec": {"secret": "PRIVATE"},
    }
    batch = {"id": "batch", "thread_id": "thread", "user_id": "owner", "title": "Research", "execution_spec": {"secret": "PRIVATE"}}
    repo = SimpleNamespace(get_batch=AsyncMock(return_value=batch), list_by_thread=AsyncMock(return_value=[batch]), list_items=AsyncMock(return_value=[row]))
    allowed = AsyncMock(return_value=True)
    reader = RepositoryBatchResultReader(repo, user_id="owner", check_thread=allowed)
    return SimpleNamespace(repo=repo, row=row, batch=batch, allowed=allowed, reader=reader)


def test_gateway_registers_request_bound_batch_result_reader():
    app = create_app()
    resolver = getattr(app.state, "deerflow_extension_batch_results_resolver", None)
    assert callable(resolver), "Extensions cannot currently read captured durable batch results through a public request-bound capability"


def test_optional_request_capability_does_not_import_framework_or_fallback():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert resolve_batch_results(request) is None
    with pytest.raises(BatchResultError) as unsupported:
        require_batch_results(request)
    assert unsupported.value.status_code == 503
    setattr(request.app.state, BATCH_RESULTS_RESOLVER_KEY, lambda request: (_ for _ in ()).throw(RuntimeError("resolver failure")))
    with pytest.raises(RuntimeError, match="resolver failure"):
        resolve_batch_results(request)


@pytest.mark.asyncio
async def test_result_public_projection_excludes_secrets_and_detaches_snapshot(storage):
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert result["result"] == storage.row["result"]
    assert result["evidence"]["sources"] == [source()]
    assert result["evidence"]["omitted_count"] == 2
    assert "PRIVATE" not in str(result)
    assert len(result["revision"]) == 64
    result["evidence"]["sources"][0]["pages"].append(999)
    result["acceptance_criteria"].append("mutated locally")
    assert storage.row["result_artifact"]["knowledge_sources"]["sources"][0]["pages"] == [1, 2]
    assert storage.row["acceptance_criteria"] == ["file_exists:report.md"]
    storage.repo.list_items.assert_awaited_once_with("batch", user_id="owner", offset=0, limit=1, include_result=True)


@pytest.mark.asyncio
async def test_paused_result_projection_does_not_block_other_requests(storage, monkeypatch):
    from deerflow.extensions import batch_results

    entered, release = threading.Event(), threading.Event()
    original = batch_results._evidence
    responsive = False

    def paused(value, report):
        nonlocal responsive
        entered.set()
        responsive = release.wait(5)  # Safety bound; progress is controlled by the loop below.
        return original(value, report)

    monkeypatch.setattr(batch_results, "_evidence", paused)
    pending = asyncio.create_task(storage.reader.read_item(thread_id="thread", batch_id="batch", position=0))
    try:
        assert await asyncio.to_thread(entered.wait, 10), "Projection never started"
        release.set()  # An unrelated request can advance while projection is paused.
        result = await pending
        assert result["evidence"]["sources"] == [source()]
        assert responsive, "Result projection blocked the event loop until its safety deadline"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_thread_denial_precedes_batch_metadata_and_payload(storage):
    storage.allowed.return_value = False
    assert await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0) is None
    assert await storage.reader.list_items(thread_id="thread", batch_id="batch") is None
    assert await storage.reader.list_batches(thread_id="thread") == []
    storage.repo.get_batch.assert_not_awaited()
    storage.repo.list_items.assert_not_awaited()
    storage.repo.list_by_thread.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [None, {"thread_id": "other-thread"}])
async def test_hidden_batch_and_wrong_thread_do_not_read_results(storage, batch):
    storage.repo.get_batch.return_value = batch
    assert await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0) is None
    storage.repo.list_items.assert_not_awaited()


@pytest.mark.asyncio
async def test_summary_pages_never_download_results_or_artifacts(storage):
    summaries = await storage.reader.list_batches(thread_id="thread")
    assert "execution_spec" not in summaries[0] and "user_id" not in summaries[0]
    rows = await storage.reader.list_items(thread_id="thread", batch_id="batch", offset=50, limit=50)
    assert "result" not in rows[0] and "result_artifact" not in rows[0]
    storage.repo.list_items.assert_awaited_once_with("batch", user_id="owner", offset=50, limit=50)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "queued", "leased", "running", "failed", "cancelled"])
async def test_unsuccessful_and_nonterminal_rows_never_publish_evidence(storage, status):
    storage.row["status"] = status
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert result["status"] == status and result["evidence"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact", [None, [], {}, {"knowledge_sources": {"version": 2, "sources": []}}, {"knowledge_sources": {"version": True, "sources": []}}, {"knowledge_sources": {"version": 1, "sources": [], "omitted_count": -1}}])
async def test_legacy_and_unsupported_evidence_remains_unavailable(storage, artifact):
    storage.row["result_artifact"] = artifact
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert result["result"] == storage.row["result"] and result["evidence"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [{"id": "malformed"}, {"provider": "other"}, {"dataset_id": ""}, {"document_name": "a" * 513}, {"pages": [True]}, {"pages": [-1]}, {"truncated": "false"}, {"text": None}])
async def test_invalid_source_records_are_not_exposed(storage, updates):
    storage.row["result_artifact"]["knowledge_sources"]["sources"] = [source(**updates)]
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert result["evidence"]["sources"] == []


@pytest.mark.asyncio
async def test_sources_are_report_bound_first_wins_and_private_fields_are_omitted(storage):
    original = source(secret="PRIVATE")
    storage.row["result_artifact"]["knowledge_sources"]["sources"] = [original, source(text="replacement"), source(id="b" * 32 + "-2")]
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert result["evidence"]["sources"] == [source()]


@pytest.mark.asyncio
async def test_revision_changes_when_completion_changes_same_attempt(storage):
    before = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    storage.row["acceptance_verdict"] = {"all_hold": True}
    after = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert before["attempt"] == after["attempt"]
    assert before["revision"] != after["revision"]
    storage.row["attempt"] += 1
    storage.row["result_artifact"] = None
    retried = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert retried["revision"] != after["revision"] and retried["evidence"] is None


@pytest.mark.asyncio
async def test_missing_position_never_returns_another_row(storage):
    storage.row["position"] = 1
    assert await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("position", [-1, 100_000, True, 0.0, "0"])
async def test_position_bounds_use_native_schema_ceiling(storage, position):
    with pytest.raises(ValueError):
        await storage.reader.read_item(thread_id="thread", batch_id="batch", position=position)
    storage.repo.get_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_ceiling_preserves_complete_excerpts_and_marks_truncation(storage):
    storage.row["result"] += "x" * 1_000_000
    result = await storage.reader.read_item(thread_id="thread", batch_id="batch", position=0)
    assert len(result["result"]) == 1_000_000 and result["result_truncated"] is True
    assert result["evidence"]["sources"][0]["text"] == source()["text"]


@pytest.mark.parametrize("permission,user", [(False, "owner"), (True, None)])
def test_gateway_request_binding_requires_stamped_user_and_permission(permission, user):
    app = create_app()
    request = SimpleNamespace(app=app, state=SimpleNamespace(user=SimpleNamespace(id=user, system_role="user") if user else None, auth=SimpleNamespace(has_permission=lambda resource, action: permission)))
    with pytest.raises(BatchResultError) as denied:
        require_batch_results(request)
    assert denied.value.status_code == 403


def test_worker_stopped_does_not_remove_repository_read_capability():
    app = create_app()
    app.state.subagent_batches_available = False
    app.state.subagent_batch_repo = object()
    app.state.thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    request = SimpleNamespace(app=app, state=SimpleNamespace(user=SimpleNamespace(id="owner", system_role="admin"), auth=SimpleNamespace(has_permission=lambda resource, action: True)))
    assert isinstance(require_batch_results(request), RepositoryBatchResultReader)


@pytest.mark.asyncio
async def test_metadata_dto_is_a_detached_copy(storage):
    storage.batch["counts"] = {"succeeded": 1}
    page = await storage.reader.list_batches(thread_id="thread")
    page[0]["counts"]["succeeded"] = 200
    assert storage.batch["counts"] == {"succeeded": 1}
