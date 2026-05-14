"""MCP server providing RAGFlow knowledge base retrieval tools.

Run as a stdio MCP server:
    uv run python -m deerflow.mcp.ragflow_server

Required environment variables:
    RAGFLOW_BASE_URL - RAGFlow API base URL (e.g., http://localhost:9380)
    RAGFLOW_API_KEY  - RAGFlow API key (Bearer token)
"""

import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _load_config() -> tuple[str, str]:
    """Load RAGFlow configuration from environment variables."""
    base_url = os.environ.get("RAGFLOW_BASE_URL", "http://localhost:9380")
    api_key = os.environ.get("RAGFLOW_API_KEY", "")
    if not api_key:
        logger.warning("RAGFLOW_API_KEY environment variable is not set")
    base_url = base_url.rstrip("/")
    logger.info(
        "[RAGFlow MCP] Config loaded: base_url=%s, api_key=%s",
        base_url,
        f"{api_key[:20]}..." if api_key else "(empty)",
    )
    return base_url, api_key


def _make_client() -> httpx.Client:
    """Create an authenticated httpx client."""
    base_url, api_key = _load_config()
    headers = {"Authorization": f"Bearer {api_key}"}
    logger.info(
        "[RAGFlow MCP] Creating HTTP client: base_url=%s",
        base_url,
    )
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=30.0,
    )


mcp = FastMCP(
    name="ragflow",
    instructions="RAGFlow knowledge base retrieval tools. Use list_knowledge_bases to discover datasets and retrieve_knowledge to search for content.",
)


@mcp.tool()
def list_knowledge_bases() -> str:
    """List all available RAGFlow knowledge bases (datasets).

    Returns a formatted list of knowledge bases with their id, name,
    and description. Use this to discover available datasets before
    performing retrieval.
    """
    logger.info("[RAGFlow MCP] list_knowledge_bases: called")
    try:
        with _make_client() as client:
            url = "/api/v1/datasets"
            logger.info("[RAGFlow MCP] list_knowledge_bases: GET %s", url)
            resp = client.get(url)
            logger.info(
                "[RAGFlow MCP] list_knowledge_bases: status=%d, body_len=%d",
                resp.status_code,
                len(resp.text),
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("[RAGFlow MCP] list_knowledge_bases: response_code=%s", data.get("code"))

        if data.get("code") != 0:
            err_msg = f"Error from RAGFlow: {data.get('message', 'Unknown error')}"
            logger.error("[RAGFlow MCP] list_knowledge_bases: %s", err_msg)
            return err_msg

        datasets = data.get("data", [])
        if not datasets:
            logger.warning("[RAGFlow MCP] list_knowledge_bases: No knowledge bases found")
            return "No knowledge bases found. Please create one in RAGFlow first."

        lines = ["## Available Knowledge Bases\n"]
        for ds in datasets:
            name = ds.get("name", "Unnamed")
            ds_id = ds.get("id", "")
            desc = ds.get("description", "No description")
            doc_count = ds.get("document_count", ds.get("chunk_num", "?"))
            lines.append(
                f"- **{name}** "
                f"(id: `{ds_id}`) "
                f"(docs: {doc_count}) "
                f"- {desc}"
            )
        result = "\n".join(lines)
        logger.info("[RAGFlow MCP] list_knowledge_bases: Found %d datasets, returning %d chars", len(datasets), len(result))
        return result

    except httpx.ConnectError as e:
        err_msg = (
            "Error: Cannot connect to RAGFlow. "
            "Please ensure RAGFLOW_BASE_URL is correct and RAGFlow is running. "
            f"Details: {e}"
        )
        logger.error("[RAGFlow MCP] list_knowledge_bases: ConnectError: %s", e)
        return err_msg
    except httpx.HTTPStatusError as e:
        err_msg = f"HTTP Error {e.response.status_code}: {e.response.text[:500]}"
        logger.error("[RAGFlow MCP] list_knowledge_bases: HTTPStatusError: %s", err_msg)
        return err_msg
    except Exception as e:
        err_msg = f"Error listing knowledge bases: {type(e).__name__}: {e}"
        logger.error("[RAGFlow MCP] list_knowledge_bases: Unexpected error: %s", err_msg)
        return err_msg


@mcp.tool()
def retrieve_knowledge(
    query: str,
    dataset_ids: list[str],
    top_k: int = 5,
) -> str:
    """Retrieve relevant knowledge chunks from RAGFlow knowledge bases.

    Args:
        query: The search query / question to retrieve information for.
        dataset_ids: Required list of knowledge base IDs to search within.
            Use list_knowledge_bases first to discover available dataset IDs.
        top_k: Maximum number of chunks to return (default: 5, max: 20).

    Returns:
        Formatted retrieval results with content, source document, and
        relevance scores. Returns a structured error message if retrieval
        fails or no results are found.
    """
    logger.info(
        "[RAGFlow MCP] retrieve_knowledge: called query='%s', dataset_ids=%s, top_k=%d",
        query, dataset_ids, top_k,
    )

    if not query or not query.strip():
        logger.warning("[RAGFlow MCP] retrieve_knowledge: Empty query")
        return "Error: query must not be empty."

    query = query.strip()
    top_k = min(max(top_k, 1), 20)

    payload: dict = {
        "question": query,
        "top_k": top_k,
        "dataset_ids": dataset_ids,
    }
    logger.info("[RAGFlow MCP] retrieve_knowledge: payload=%s", payload)

    try:
        with _make_client() as client:
            url = "/api/v1/retrieval"
            logger.info("[RAGFlow MCP] retrieve_knowledge: POST %s", url)
            resp = client.post(url, json=payload)
            logger.info(
                "[RAGFlow MCP] retrieve_knowledge: status=%d, body_len=%d",
                resp.status_code,
                len(resp.text),
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("[RAGFlow MCP] retrieve_knowledge: response_code=%s", data.get("code"))

        if data.get("code") != 0:
            err_msg = f"Error from RAGFlow: {data.get('message', 'Unknown error')}"
            logger.error("[RAGFlow MCP] retrieve_knowledge: %s", err_msg)
            return err_msg

        chunks = data.get("data", {}).get("chunks", [])
        logger.info("[RAGFlow MCP] retrieve_knowledge: Found %d chunks", len(chunks))

        if not chunks:
            no_result_msg = (
                f"No results found for \"{query}\" in the specified knowledge base(s).\n\n"
                "Possible reasons:\n"
                "1. The knowledge base does not contain relevant content.\n"
                "2. Try rephrasing your query or using different keywords."
            )
            logger.warning("[RAGFlow MCP] retrieve_knowledge: %s", no_result_msg)
            return no_result_msg

        lines = [
            f"## Retrieval Results for: \"{query}\"\n",
            f"Found {len(chunks)} chunk(s):\n",
        ]
        for i, chunk in enumerate(chunks, 1):
            content = chunk.get("content", "No content").strip()
            doc_name = chunk.get("document_keyword", "Unknown document")
            similarity = chunk.get("similarity", 0)
            doc_id = chunk.get("document_id", "")
            logger.info(
                "[RAGFlow MCP] retrieve_knowledge: Chunk %d: doc='%s', similarity=%.4f, content_len=%d",
                i, doc_name, similarity, len(content),
            )
            lines.append(f"### Chunk {i}")
            lines.append(f"- **Source**: {doc_name}")
            if doc_id:
                lines.append(f"- **Doc ID**: {doc_id}")
            lines.append(f"- **Similarity**: {similarity:.4f}")
            lines.append(f"- **Content**:\n{content}\n")

        result = "\n".join(lines)
        logger.info("[RAGFlow MCP] retrieve_knowledge: Returning %d chars", len(result))
        return result

    except httpx.ConnectError as e:
        err_msg = (
            "Error: Cannot connect to RAGFlow. "
            "Please ensure RAGFLOW_BASE_URL is correct and RAGFlow is running. "
            f"Details: {e}"
        )
        logger.error("[RAGFlow MCP] retrieve_knowledge: ConnectError: %s", e)
        return err_msg
    except httpx.HTTPStatusError as e:
        err_msg = f"HTTP Error {e.response.status_code}: {e.response.text[:500]}"
        logger.error("[RAGFlow MCP] retrieve_knowledge: HTTPStatusError: %s", err_msg)
        return err_msg
    except Exception as e:
        err_msg = f"Error retrieving knowledge: {type(e).__name__}: {e}"
        logger.error("[RAGFlow MCP] retrieve_knowledge: Unexpected error: %s", err_msg)
        return err_msg


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=__import__("sys").stderr,
    )
    mcp.run(transport="stdio")
