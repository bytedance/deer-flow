from deerflow.config.paths import resolve_path
from deerflow.vectorDB.base import VectorStore


async def make_vector_store(config) -> VectorStore | None:
    """Factory to initialize the requested vector backend."""

    if config.vector_store.backend == "none":
        return None
    if config.vector_store.backend == "chroma":
        from deerflow.vectorDB.db.chroma import ChromaVectorStore

        actual_path = resolve_path(config.vector_store.chroma.path)
        store = ChromaVectorStore(config=config, path=str(actual_path), collection_name=config.vector_store.chroma.collection_name)
        return store

    raise ValueError(f"Unsupported vector backend: {config.vector_store.backend}")
