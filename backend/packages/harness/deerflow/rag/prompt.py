"""Prompt formatting for RAG chunk injection."""

from __future__ import annotations

from xml.sax.saxutils import escape as xml_escape

from deerflow.rag.vector_store import SearchResult


def _count_tokens(text: str) -> int:
    """Estimate token count (4 chars ≈ 1 token)."""
    return len(text) // 4


def format_chunks_for_injection(
    chunks: list[SearchResult],
    max_tokens: int = 2000,
) -> str:
    """Format retrieved chunks for injection into the system prompt.

    Follows the same token-aware truncation pattern as
    :func:`deerflow.agents.memory.prompt.format_memory_for_injection`.

    Args:
        chunks: Retrieved search results to format.
        max_tokens: Maximum tokens for the formatted output.

    Returns:
        Formatted string wrapped in ``<knowledge_base>`` tags, or empty string.
    """
    if not chunks:
        return ""

    header = "<knowledge_base>\nThe following information may be relevant:\n\n"
    footer = "</knowledge_base>"
    header_tokens = _count_tokens(header)
    footer_tokens = _count_tokens(footer)
    running_tokens = header_tokens + footer_tokens

    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        source = chunk.metadata.get("source", "unknown")
        line = f"[{i + 1}] (source: {source}) {chunk.content}"
        line_tokens = _count_tokens("\n\n" + line) if lines else _count_tokens(line)

        if running_tokens + line_tokens <= max_tokens:
            lines.append(line)
            running_tokens += line_tokens
        else:
            break

    if not lines:
        return ""

    return header + "\n\n".join(lines) + "\n" + footer


def format_multi_kb_context(
    results: list[SearchResult],
    max_tokens: int = 4000,
) -> str:
    """Format multi-KB retrieval results into XML-structured context.

    Each result carries metadata with ``kb_name``, ``title``, ``knowledge_base_id``,
    and ``score`` so the LLM can attribute sources.

    Args:
        results: Merged search results from multiple knowledge bases.
        max_tokens: Maximum estimated tokens for the formatted output.

    Returns:
        XML-formatted string wrapped in ``<knowledge_base_context>`` tags, or empty string.
    """
    if not results:
        return ""

    header = "<knowledge_base_context>\n"
    footer = "</knowledge_base_context>"
    header_tokens = _count_tokens(header)
    footer_tokens = _count_tokens(footer)
    running_tokens = header_tokens + footer_tokens

    entries: list[str] = []
    for chunk in results:
        meta = chunk.metadata
        kb_id = xml_escape(meta.get("knowledge_base_id", ""))
        kb_name = xml_escape(meta.get("kb_name", ""))
        doc_title = xml_escape(meta.get("title", ""))
        score = f"{chunk.score:.2f}"
        content = xml_escape(chunk.content)

        entry = (
            f'  <source kb_id="{kb_id}" kb_name="{kb_name}" '
            f'doc_title="{doc_title}" score="{score}">\n'
            f"    {content}\n"
            f"  </source>"
        )
        entry_tokens = _count_tokens(entry + "\n")

        if running_tokens + entry_tokens > max_tokens:
            break

        entries.append(entry)
        running_tokens += entry_tokens

    if not entries:
        return ""

    return header + "\n".join(entries) + "\n" + footer
