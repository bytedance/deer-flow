"""Unit tests for scripts/citations.py."""
import json
from pathlib import Path

import citations as ct


def test_build_citations_truncates_content():
    chunks = [
        {
            "id": "c1",
            "document_id": "d1",
            "document_keyword": "policy.pdf",
            "similarity": 0.91,
            "content": "A" * 1000,
            "meta_fields": {"部门": "零售金融部"},
        }
    ]
    items = ct.build_citations(chunks, max_content_chars=100, max_items=5)
    assert items[0]["ref"] == 1
    assert items[0]["document_name"] == "policy.pdf"
    assert len(items[0]["content"]) == 100
    assert items[0]["meta_fields"]["部门"] == "零售金融部"


def test_render_citations_markdown():
    md = ct.render_citations_markdown(
        [
            {
                "ref": 1,
                "document_name": "a.txt",
                "similarity": 0.8,
                "content": "hello",
                "chunk_id": "c1",
                "document_id": "d1",
                "meta_fields": {},
            }
        ],
        question="test?",
    )
    assert "## [1] a.txt" in md
    assert "hello" in md
    assert "test?" in md


def test_build_citations_search_api_chunk_shape():
    """Search (/datasets/search) returns docnm_kwd + content_with_weight, not SDK names."""
    chunks = [
        {
            "chunk_id": "c-search",
            "doc_id": "d-search",
            "docnm_kwd": "制度办法.pdf",
            "content_with_weight": "第三章 贷款审批流程应当遵循双人复核原则。",
            "similarity": 0.88,
            "meta_fields": {"department": "零售金融部"},
        }
    ]
    items = ct.build_citations(chunks)
    assert items[0]["document_name"] == "制度办法.pdf"
    assert items[0]["chunk_id"] == "c-search"
    assert items[0]["document_id"] == "d-search"
    assert "双人复核" in items[0]["content"]
    assert items[0]["snippet"] == items[0]["content"]


def test_build_citations_uses_highlight_when_content_missing():
    chunks = [
        {
            "id": "c1",
            "document_keyword": "policy.pdf",
            "similarity": 0.7,
            "highlight": "highlighted policy excerpt",
        }
    ]
    items = ct.build_citations(chunks)
    assert items[0]["content"] == "highlighted policy excerpt"


def test_citations_from_retrieval_file(tmp_path):
    payload = {
        "code": 0,
        "data": {
            "chunks": [
                {
                    "id": "c1",
                    "document_keyword": "doc.txt",
                    "content": "body",
                    "similarity": 0.5,
                }
            ]
        },
    }
    path = tmp_path / "retrieval.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    items = ct.citations_from_retrieval_file(path)
    assert len(items) == 1
    assert items[0]["document_name"] == "doc.txt"
