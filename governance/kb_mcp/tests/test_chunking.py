from governance_kb_mcp.chunking import chunk_document, DocumentChunk


def test_chunk_single_paragraph():
    text = "Hello world.\nThis is a test."
    chunks = chunk_document(text, "test.txt")
    assert len(chunks) == 1
    assert chunks[0].source_file == "test.txt"
    assert "Hello world" in chunks[0].content
    assert chunks[0].line_range == "1-2"


def test_chunk_multiple_paragraphs():
    text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
    chunks = chunk_document(text, "doc.md")
    assert len(chunks) == 3
    assert "Paragraph 1" in chunks[0].content
    assert "Paragraph 2" in chunks[1].content
    assert "Paragraph 3" in chunks[2].content
    assert chunks[0].line_range == "1-1"
    assert chunks[1].line_range == "3-3"
    assert chunks[2].line_range == "5-5"


def test_chunk_long_text_split():
    text = "A" * 500 + "\n\n" + "B" * 500
    chunks = chunk_document(text, "big.txt", max_chunk_size=300)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.content) <= 350  # some tolerance for boundary


def test_chunk_empty_text():
    chunks = chunk_document("", "empty.txt")
    assert len(chunks) == 0


def test_chunk_line_range_correct():
    text = "Line 1\nLine 2\nLine 3\n\nLine 5\nLine 6"
    chunks = chunk_document(text, "lines.txt")
    assert len(chunks) == 2
    assert chunks[0].line_range == "1-3"
    assert chunks[1].line_range == "5-6"
