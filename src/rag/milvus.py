# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from langchain_milvus.vectorstores import Milvus as LangchainMilvus
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

from src.config.loader import get_bool_env, get_int_env, get_str_env
from src.rag.retriever import Chunk, Document, Resource, Retriever

logger = logging.getLogger(__name__)


class DashscopeEmbeddings:
    """OpenAI-compatible embeddings wrapper."""

    def __init__(self, **kwargs: Any) -> None:
        self._client: OpenAI = OpenAI(
            api_key=kwargs.get("api_key", ""), base_url=kwargs.get("base_url", "")
        )
        self._model: str = kwargs.get("model", "")
        self._encoding_format: str = kwargs.get("encoding_format", "float")

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Internal helper performing the embedding API call."""
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
        """Return embedding for a given text."""
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings for multiple documents (LangChain interface)."""
        return self._embed(texts)


class MilvusRetriever(Retriever):
    """Retriever implementation backed by a Milvus vector store.
    Responsibilities:
        * Initialize / lazily connect to Milvus (local Lite or remote server).
        * Provide methods for inserting content chunks & querying similarity.
        * Optionally surface example markdown resources found in the project.
    Environment variables (selected):
        MILVUS_URI: Connection URI or local *.db path for Milvus Lite.
        MILVUS_COLLECTION: Target collection name (default: documents).
        MILVUS_TOP_K: Result set size (default: 10).
        MILVUS_EMBEDDING_PROVIDER: openai | dashscope (default: openai).
        MILVUS_EMBEDDING_MODEL: Embedding model name.
        MILVUS_EMBEDDING_DIM: Override embedding dimensionality.
        MILVUS_AUTO_LOAD_EXAMPLES: Load example *.md files if true.
        MILVUS_EXAMPLES_DIR: Folder containing example markdown files.
    """

    def __init__(self) -> None:
        # --- Connection / collection configuration ---
        self.uri: str = get_str_env("MILVUS_URI", "http://localhost:19530")
        self.user: str = get_str_env("MILVUS_USER")
        self.password: str = get_str_env("MILVUS_PASSWORD")
        self.collection_name: str = get_str_env("MILVUS_COLLECTION", "documents")

        # --- Search configuration ---
        top_k_raw = get_str_env("MILVUS_TOP_K", "10")
        self.top_k: int = int(top_k_raw) if top_k_raw.isdigit() else 10

        # --- Vector field names ---
        self.vector_field: str = get_str_env("MILVUS_VECTOR_FIELD", "embedding")
        self.id_field: str = get_str_env("MILVUS_ID_FIELD", "id")
        self.content_field: str = get_str_env("MILVUS_CONTENT_FIELD", "content")
        self.title_field: str = get_str_env("MILVUS_TITLE_FIELD", "title")
        self.url_field: str = get_str_env("MILVUS_URL_FIELD", "url")
        self.metadata_field: str = get_str_env("MILVUS_METADATA_FIELD", "metadata")

        # --- Embedding configuration ---
        self.embedding_model = get_str_env("MILVUS_EMBEDDING_MODEL")
        self.embedding_api_key = get_str_env("MILVUS_EMBEDDING_API_KEY")
        self.embedding_base_url = get_str_env("MILVUS_EMBEDDING_BASE_URL")
        self.embedding_dim: int = self._get_embedding_dimension(self.embedding_model)
        self.embedding_provider = get_str_env("MILVUS_EMBEDDING_PROVIDER", "openai")

        # --- Examples / auto-load configuration ---
        self.auto_load_examples: bool = get_bool_env("MILVUS_AUTO_LOAD_EXAMPLES", True)
        self.examples_dir: str = get_str_env("MILVUS_EXAMPLES_DIR", "examples")
        # chunk size
        self.chunk_size: int = get_int_env("MILVUS_CHUNK_SIZE", 4000)

        # --- Embedding model initialization ---
        self._init_embedding_model()

        # Client (MilvusClient or LangchainMilvus) created lazily
        self.client: Any = None

    def _init_embedding_model(self) -> None:
        """Initialize the embedding model based on configuration."""
        kwargs = {
            "api_key": self.embedding_api_key,
            "model": self.embedding_model,
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
        """Return embedding dimension for the supplied model name."""
        # Common OpenAI embedding model dimensions
        embedding_dims = {
            "text-embedding-ada-002": 1536,
            "text-embedding-v4": 2048,
        }

        # Check if user has explicitly set the dimension
        explicit_dim = get_int_env("MILVUS_EMBEDDING_DIM", 0)
        if explicit_dim > 0:
            return explicit_dim
        # Return the dimension for the specified model
        return embedding_dims.get(model_name, 1536)  # Default to 1536

    def _create_collection_schema(self) -> CollectionSchema:
        """Build and return a Milvus ``CollectionSchema`` object with metadata field.
        Attempts to use a JSON field for metadata; falls back to VARCHAR if JSON
        type isn't supported in the deployment.
        """
        fields = [
            FieldSchema(
                name=self.id_field,
                dtype=DataType.VARCHAR,
                max_length=512,
                is_primary=True,
                auto_id=False,
            ),
            FieldSchema(
                name=self.vector_field,
                dtype=DataType.FLOAT_VECTOR,
                dim=self.embedding_dim,
            ),
            FieldSchema(
                name=self.content_field, dtype=DataType.VARCHAR, max_length=65535
            ),
            FieldSchema(name=self.title_field, dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name=self.url_field, dtype=DataType.VARCHAR, max_length=1024),
        ]

        schema = CollectionSchema(
            fields=fields,
            description=f"Collection for DeerFlow RAG documents: {self.collection_name}",
            enable_dynamic_field=True,  # Allow additional dynamic metadata fields
        )
        return schema

    def _ensure_collection_exists(self) -> None:
        """Ensure the configured collection exists (create if missing).
        For Milvus Lite we create the collection manually; for the remote
        (LangChain) client we rely on LangChain's internal logic.
        """
        if self._is_milvus_lite():
            # For Milvus Lite, use MilvusClient
            try:
                # Check if collection exists
                collections = self.client.list_collections()
                if self.collection_name not in collections:
                    # Create collection
                    schema = self._create_collection_schema()
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        schema=schema,
                        index_params={
                            "field_name": self.vector_field,
                            "index_type": "IVF_FLAT",
                            "metric_type": "IP",
                            "params": {"nlist": 1024},
                        },
                    )
                    logger.info("Created Milvus collection: %s", self.collection_name)

            except Exception as e:
                logger.warning("Could not ensure collection exists: %s", e)
        else:
            # For LangChain Milvus, collection creation is handled automatically
            logger.warning(
                "Could not ensure collection exists: %s", self.collection_name
            )

    def _load_example_files(self) -> None:
        """Load example markdown files into the collection (idempotent).
        Each markdown file is split into chunks and inserted only if a chunk
        with the derived document id hasn't been previously stored.
        """
        try:
            # Get the project root directory
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # Go up to project root
            examples_path = project_root / self.examples_dir

            if not examples_path.exists():
                logger.info("Examples directory not found: %s", examples_path)
                return

            logger.info("Loading example files from: %s", examples_path)

            # Find all markdown files
            md_files = list(examples_path.glob("*.md"))
            if not md_files:
                logger.info("No markdown files found in examples directory")
                return
            # Check if files are already loaded
            existing_docs = self._get_existing_document_ids()
            loaded_count = 0
            for md_file in md_files:
                doc_id = self._generate_doc_id(md_file)

                # Skip if already loaded
                if doc_id in existing_docs:
                    continue
                try:
                    # Read and process the file
                    content = md_file.read_text(encoding="utf-8")
                    title = self._extract_title_from_markdown(content, md_file.name)

                    # Split content into chunks if it's too long
                    chunks = self._split_content(content)

                    # Insert each chunk
                    for i, chunk in enumerate(chunks):
                        chunk_id = f"{doc_id}_chunk_{i}" if len(chunks) > 1 else doc_id
                        self._insert_document_chunk(
                            doc_id=chunk_id,
                            content=chunk,
                            title=title,
                            url=f"milvus://{self.collection_name}/{md_file.name}",
                            metadata={"source": "examples", "file": md_file.name},
                        )

                    loaded_count += 1
                    logger.debug("Loaded example markdown: %s", md_file.name)

                except Exception as e:
                    logger.warning("Error loading %s: %s", md_file.name, e)

            logger.info(
                "Successfully loaded %d example files into Milvus", loaded_count
            )

        except Exception as e:
            logger.error("Error loading example files: %s", e)

    def _generate_doc_id(self, file_path: Path) -> str:
        """Return a stable identifier derived from name, size & mtime hash."""
        # Use file name and size for a simple but effective ID
        file_stat = file_path.stat()
        content_hash = hashlib.md5(
            f"{file_path.name}_{file_stat.st_size}_{file_stat.st_mtime}".encode()
        ).hexdigest()[:8]
        return f"example_{file_path.stem}_{content_hash}"

    def _extract_title_from_markdown(self, content: str, filename: str) -> str:
        """Extract the first level-1 heading; else derive from file name."""
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()

        # Fallback to filename without extension
        return filename.replace(".md", "").replace("_", " ").title()

    def _split_content(self, content: str) -> List[str]:
        """Split long markdown text into paragraph-based chunks."""
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

    def _get_existing_document_ids(self) -> Set[str]:
        """Return set of existing document identifiers in the collection."""
        try:
            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="",
                    output_fields=[self.id_field],
                    limit=10000,
                )
                return {
                    result.get(self.id_field, "")
                    for result in results
                    if result.get(self.id_field)
                }
            else:
                # For LangChain Milvus, we can't easily query all IDs
                # Return empty set to allow re-insertion (LangChain will handle duplicates)
                return set()
        except Exception:
            return set()

    def _insert_document_chunk(
        self, doc_id: str, content: str, title: str, url: str, metadata: Dict[str, Any]
    ) -> None:
        """Insert a single content chunk into Milvus."""
        try:
            # Generate embedding
            embedding = self._get_embedding(content)

            if self._is_milvus_lite():
                # For Milvus Lite, use MilvusClient
                data = [
                    {
                        self.id_field: doc_id,
                        self.vector_field: embedding,
                        self.content_field: content,
                        self.title_field: title,
                        self.url_field: url,
                        **metadata,  # Add metadata fields
                    }
                ]
                self.client.insert(collection_name=self.collection_name, data=data)
            else:
                # For LangChain Milvus, use add_texts
                self.client.add_texts(
                    texts=[content],
                    metadatas=[
                        {
                            self.id_field: doc_id,
                            self.title_field: title,
                            self.url_field: url,
                            **metadata,
                        }
                    ],
                )
        except Exception as e:
            raise RuntimeError(f"Failed to insert document chunk: {str(e)}")

    def _connect(self) -> None:
        """Create the underlying Milvus client (idempotent)."""
        try:
            # Check if using Milvus Lite (file-based) vs server-based Milvus
            if self._is_milvus_lite():
                # Use MilvusClient for Milvus Lite (local file database)
                self.client = MilvusClient(self.uri)
                # Ensure collection exists
                self._ensure_collection_exists()
            else:
                connection_args = {
                    "uri": self.uri,
                }
                # Add user/password only if provided
                if self.user:
                    connection_args["user"] = self.user
                if self.password:
                    connection_args["password"] = self.password

                # Create LangChain client (it will handle collection creation automatically)
                self.client = LangchainMilvus(
                    embedding_function=self.embedding_model,
                    collection_name=self.collection_name,
                    connection_args=connection_args,
                    # optional (if collection already exists with different schema, be careful)
                    drop_old=False,
                )
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Milvus: {str(e)}")

    def _is_milvus_lite(self) -> bool:
        """Return True if the URI points to a local Milvus Lite file.
        Milvus Lite uses local file paths (often ``*.db``) without an HTTP/HTTPS
        scheme. We treat any path not containing a protocol and not starting
        with an HTTP(S) prefix as a Lite instance.
        """
        return self.uri.endswith(".db") or (
            not self.uri.startswith(("http://", "https://")) and "://" not in self.uri
        )

    def _get_embedding(self, text: str) -> List[float]:
        """Return embedding for a given text."""
        try:
            # Validate input
            if not isinstance(text, str):
                raise ValueError(f"Text must be a string, got {type(text)}")

            if not text.strip():
                raise ValueError("Text cannot be empty or only whitespace")
            # Unified embedding interface (OpenAIEmbeddings or DashscopeEmbeddings wrapper)
            embeddings = self.embedding_model.embed_query(text=text.strip())

            # Validate output
            if not isinstance(embeddings, list) or not embeddings:
                raise ValueError(f"Invalid embedding format: {type(embeddings)}")

            return embeddings
        except Exception as e:
            raise RuntimeError(f"Failed to generate embedding: {str(e)}")

    def list_resources(self, query: Optional[str] = None) -> List[Resource]:
        """List available resource summaries.

        Strategy:
            1. If connected to Milvus Lite: query stored document metadata.
            2. If LangChain client: perform a lightweight similarity search
               using either the provided ``query`` or a zero vector to fetch
               candidate docs (mocked in tests).
            3. Append local markdown example titles (non-ingested) for user
               discoverability.

        Args:
            query: Optional search text to bias resource ordering.

        Returns:
            List of ``Resource`` objects.
        """
        resources: List[Resource] = []

        # Ensure connection established
        if not self.client:
            try:
                self._connect()
            except Exception:
                # Fall back to only local examples if connection fails
                return self._list_local_markdown_resources()

        try:
            if self._is_milvus_lite():
                # Query limited metadata. Empty filter returns up to limit docs.
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="source == 'examples'",
                    output_fields=[self.id_field, self.title_field, self.url_field],
                    limit=100,
                )
                for r in results:
                    resources.append(
                        Resource(
                            uri=r.get(self.url_field, "")
                            or f"milvus://{r.get(self.id_field, '')}",
                            title=r.get(self.title_field, "")
                            or r.get(self.id_field, "Unnamed"),
                            description="Stored Milvus document",
                        )
                    )
            else:
                # Use similarity_search_by_vector for lightweight listing.
                # If a query is provided embed it; else use a zero vector.
                docs: Iterable[Any] = self.client.similarity_search(
                    query,
                    k=100,
                    expr="source == 'examples'",  # Limit to 100 results
                )
                for d in docs:
                    meta = getattr(d, "metadata", {}) or {}
                    # check if the resource is in the list of resources
                    if resources and any(
                        r.uri == meta.get(self.url_field, "")
                        or r.uri == f"milvus://{meta.get(self.id_field, '')}"
                        for r in resources
                    ):
                        continue
                    resources.append(
                        Resource(
                            uri=meta.get(self.url_field, "")
                            or f"milvus://{meta.get(self.id_field, '')}",
                            title=meta.get(self.title_field, "")
                            or meta.get(self.id_field, "Unnamed"),
                            description="Stored Milvus document",
                        )
                    )
                logger.info(
                    "Succeed listed %d resources from Milvus collection: %s",
                    len(resources),
                    self.collection_name,
                )
        except Exception:
            logger.warning(
                "Failed to query Milvus for resources, falling back to local examples."
            )
            # Fall back to only local examples if connection fails
            return self._list_local_markdown_resources()
        return resources

    def _list_local_markdown_resources(self) -> List[Resource]:
        """Return local example markdown files as ``Resource`` objects.

        These are surfaced even when not ingested so users can choose to load
        them. Controlled by directory presence only (lightweight)."""
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # up to project root
        examples_path = project_root / self.examples_dir
        if not examples_path.exists():
            return []

        md_files = list(examples_path.glob("*.md"))
        resources: list[Resource] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                title = self._extract_title_from_markdown(content, md_file.name)
                uri = f"milvus://{self.collection_name}/{md_file.name}"
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
        """Perform vector similarity search returning rich ``Document`` objects.

        Args:
            query: Natural language query string.
            resources: Optional subset filter of ``Resource`` objects; if
                provided, only documents whose id/url appear in the list will
                be included.

        Returns:
            List of aggregated ``Document`` objects; each contains one or more
            ``Chunk`` instances (one per matched piece of content).

        Raises:
            RuntimeError: On underlying search errors.
        """
        resources = resources or []
        try:
            if not self.client:
                self._connect()

            # Get embeddings for the query
            query_embedding = self._get_embedding(query)

            # For Milvus Lite, use MilvusClient directly
            if self._is_milvus_lite():
                # Perform vector search
                search_results = self.client.search(
                    collection_name=self.collection_name,
                    data=[query_embedding],
                    anns_field=self.vector_field,
                    param={"metric_type": "IP", "params": {"nprobe": 10}},
                    limit=self.top_k,
                    output_fields=[
                        self.id_field,
                        self.content_field,
                        self.title_field,
                        self.url_field,
                    ],
                )

                documents = {}

                for result_list in search_results:
                    for result in result_list:
                        entity = result.get("entity", {})
                        doc_id = entity.get(self.id_field, "")
                        content = entity.get(self.content_field, "")
                        title = entity.get(self.title_field, "")
                        url = entity.get(self.url_field, "")
                        score = result.get("distance", 0.0)

                        # Skip if resource filtering is requested and this doc is not in the list
                        if resources:
                            doc_in_resources = False
                            for resource in resources:
                                if (
                                    url and url in resource.uri
                                ) or doc_id in resource.uri:
                                    doc_in_resources = True
                                    break
                            if not doc_in_resources:
                                continue

                        # Create or update document
                        if doc_id not in documents:
                            documents[doc_id] = Document(
                                id=doc_id, url=url, title=title, chunks=[]
                            )

                        # Add chunk to document
                        chunk = Chunk(content=content, similarity=score)
                        documents[doc_id].chunks.append(chunk)

                return list(documents.values())

            else:
                # For LangChain Milvus, use similarity search
                search_results = self.client.similarity_search_with_score(
                    query=query, k=self.top_k
                )

                documents = {}

                for doc, score in search_results:
                    metadata = doc.metadata or {}
                    doc_id = metadata.get(self.id_field, "")
                    title = metadata.get(self.title_field, "")
                    url = metadata.get(self.url_field, "")
                    content = doc.page_content

                    # Skip if resource filtering is requested and this doc is not in the list
                    if resources:
                        doc_in_resources = False
                        for resource in resources:
                            if (url and url in resource.uri) or doc_id in resource.uri:
                                doc_in_resources = True
                                break
                        if not doc_in_resources:
                            continue

                    # Create or update document
                    if doc_id not in documents:
                        documents[doc_id] = Document(
                            id=doc_id, url=url, title=title, chunks=[]
                        )

                    # Add chunk to document
                    chunk = Chunk(content=content, similarity=score)
                    documents[doc_id].chunks.append(chunk)

                return list(documents.values())

        except Exception as e:
            raise RuntimeError(f"Failed to query documents from Milvus: {str(e)}")

    def create_collection(self) -> None:
        """Public hook ensuring collection exists (explicit initialization)."""
        if not self.client:
            self._connect()
        else:
            # If we're using Milvus Lite, ensure collection exists
            if self._is_milvus_lite():
                self._ensure_collection_exists()

    def load_examples(self, force_reload: bool = False) -> None:
        """Load example markdown files, optionally clearing existing ones.

        Args:
            force_reload: If True existing example documents are deleted first.
        """
        if not self.client:
            self._connect()

        if force_reload:
            # Clear existing examples
            self._clear_example_documents()

        self._load_example_files()

    def _clear_example_documents(self) -> None:
        """Delete previously ingested example documents (Milvus Lite only)."""
        try:
            if self._is_milvus_lite():
                # For Milvus Lite, delete documents with source='examples'
                # Note: Milvus doesn't support direct delete by filter in all versions
                # So we'll query and delete by IDs
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="source == 'examples'",
                    output_fields=[self.id_field],
                    limit=10000,
                )

                if results:
                    doc_ids = [result[self.id_field] for result in results]
                    self.client.delete(
                        collection_name=self.collection_name, ids=doc_ids
                    )
                    logger.info("Cleared %d existing example documents", len(doc_ids))
            else:
                # For LangChain Milvus, we can't easily delete by metadata
                logger.info(
                    "Clearing existing examples not supported for LangChain Milvus client"
                )

        except Exception as e:
            logger.warning("Could not clear existing examples: %s", e)

    def get_loaded_examples(self) -> List[Dict[str, str]]:
        """Return metadata for previously ingested example documents."""
        try:
            if not self.client:
                self._connect()

            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="source == 'examples'",
                    output_fields=[
                        self.id_field,
                        self.title_field,
                        self.url_field,
                        "source",
                        "file",
                    ],
                    limit=1000,
                )

                examples = []
                for result in results:
                    examples.append(
                        {
                            "id": result.get(self.id_field, ""),
                            "title": result.get(self.title_field, ""),
                            "file": result.get("file", ""),
                            "url": result.get(self.url_field, ""),
                        }
                    )

                return examples
            else:
                # For LangChain Milvus, we can't easily filter by metadata
                logger.info(
                    "Getting loaded examples not supported for LangChain Milvus client"
                )
                return []

        except Exception as e:
            logger.error("Error getting loaded examples: %s", e)
            return []

    def close(self) -> None:
        """Release underlying client resources (idempotent)."""
        if hasattr(self, "client") and self.client:
            try:
                # For Milvus Lite (MilvusClient), close the connection
                if self._is_milvus_lite() and hasattr(self.client, "close"):
                    self.client.close()
                # For LangChain Milvus, no explicit close method needed
                self.client = None
            except Exception:
                # Ignore errors during cleanup
                pass

    def _sanitize_filename(self, filename: str, max_length: int = 200) -> str:
        """Sanitize filename for safe use in doc_id and URI construction.

        Args:
            filename: Original filename to sanitize.
            max_length: Maximum allowed length for the filename (default: 200).

        Returns:
            Sanitized filename safe for storage and URI construction.
        """
        # Extract basename to remove any path components
        sanitized = Path(filename).name

        # Remove or replace problematic characters
        # Keep alphanumeric, dots, hyphens, underscores; replace others with underscore
        sanitized = re.sub(r"[^\w.\-]", "_", sanitized)

        # Collapse multiple underscores
        sanitized = re.sub(r"_+", "_", sanitized)

        # Remove leading/trailing underscores and dots
        sanitized = sanitized.strip("_.")

        # Ensure we have a valid filename
        if not sanitized:
            sanitized = "unnamed_file"

        # Truncate if too long, preserving extension
        if len(sanitized) > max_length:
            # Try to preserve extension
            parts = sanitized.rsplit(".", 1)
            if len(parts) == 2 and len(parts[1]) <= 10:
                ext = "." + parts[1]
                base = parts[0][: max_length - len(ext)]
                sanitized = base + ext
            else:
                sanitized = sanitized[:max_length]

        return sanitized

    def _check_duplicate_file(self, filename: str) -> bool:
        """Check if a file with the same name has been uploaded before."""
        try:
            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter=f"file == '{filename}' and source == 'uploaded'",
                    output_fields=[self.id_field],
                    limit=1,
                )
                return len(results) > 0
            else:
                # For LangChain Milvus, perform a search with metadata filter
                docs = self.client.similarity_search(
                    "",
                    k=1,
                    expr=f"file == '{filename}' and source == 'uploaded'",
                )
                return len(docs) > 0
        except Exception:
            # If check fails, allow upload to proceed
            return False

    def ingest_file(self, file_content: bytes, filename: str, **kwargs) -> Resource:
        """Ingest a file into the Milvus vector store for RAG retrieval.

        This method processes an uploaded file, splits it into chunks if necessary,
        generates embeddings, and stores them in the configured Milvus collection.

        Args:
            file_content: Raw bytes of the file to ingest. Must be valid UTF-8
                encoded text content (e.g., markdown or plain text files).
            filename: Original filename. Used for title extraction, metadata storage,
                and URI construction. The filename is sanitized to remove special
                characters and path separators before use.
            **kwargs: Reserved for future use. Currently unused but accepted for
                forward compatibility (e.g., custom metadata, chunking options).

        Returns:
            Resource: Object containing:
                - uri: Milvus URI in format ``milvus://{collection}/{filename}``
                - title: Extracted from first markdown heading or derived from filename
                - description: "Uploaded file" or "Uploaded file (new version)"

        Raises:
            ValueError: If file_content cannot be decoded as UTF-8 text. This typically
                occurs when attempting to upload binary files (images, PDFs, etc.)
                which are not supported.
            RuntimeError: If document chunk insertion fails due to embedding generation
                errors, Milvus connection issues, or storage failures.
            ConnectionError: If unable to establish connection to Milvus server.

        Supported file types:
            - Markdown files (.md): Title extracted from first ``# heading``
            - Plain text files (.txt): Title derived from filename

        Duplicate handling:
            Files with the same name can be uploaded multiple times. Each upload
            creates a new document with a unique ID (includes timestamp). The
            description field indicates if this is a new version of an existing
            file. Old versions are retained in storage.

        Example:
            >>> retriever = MilvusRetriever()
            >>> with open("document.md", "rb") as f:
            ...     resource = retriever.ingest_file(f.read(), "document.md")
            >>> print(resource.uri)
            milvus://documents/document.md
        """
        # Check connection
        if not self.client:
            self._connect()

        # Sanitize filename to prevent issues with special characters and path traversal
        safe_filename = self._sanitize_filename(filename)
        if safe_filename != filename:
            logger.debug(
                "Filename sanitized: '%s' -> '%s'", filename, safe_filename
            )

        # Decode content (only UTF-8 text files supported)
        try:
            content = file_content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(
                "Only UTF-8 encoded text files are supported (e.g., .md, .txt). "
                "Binary files such as images, PDFs, or Word documents cannot be processed."
            )

        # Check for existing file with same name
        is_duplicate = self._check_duplicate_file(safe_filename)
        if is_duplicate:
            logger.info(
                "File '%s' was previously uploaded. Creating new version.", safe_filename
            )

        # Generate unique doc_id using filename, content length, and timestamp
        # Timestamp ensures uniqueness even for identical re-uploads
        timestamp = int(time.time() * 1000)  # millisecond precision
        content_hash = hashlib.md5(
            f"{safe_filename}_{len(content)}_{timestamp}".encode()
        ).hexdigest()[:8]
        base_name = safe_filename.rsplit(".", 1)[0] if "." in safe_filename else safe_filename
        doc_id = f"uploaded_{base_name}_{content_hash}"

        title = self._extract_title_from_markdown(content, safe_filename)
        chunks = self._split_content(content)

        # Insert chunks
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}" if len(chunks) > 1 else doc_id
            self._insert_document_chunk(
                doc_id=chunk_id,
                content=chunk,
                title=title,
                url=f"milvus://{self.collection_name}/{safe_filename}",
                metadata={"source": "uploaded", "file": safe_filename, "timestamp": timestamp},
            )

        description = "Uploaded file (new version)" if is_duplicate else "Uploaded file"
        return Resource(
            uri=f"milvus://{self.collection_name}/{safe_filename}",
            title=title,
            description=description,
        )

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        """Best-effort cleanup when instance is garbage collected."""
        self.close()


# Backwards compatibility export (original class name kept for external imports)
class MilvusProvider(MilvusRetriever):
    """Backward compatible alias for ``MilvusRetriever`` (original name)."""

    pass


def load_examples() -> None:
    auto_load_examples = get_bool_env("MILVUS_AUTO_LOAD_EXAMPLES", False)
    rag_provider = get_str_env("RAG_PROVIDER", "")
    if rag_provider == "milvus" and auto_load_examples:
        provider = MilvusProvider()
        provider.load_examples()
