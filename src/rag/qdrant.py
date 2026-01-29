# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from openai import OpenAI
from qdrant_client import QdrantClient, grpc
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.config.loader import get_bool_env, get_int_env, get_str_env
from src.rag.retriever import Chunk, Document, Resource, Retriever

logger = logging.getLogger(__name__)

SCROLL_SIZE = 64


class DashscopeEmbeddings:
    def __init__(self, **kwargs: Any) -> None:
        self._client: OpenAI = OpenAI(
            api_key=kwargs.get("api_key", ""), base_url=kwargs.get("base_url", "")
        )
        self._model: str = kwargs.get("model", "")
        self._encoding_format: str = kwargs.get("encoding_format", "float")

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        clean_texts = [t if isinstance(t, str) else str(t) for t in texts]
        if not clean_texts:
            return []
        resp = self._client.embeddings.create(
            model=self._model,
            input=clean_texts,
            encoding_format=self._encoding_format,
        )
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> List[float]:
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)


class QdrantProvider(Retriever):
    def __init__(self) -> None:
        self.location: str = get_str_env("QDRANT_LOCATION", ":memory:")
        self.api_key: str = get_str_env("QDRANT_API_KEY", "")
        self.collection_name: str = get_str_env("QDRANT_COLLECTION", "documents")

        top_k_raw = get_str_env("QDRANT_TOP_K", "10")
        self.top_k: int = int(top_k_raw) if top_k_raw.isdigit() else 10

        self.embedding_model_name = get_str_env("QDRANT_EMBEDDING_MODEL")
        self.embedding_api_key = get_str_env("QDRANT_EMBEDDING_API_KEY")
        self.embedding_base_url = get_str_env("QDRANT_EMBEDDING_BASE_URL")
        self.embedding_dim: int = self._get_embedding_dimension(
            self.embedding_model_name
        )
        self.embedding_provider = get_str_env("QDRANT_EMBEDDING_PROVIDER", "openai")

        self.auto_load_examples: bool = get_bool_env("QDRANT_AUTO_LOAD_EXAMPLES", True)
        self.examples_dir: str = get_str_env("QDRANT_EXAMPLES_DIR", "examples")
        self.chunk_size: int = get_int_env("QDRANT_CHUNK_SIZE", 4000)

        self._init_embedding_model()

        self.client: Any = None
        self.vector_store: Any = None

    def _init_embedding_model(self) -> None:
        kwargs = {
            "api_key": self.embedding_api_key,
            "model": self.embedding_model_name,
            "base_url": self.embedding_base_url,
            "encoding_format": "float",
            "dimensions": self.embedding_dim,
        }
        if self.embedding_provider.lower() == "openai":
            self.embedding_model = OpenAIEmbeddings(**kwargs)
        elif self.embedding_provider.lower() == "dashscope":
            self.embedding_model = DashscopeEmbeddings(**kwargs)
        else:
            raise ValueError(
                f"Unsupported embedding provider: {self.embedding_provider}. "
                "Supported providers: openai, dashscope"
            )

    def _get_embedding_dimension(self, model_name: str) -> int:
        embedding_dims = {
            "text-embedding-ada-002": 1536,
            "text-embedding-v4": 2048,
        }

        explicit_dim = get_int_env("QDRANT_EMBEDDING_DIM", 0)
        if explicit_dim > 0:
            return explicit_dim
        return embedding_dims.get(model_name, 1536)

    def _ensure_collection_exists(self) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim, distance=Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection: %s", self.collection_name)

    def _load_example_files(self) -> None:
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        examples_path = project_root / self.examples_dir

        if not examples_path.exists():
            logger.info("Examples directory not found: %s", examples_path)
            return

        logger.info("Loading example files from: %s", examples_path)

        md_files = list(examples_path.glob("*.md"))
        if not md_files:
            logger.info("No markdown files found in examples directory")
            return

        existing_docs = self._get_existing_document_ids()
        loaded_count = 0
        for md_file in md_files:
            doc_id = self._generate_doc_id(md_file)

            if doc_id in existing_docs:
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                title = self._extract_title_from_markdown(content, md_file.name)

                chunks = self._split_content(content)

                for i, chunk in enumerate(chunks):
                    chunk_id = f"{doc_id}_chunk_{i}" if len(chunks) > 1 else doc_id
                    self._insert_document_chunk(
                        doc_id=chunk_id,
                        content=chunk,
                        title=title,
                        url=f"qdrant://{self.collection_name}/{md_file.name}",
                        metadata={"source": "examples", "file": md_file.name},
                    )

                loaded_count += 1
                logger.debug("Loaded example markdown: %s", md_file.name)

            except Exception as e:
                logger.warning("Error loading %s: %s", md_file.name, e)

        logger.info("Successfully loaded %d example files into Qdrant", loaded_count)

    def _generate_doc_id(self, file_path: Path) -> str:
        file_stat = file_path.stat()
        content_hash = hashlib.md5(
            f"{file_path.name}_{file_stat.st_size}_{file_stat.st_mtime}".encode()
        ).hexdigest()[:8]
        return f"example_{file_path.stem}_{content_hash}"

    def _extract_title_from_markdown(self, content: str, filename: str) -> str:
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()

        return filename.replace(".md", "").replace("_", " ").title()

    def _split_content(self, content: str) -> List[str]:
        if len(content) <= self.chunk_size:
            return [content]

        chunks = []
        paragraphs = content.split("\n\n")
        current_chunk = ""

        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) <= self.chunk_size:
                current_chunk += paragraph + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph + "\n\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _string_to_uuid(self, text: str) -> str:
        namespace = uuid.NAMESPACE_DNS
        return str(uuid.uuid5(namespace, text))

    def _scroll_all_points(
        self,
        scroll_filter: Optional[Filter] = None,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> List[Any]:
        results = []
        next_offset = None
        stop_scrolling = False

        while not stop_scrolling:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=SCROLL_SIZE,
                offset=next_offset,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
            stop_scrolling = next_offset is None or (
                isinstance(next_offset, grpc.PointId)
                and getattr(next_offset, "num", 0) == 0
                and getattr(next_offset, "uuid", "") == ""
            )
            results.extend(points)

        return results

    def _get_existing_document_ids(self) -> Set[str]:
        try:
            points = self._scroll_all_points(with_payload=True, with_vectors=False)
            return {
                point.payload.get("doc_id", str(point.id))
                for point in points
                if point.payload
            }
        except Exception:
            return set()

    def _insert_document_chunk(
        self, doc_id: str, content: str, title: str, url: str, metadata: Dict[str, Any]
    ) -> None:
        embedding = self._get_embedding(content)

        payload = {
            "doc_id": doc_id,
            "content": content,
            "title": title,
            "url": url,
            **metadata,
        }

        point_id = self._string_to_uuid(doc_id)
        point = PointStruct(id=point_id, vector=embedding, payload=payload)

        self.client.upsert(
            collection_name=self.collection_name, points=[point], wait=True
        )

    def _connect(self) -> None:
        client_kwargs = {"location": self.location}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        self.client = QdrantClient(**client_kwargs)

        self._ensure_collection_exists()

        try:
            self.vector_store = QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embedding_model,
            )
        except Exception:
            self.vector_store = None

    def _get_embedding(self, text: str) -> List[float]:
        return self.embedding_model.embed_query(text=text.strip())

    def list_resources(self, query: Optional[str] = None) -> List[Resource]:
        resources: List[Resource] = []

        if not self.client:
            try:
                self._connect()
            except Exception:
                return self._list_local_markdown_resources()

        try:
            if query and self.vector_store:
                docs = self.vector_store.similarity_search(
                    query, k=100, filter={"source": "examples"}
                )
                for d in docs:
                    meta = d.metadata or {}
                    uri = meta.get("url", "") or f"qdrant://{meta.get('id', '')}"
                    if any(r.uri == uri for r in resources):
                        continue
                    resources.append(
                        Resource(
                            uri=uri,
                            title=meta.get("title", "") or meta.get("id", "Unnamed"),
                            description="Stored Qdrant document",
                        )
                    )
            else:
                all_points = self._scroll_all_points(
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="source", match=MatchValue(value="examples")
                            )
                        ]
                    ),
                    with_payload=True,
                    with_vectors=False,
                )

                for point in all_points:
                    payload = point.payload or {}
                    doc_id = payload.get("doc_id", str(point.id))
                    uri = payload.get("url", "") or f"qdrant://{doc_id}"
                    resources.append(
                        Resource(
                            uri=uri,
                            title=payload.get("title", "") or doc_id,
                            description="Stored Qdrant document",
                        )
                    )

            logger.info(
                "Successfully listed %d resources from Qdrant collection: %s",
                len(resources),
                self.collection_name,
            )
        except Exception:
            logger.warning(
                "Failed to query Qdrant for resources, falling back to local examples."
            )
            return self._list_local_markdown_resources()
        return resources

    async def list_resources_async(self, query: Optional[str] = None) -> List[Resource]:
        """
        Asynchronous version of list_resources.
        Wraps the synchronous implementation in asyncio.to_thread() to avoid blocking the event loop.
        """
        return await asyncio.to_thread(self.list_resources, query)

    def _list_local_markdown_resources(self) -> List[Resource]:
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        examples_path = project_root / self.examples_dir
        if not examples_path.exists():
            return []

        md_files = list(examples_path.glob("*.md"))
        resources: list[Resource] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                title = self._extract_title_from_markdown(content, md_file.name)
                uri = f"qdrant://{self.collection_name}/{md_file.name}"
                resources.append(
                    Resource(
                        uri=uri,
                        title=title,
                        description="Local markdown example (not yet ingested)",
                    )
                )
            except Exception:
                continue
        return resources

    def query_relevant_documents(
        self, query: str, resources: Optional[List[Resource]] = None
    ) -> List[Document]:
        resources = resources or []
        if not self.client:
            self._connect()

        query_embedding = self._get_embedding(query)

        search_results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=self.top_k,
            with_payload=True,
        ).points

        documents = {}

        for result in search_results:
            payload = result.payload or {}
            doc_id = payload.get("doc_id", str(result.id))
            content = payload.get("content", "")
            title = payload.get("title", "")
            url = payload.get("url", "")
            score = result.score

            if resources:
                doc_in_resources = False
                for resource in resources:
                    if (url and url in resource.uri) or doc_id in resource.uri:
                        doc_in_resources = True
                        break
                if not doc_in_resources:
                    continue

            if doc_id not in documents:
                documents[doc_id] = Document(id=doc_id, url=url, title=title, chunks=[])

            chunk = Chunk(content=content, similarity=score)
            documents[doc_id].chunks.append(chunk)

        return list(documents.values())

    async def query_relevant_documents_async(
        self, query: str, resources: Optional[List[Resource]] = None
    ) -> List[Document]:
        """
        Asynchronous version of query_relevant_documents.
        Wraps the synchronous implementation in asyncio.to_thread() to avoid blocking the event loop.
        """
        return await asyncio.to_thread(
            self.query_relevant_documents, query, resources
        )

    def create_collection(self) -> None:
        if not self.client:
            self._connect()
        else:
            self._ensure_collection_exists()

    def load_examples(self, force_reload: bool = False) -> None:
        if not self.client:
            self._connect()

        if force_reload:
            self._clear_example_documents()

        self._load_example_files()

    def _clear_example_documents(self) -> None:
        try:
            all_points = self._scroll_all_points(
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="source", match=MatchValue(value="examples"))
                    ]
                ),
                with_payload=False,
                with_vectors=False,
            )

            if all_points:
                point_ids = [str(point.id) for point in all_points]
                self.client.delete(
                    collection_name=self.collection_name, points_selector=point_ids
                )
                logger.info("Cleared %d existing example documents", len(point_ids))

        except Exception as e:
            logger.warning("Could not clear existing examples: %s", e)

    def get_loaded_examples(self) -> List[Dict[str, str]]:
        if not self.client:
            self._connect()

        all_points = self._scroll_all_points(
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value="examples"))]
            ),
            with_payload=True,
            with_vectors=False,
        )

        examples = []
        for point in all_points:
            payload = point.payload or {}
            examples.append(
                {
                    "id": payload.get("doc_id", str(point.id)),
                    "title": payload.get("title", ""),
                    "file": payload.get("file", ""),
                    "url": payload.get("url", ""),
                }
            )

        return examples

    def close(self) -> None:
        if hasattr(self, "client") and self.client:
            try:
                if hasattr(self.client, "close"):
                    self.client.close()
                self.client = None
                self.vector_store = None
            except Exception as e:
                logger.warning("Exception occurred while closing QdrantProvider: %s", e)

    def __del__(self) -> None:
        self.close()


def load_examples() -> None:
    auto_load_examples = get_bool_env("QDRANT_AUTO_LOAD_EXAMPLES", False)
    rag_provider = get_str_env("RAG_PROVIDER", "")
    if rag_provider == "qdrant" and auto_load_examples:
        provider = QdrantProvider()
        provider.load_examples()
