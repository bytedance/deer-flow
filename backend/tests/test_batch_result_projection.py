"""Native result projection preserves historical evidence and omits private storage."""

from types import SimpleNamespace

import pytest

from deerflow.subagents.batch_results import project_batch_result

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
    return SimpleNamespace(row=row)


def test_result_public_projection_excludes_secrets_and_detaches_snapshot(storage):
    result = project_batch_result(storage.row)
    assert result["result"] == storage.row["result"]
    assert result["evidence"]["sources"] == [source()]
    assert result["evidence"]["omitted_count"] == 2
    assert "PRIVATE" not in str(result)
    assert len(result["revision"]) == 64
    result["evidence"]["sources"][0]["pages"].append(999)
    result["acceptance_criteria"].append("mutated locally")
    assert storage.row["result_artifact"]["knowledge_sources"]["sources"][0]["pages"] == [1, 2]
    assert storage.row["acceptance_criteria"] == ["file_exists:report.md"]


@pytest.mark.parametrize("status", ["pending", "queued", "leased", "running", "failed", "cancelled"])
def test_unsuccessful_and_nonterminal_rows_never_publish_evidence(storage, status):
    storage.row["status"] = status
    result = project_batch_result(storage.row)
    assert result["status"] == status and result["evidence"] is None


@pytest.mark.parametrize("artifact", [None, [], {}, {"knowledge_sources": {"version": 2, "sources": []}}, {"knowledge_sources": {"version": True, "sources": []}}, {"knowledge_sources": {"version": 1, "sources": [], "omitted_count": -1}}])
def test_legacy_and_unsupported_evidence_remains_unavailable(storage, artifact):
    storage.row["result_artifact"] = artifact
    result = project_batch_result(storage.row)
    assert result["result"] == storage.row["result"] and result["evidence"] is None


@pytest.mark.parametrize("updates", [{"id": "malformed"}, {"provider": "other"}, {"dataset_id": ""}, {"document_name": "a" * 513}, {"pages": [True]}, {"pages": [-1]}, {"truncated": "false"}, {"text": None}])
def test_invalid_source_records_are_not_exposed(storage, updates):
    storage.row["result_artifact"]["knowledge_sources"]["sources"] = [source(**updates)]
    result = project_batch_result(storage.row)
    assert result["evidence"]["sources"] == []


def test_sources_are_report_bound_first_wins_and_private_fields_are_omitted(storage):
    original = source(secret="PRIVATE")
    storage.row["result_artifact"]["knowledge_sources"]["sources"] = [original, source(text="replacement"), source(id="b" * 32 + "-2")]
    result = project_batch_result(storage.row)
    assert result["evidence"]["sources"] == [source()]


def test_revision_changes_when_completion_changes_same_attempt(storage):
    before = project_batch_result(storage.row)
    storage.row["acceptance_verdict"] = {"all_hold": True}
    after = project_batch_result(storage.row)
    assert before["attempt"] == after["attempt"]
    assert before["revision"] != after["revision"]
    storage.row["attempt"] += 1
    storage.row["result_artifact"] = None
    retried = project_batch_result(storage.row)
    assert retried["revision"] != after["revision"] and retried["evidence"] is None


def test_report_ceiling_preserves_complete_excerpts_and_marks_truncation(storage):
    storage.row["result"] += "x" * 1_000_000
    result = project_batch_result(storage.row)
    assert len(result["result"]) == 1_000_000 and result["result_truncated"] is True
    assert result["evidence"]["sources"][0]["text"] == source()["text"]
