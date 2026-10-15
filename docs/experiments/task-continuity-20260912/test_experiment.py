import asyncio
import json

import numpy as np
import pytest

from common import PROTOCOL, ROOT, clip, tokens
from memory import reader_context
from prepare import history_batches, record_chunks
from retrieval import HistoryIndex, lexical_terms


def rec(rid, content, session="s1"):
    return {"id": rid, "content": content, "session_id": session, "date": "2026-01-01", "role": "tool"}


def test_public_gold_is_not_in_model_records():
    manifest = json.loads((ROOT / "public-manifest.json").read_text())
    dev = {r["id"] for r in manifest["dev"]}
    test = {r["id"] for r in manifest["test"]}
    assert not dev & test
    assert len(test) == 42
    for item in manifest["dev"] + manifest["test"]:
        case = json.loads((ROOT / "cases/public" / f"{item['id']}.json").read_text())
        assert "answer" not in case and "evidence_sessions" not in case
        assert all(set(r) == {"id", "content", "role", "session_id", "date"} for r in case["records"])


def test_chunking_preserves_long_tool_result_end_and_source():
    records = [rec("r00001", "prefix " * 1200 + "UNIQUE_END_MARKER")]
    chunks = record_chunks(records)
    assert len(chunks) > 1
    assert "UNIQUE_END_MARKER" in chunks[-1]["text"]
    assert all(c["record_id"] == "r00001" for c in chunks)
    assert all(tokens(c["text"]) <= PROTOCOL["archive_chunk_tokens"] for c in chunks)


def test_batches_do_not_discard_old_history():
    records = [rec(f"r{i:05d}", f"MARKER_{i} " + "word " * 100) for i in range(30)]
    batches = history_batches(records, 500)
    joined = "\n".join(batches)
    assert len(batches) > 1
    assert all(f"MARKER_{i}" in joined for i in range(30))


def test_keyword_search_handles_code_symbols_cjk_and_sql_syntax():
    records = [rec("r00001", "数据库连接池耗尽，改用 tenant_cursor_v7。"), rec("r00002", "tea gardening")]
    index = HistoryIndex(records, "test")
    assert index.keyword_ranks("连接池") == [0]
    assert index.keyword_ranks("tenant_cursor_v7") == [0]
    assert index.keyword_ranks('" OR * - drop table history;') == []
    index.close()


def test_search_scope_and_exact_read_do_not_fall_back_to_recent_history():
    index = HistoryIndex([rec("r00001", "alpha")], "scope-a")
    assert index.read("r00099") == {"error": "unknown_record_id"}
    assert index.keyword_ranks("foreign-secret") == []
    assert "alpha" in index.read("r00001-c0")["text"]
    index.close()


def test_token_budget_limits_packed_retrieval():
    index = HistoryIndex([rec(f"r{i:05d}", "alpha " * 300) for i in range(10)], "budget")
    hits = index.pack(list(range(len(index.chunks))), 1000)
    assert sum(tokens(h["rendered"]) + 2 for h in hits) <= 1000
    assert hits
    index.close()


def test_hybrid_can_recover_semantic_hit_without_lexical_overlap():
    index = HistoryIndex([rec("r00001", "connection pool exhausted"), rec("r00002", "unrelated tea")], "semantic")
    index.vectors = np.array([[1., 0.], [0., 1.]])
    class Fake:
        async def embed(self, *args, **kwargs):
            return np.array([[1., 0.]])
    result = asyncio.run(index.search("previous outage cause", "hybrid", Fake(), 500))
    assert result["hits"][0]["record_id"] == "r00001"
    index.close()


def test_reader_context_has_no_gold_and_keeps_same_summary():
    memory = {"summary": "SUMMARY_MARK", "notes": "NOTE_MARK", "recent_tail": "RECENT_MARK"}
    a = reader_context(memory, "A")
    b = reader_context(memory, "B")
    assert "SUMMARY_MARK" in a and "SUMMARY_MARK" in b
    assert "NOTE_MARK" not in a and "NOTE_MARK" in b
    assert "RECENT_MARK" in a and "RECENT_MARK" in b


def test_manifest_verifier_checks_exact_types_and_extra_fields():
    from task_eval import manifest_matches
    assert manifest_matches({"limit": 1, "enabled": False}, {"limit": 1, "enabled": False})
    assert not manifest_matches({"limit": True}, {"limit": 1})
    assert not manifest_matches({"limit": 1, "extra": 2}, {"limit": 1})


def test_task_prefix_contains_evidence_but_not_expected_manifest_metadata():
    from task_cases import case_for
    case, gold = case_for("artifact", 0)
    assert "expected_manifest" not in case
    assert all("expected" not in r for r in case["records"])
    assert any(gold["expected_manifest"]["sha256"] in r["content"] for r in case["records"])


def test_paired_statistics_handles_no_change_and_direction():
    from report import paired
    same = paired([True, False] * 5, [True, False] * 5)
    assert same["ci95_pp"] == [0.0, 0.0]
    assert same["mcnemar_exact_p"] == 1.0
    win = paired([False] * 8, [True] * 8)
    assert win["difference_pp"] == 100.0 and win["ci95_pp"] == [100.0, 100.0]
    assert win["mcnemar_exact_p"] == pytest.approx(0.0078125)


def test_official_qa_prompt_branches_include_gold_only_at_grading():
    from public_eval import official_grader
    make, sha = official_grader()
    assert len(sha) == 64
    prompt = make("abstention", "QUESTION", "GOLD_ONLY", "PREDICTION", abstention=True)
    assert "unanswerable" in prompt and "GOLD_ONLY" in prompt


@pytest.mark.parametrize("with_optional_keys", [False, True])
def test_artifact_audit_detects_optional_llm_key(tmp_path, monkeypatch, with_optional_keys):
    from types import SimpleNamespace
    import audit_results

    root = tmp_path / "artifacts"
    root.mkdir()
    for name in ("public-manifest.json", "task-manifest.json"):
        (root / name).write_text('{"test": []}')
    (root / "known-goal-manifest.json").write_text('[]')
    settings = {"llm_base": "https://synthetic-llm.invalid"}
    if with_optional_keys:
        settings.update(llm_key="synthetic-llm-key", embedding_base="https://synthetic-embedding.invalid", embedding_key="synthetic-embedding-key")
    else:
        settings.update(embedding_base="", embedding_key=None)
    endpoints = tmp_path / "endpoints.json"
    endpoints.write_text(json.dumps(settings))
    (root / "clean.txt").write_text("ordinary public content")
    expected = set()
    for key, value in settings.items():
        if value:
            filename = f"leaked-{key}.txt"
            (root / filename).write_text(value)
            expected.add(filename)
    monkeypatch.setattr(audit_results, "ROOT", root)
    audit_results.run(SimpleNamespace(full=False, endpoints=str(endpoints)))
    result = json.loads((root / "results/audit.json").read_text())
    assert {issue["file"] for issue in result["issues"]} == expected
