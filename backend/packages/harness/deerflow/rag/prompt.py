"""Prompt formatting for RAG chunk injection."""

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
