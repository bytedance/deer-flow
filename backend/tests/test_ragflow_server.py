"""Unit tests for RAGFlow MCP result formatting."""

import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "packages/harness/deerflow/mcp/ragflow_server.py"
_SPEC = importlib.util.spec_from_file_location("ragflow_server_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_RAGFLOW_SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RAGFLOW_SERVER)
_format_retrieval_results = _RAGFLOW_SERVER._format_retrieval_results


def _chunk(content: str, *, doc_name: str = "doc.pdf", similarity: float = 0.9, doc_id: str = "doc-1") -> dict:
    return {
        "content": content,
        "document_keyword": doc_name,
        "document_id": doc_id,
        "similarity": similarity,
    }


def test_formats_crop_image_before_page_image():
    content = (
        "人员跌倒检测系统界面如图5-1所示。\n\n"
        "[SOURCE doc_id=source-doc page=29 chunk_id=p0029_c0066 "
        "page_image=http://localhost:8018/page.png block_type=text "
        "crop_image=http://localhost:8018/crop.png]"
    )

    result = _format_retrieval_results("跌倒检测界面", [_chunk(content)], top_k=5)

    assert "- **Page**: 29" in result
    assert "- **Chunk ID**: p0029_c0066" in result
    assert "- **Block Type**: text" in result
    assert "![doc.pdf - page 29 - p0029_c0066 - chunk 1](http://localhost:8018/crop.png)" in result
    assert "![doc.pdf - page 29 - p0029_c0066 - chunk 1](http://localhost:8018/page.png)" not in result


def test_formats_page_image_when_crop_missing():
    content = "content\n[SOURCE doc_id=source-doc page=3 page_image=http://localhost:8018/page.png]"

    result = _format_retrieval_results("query", [_chunk(content)], top_k=5)

    assert "- **Image (page_image)**:" in result
    assert "![doc.pdf - page 3 - chunk 1](http://localhost:8018/page.png)" in result


def test_formats_image_when_crop_and_page_missing():
    content = "content\n[SOURCE doc_id=source-doc page=4 image=http://localhost:8018/image.png]"

    result = _format_retrieval_results("query", [_chunk(content)], top_k=5)

    assert "- **Image (image)**:" in result
    assert "![doc.pdf - page 4 - chunk 1](http://localhost:8018/image.png)" in result


def test_deduplicates_repeated_image_urls():
    source = "[SOURCE doc_id=source-doc page=1 crop_image=http://localhost:8018/shared.png]"
    chunks = [
        _chunk(f"first\n{source}", doc_name="first.pdf"),
        _chunk(f"second\n{source}", doc_name="second.pdf"),
    ]

    result = _format_retrieval_results("query", chunks, top_k=5)

    assert result.count("http://localhost:8018/shared.png") == 1


def test_limits_formatted_chunks_to_top_k():
    chunks = [_chunk(f"content {i}", doc_name=f"doc-{i}.pdf") for i in range(1, 31)]

    result = _format_retrieval_results("query", chunks, top_k=3)

    assert "Found 3 chunk(s):" in result
    assert "### Chunk 3" in result
    assert "### Chunk 4" not in result
    assert "doc-4.pdf" not in result
