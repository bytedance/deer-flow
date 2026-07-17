import logging

from mcp.server.fastmcp import FastMCP

from governance_kb_mcp.chunking import chunk_document
from governance_kb_mcp.config import KBConfig
from governance_kb_mcp.embedding import EmbeddingClient
from governance_kb_mcp.store import KBStore

logger = logging.getLogger(__name__)


def create_server(
    config: KBConfig | None = None,
    store: KBStore | None = None,
) -> FastMCP:
    if config is None:
        config = KBConfig.from_env()
    if store is None:
        embedding_client = EmbeddingClient(config)
        store = KBStore(config, embedding_client)

    mcp = FastMCP(
        name="kb-mcp",
        instructions=(
            "RAG knowledge base with three-layer access: company, position, personal. "
            "Use search_knowledge to find relevant documents, add_document to ingest, "
            "list_collections to see available layers."
        ),
        host=config.host,
        port=config.port,
    )

    @mcp.tool()
    def search_knowledge(
        query: str,
        level: str = "company",
        top_k: int = 5,
    ) -> list[dict]:
        """Search the knowledge base. level can be 'company', 'position:{role}', or 'personal:{user_id}'."""
        results = store.search(query, level=level, top_k=top_k)
        return [
            {
                "content": r.content,
                "source_file": r.source_file,
                "line_range": r.line_range,
                "level": r.level,
                "score": round(r.score, 4),
            }
            for r in results
        ]

    @mcp.tool()
    def add_document(
        content: str,
        source_file: str,
        level: str,
        metadata: dict = {},
    ) -> dict:
        """Add a document to the knowledge base. level: 'company', 'position:{role}', 'personal:{user_id}'."""
        chunks = chunk_document(content, source_file)
        if not chunks:
            return {"id": "", "status": "empty_content", "collection": level}
        ids = store.add_documents(chunks, level=level, metadata=metadata)
        return {"id": ids[0] if ids else "", "status": "ok", "collection": level}

    @mcp.tool()
    def list_collections() -> list[dict]:
        """List all knowledge base collections and their document counts."""
        collections = store.list_collections()
        return [
            {
                "level": c.level,
                "collection_name": c.collection_name,
                "document_count": c.document_count,
            }
            for c in collections
        ]

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)
    mcp = create_server()
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
