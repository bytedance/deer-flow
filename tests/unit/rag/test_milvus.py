# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.rag.milvus as milvus_mod
from src.rag.milvus import MilvusProvider
from src.rag.retriever import Resource


class DummyEmbedding:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def embed_query(self, text: str):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    # Prevent network / external API usage during __init__
    monkeypatch.setenv("MILVUS_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("MILVUS_EMBEDDING_MODEL", "text-embedding-ada-002")
    monkeypatch.setenv("MILVUS_COLLECTION", "documents")
    monkeypatch.setenv("MILVUS_URI", "./milvus_demo.db")  # default lite
    monkeypatch.setattr(milvus_mod, "OpenAIEmbeddings", DummyEmbedding)
    monkeypatch.setattr(milvus_mod, "DashscopeEmbeddings", DummyEmbedding)
    yield


@pytest.fixture
def project_root():
    # Mirror logic from implementation: current_file.parent.parent.parent
    return Path(milvus_mod.__file__).parent.parent.parent


def _patch_init(monkeypatch):
    """Patch retriever initialization to use dummy embedding model."""
    monkeypatch.setattr(
        MilvusProvider,
        "_init_embedding_model",
        lambda self: setattr(self, "embedding_model", DummyEmbedding()),
    )


def test_list_local_markdown_resources_missing_dir(project_root):
    retriever = MilvusProvider()
    # Point to a non-existent examples dir
    retriever.examples_dir = f"missing_examples_{uuid4().hex}"
    resources = retriever._list_local_markdown_resources()
    assert resources == []


def test_list_local_markdown_resources_populated(project_root):
    retriever = MilvusProvider()
    examples_dir = f"examples_test_{uuid4().hex}"
    retriever.examples_dir = examples_dir
    target_dir = project_root / examples_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # File with heading
    (target_dir / "file1.md").write_text(
        "# Title One\n\nContent body.", encoding="utf-8"
    )
    # File without heading -> fallback title
    (target_dir / "file_two.md").write_text("No heading here.", encoding="utf-8")
    # Non-markdown file should be ignored
    (target_dir / "ignore.txt").write_text("Should not be picked up.", encoding="utf-8")

    resources = retriever._list_local_markdown_resources()
    # Order not guaranteed; sort by uri for assertions
    resources.sort(key=lambda r: r.uri)

    # Expect two resources
    assert len(resources) == 2
    uris = {r.uri for r in resources}
    assert uris == {
        f"milvus://{retriever.collection_name}/file1.md",
        f"milvus://{retriever.collection_name}/file_two.md",
    }

    res_map = {r.uri: r for r in resources}
    r1 = res_map[f"milvus://{retriever.collection_name}/file1.md"]
    assert isinstance(r1, Resource)
    assert r1.title == "Title One"
    assert r1.description == "Local markdown example (not yet ingested)"

    r2 = res_map[f"milvus://{retriever.collection_name}/file_two.md"]
    # Fallback logic: filename -> "file_two" -> "file two" -> title case -> "File Two"
    assert r2.title == "File Two"
    assert r2.description == "Local markdown example (not yet ingested)"


def test_list_local_markdown_resources_read_error(monkeypatch, project_root):
    retriever = MilvusProvider()
    examples_dir = f"examples_error_{uuid4().hex}"
    retriever.examples_dir = examples_dir
    target_dir = project_root / examples_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    bad_file = target_dir / "bad.md"
    good_file = target_dir / "good.md"
    good_file.write_text("# Good Title\n\nBody.", encoding="utf-8")
    bad_file.write_text("Broken", encoding="utf-8")

    # Patch Path.read_text to raise for bad.md only
    original_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if self == bad_file:
            raise OSError("Cannot read file")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    resources = retriever._list_local_markdown_resources()
    # Only good.md should appear
    assert len(resources) == 1
    r = resources[0]
    assert r.title == "Good Title"
    assert r.uri == f"milvus://{retriever.collection_name}/good.md"


def test_create_collection_schema_fields(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    schema = retriever._create_collection_schema()
    field_names = {f.name for f in schema.fields}
    # Core fields must be present
    assert {
        retriever.id_field,
        retriever.vector_field,
        retriever.content_field,
    } <= field_names
    # Dynamic field enabled for extra metadata
    assert schema.enable_dynamic_field is True


def test_generate_doc_id_stable(monkeypatch, tmp_path):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    test_file = tmp_path / "example.md"
    test_file.write_text("# Title\nBody", encoding="utf-8")
    doc_id1 = retriever._generate_doc_id(test_file)
    doc_id2 = retriever._generate_doc_id(test_file)
    assert doc_id1 == doc_id2  # deterministic given unchanged file metadata


def test_extract_title_from_markdown(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    heading = retriever._extract_title_from_markdown("# Heading\nBody", "ignored.md")
    assert heading == "Heading"
    fallback = retriever._extract_title_from_markdown("Body only", "my_file_name.md")
    assert fallback == "My File Name"


def test_split_content_chunking(monkeypatch):
    monkeypatch.setenv("MILVUS_CHUNK_SIZE", "40")  # small to force split
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    long_content = (
        "Para1 text here.\n\nPara2 second block.\n\nPara3 final."  # 3 paragraphs
    )
    chunks = retriever._split_content(long_content)
    assert len(chunks) >= 2  # forced split
    assert all(chunks)  # no empty chunks


def test_get_embedding_invalid_inputs(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    # Non-string value
    with pytest.raises(RuntimeError):
        retriever._get_embedding(123)  # type: ignore[arg-type]
    # Whitespace only
    with pytest.raises(RuntimeError):
        retriever._get_embedding("   ")


def test_list_resources_remote_success_and_dedup(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    class DocObj:
        def __init__(self, content: str, meta: dict):
            self.page_content = content
            self.metadata = meta

    calls = {"similarity_search": 0}

    class RemoteClient:
        def similarity_search(self, query, k, expr):  # noqa: D401
            calls["similarity_search"] += 1
            # Two docs with identical id to test dedup
            meta1 = {
                retriever.id_field: "d1",
                retriever.title_field: "T1",
                retriever.url_field: "u1",
            }
            meta2 = {
                retriever.id_field: "d1",
                retriever.title_field: "T1_dup",
                retriever.url_field: "u1",
            }
            return [DocObj("c1", meta1), DocObj("c1_dup", meta2)]

    retriever.client = RemoteClient()
    resources = retriever.list_resources("query text")
    assert len(resources) == 1  # dedup applied
    assert resources[0].title.startswith("T1")
    assert calls["similarity_search"] == 1


def test_list_resources_lite_success(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    class DummyMilvusLite:
        def query(self, collection_name, filter, output_fields, limit):  # noqa: D401
            return [
                {
                    retriever.id_field: "idA",
                    retriever.title_field: "Alpha",
                    retriever.url_field: "u://a",
                },
                {
                    retriever.id_field: "idB",
                    retriever.title_field: "Beta",
                    retriever.url_field: "u://b",
                },
            ]

    retriever.client = DummyMilvusLite()
    resources = retriever.list_resources()
    assert {r.title for r in resources} == {"Alpha", "Beta"}


def test_query_relevant_documents_lite_success(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    # Provide deterministic embedding output
    retriever.embedding_model.embed_query = lambda text: [0.1, 0.2, 0.3]  # type: ignore

    class DummyMilvusLite:
        def search(
            self, collection_name, data, anns_field, param, limit, output_fields
        ):  # noqa: D401
            # Simulate two result entries
            return [
                [
                    {
                        "entity": {
                            retriever.id_field: "d1",
                            retriever.content_field: "c1",
                            retriever.title_field: "T1",
                            retriever.url_field: "u1",
                        },
                        "distance": 0.9,
                    },
                    {
                        "entity": {
                            retriever.id_field: "d2",
                            retriever.content_field: "c2",
                            retriever.title_field: "T2",
                            retriever.url_field: "u2",
                        },
                        "distance": 0.8,
                    },
                ]
            ]

    retriever.client = DummyMilvusLite()
    # Filter for only d2 via resource list
    docs = retriever.query_relevant_documents(
        "question", resources=[Resource(uri="milvus://d2", title="", description="")]
    )
    assert len(docs) == 1 and docs[0].id == "d2" and docs[0].chunks[0].similarity == 0.8


def test_query_relevant_documents_remote_success(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.embedding_model.embed_query = lambda text: [0.1, 0.2, 0.3]  # type: ignore

    class DocObj:
        def __init__(self, content: str, meta: dict):  # noqa: D401
            self.page_content = content
            self.metadata = meta

    class RemoteClient:
        def similarity_search_with_score(self, query, k):  # noqa: D401
            return [
                (
                    DocObj(
                        "c1",
                        {
                            retriever.id_field: "d1",
                            retriever.title_field: "T1",
                            retriever.url_field: "u1",
                        },
                    ),
                    0.7,
                ),
                (
                    DocObj(
                        "c2",
                        {
                            retriever.id_field: "d2",
                            retriever.title_field: "T2",
                            retriever.url_field: "u2",
                        },
                    ),
                    0.6,
                ),
            ]

    retriever.client = RemoteClient()
    # Filter to only d1
    docs = retriever.query_relevant_documents(
        "q", resources=[Resource(uri="milvus://d1", title="", description="")]
    )
    assert len(docs) == 1 and docs[0].id == "d1" and docs[0].chunks[0].similarity == 0.7


def test_get_embedding_dimension_explicit(monkeypatch):
    monkeypatch.setenv("MILVUS_EMBEDDING_DIM", "777")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    assert retriever.embedding_dim == 777


def test_get_embedding_dimension_unknown_model(monkeypatch):
    monkeypatch.delenv("MILVUS_EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("MILVUS_EMBEDDING_MODEL", "unknown-model-x")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    # falls back to default 1536
    assert retriever.embedding_dim == 1536


def test_is_milvus_lite_variants(monkeypatch):
    _patch_init(monkeypatch)
    monkeypatch.setenv("MILVUS_URI", "mydb.db")
    assert MilvusProvider()._is_milvus_lite() is True
    monkeypatch.setenv("MILVUS_URI", "relative_path_store")
    assert MilvusProvider()._is_milvus_lite() is True
    monkeypatch.setenv("MILVUS_URI", "http://host:19530")
    assert MilvusProvider()._is_milvus_lite() is False


def test_create_collection_lite(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    created: dict = {}

    class DummyMilvusLite:
        def list_collections(self):  # noqa: D401
            return []  # empty triggers creation

        def create_collection(self, collection_name, schema, index_params):  # noqa: D401
            created["name"] = collection_name
            created["schema"] = schema
            created["index"] = index_params

    retriever.client = DummyMilvusLite()
    retriever._ensure_collection_exists()
    assert created["name"] == retriever.collection_name


def test_ensure_collection_exists_remote(monkeypatch):
    _patch_init(monkeypatch)
    monkeypatch.setenv("MILVUS_URI", "http://remote:19530")
    retriever = MilvusProvider()
    # remote path, nothing thrown
    retriever.client = SimpleNamespace()
    retriever._ensure_collection_exists()


def test_get_existing_document_ids_lite(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    class DummyMilvusLite:
        def query(self, collection_name, filter, output_fields, limit):  # noqa: D401
            return [
                {retriever.id_field: "a"},
                {retriever.id_field: "b"},
                {"other": "ignored"},
            ]

    retriever.client = DummyMilvusLite()
    assert retriever._get_existing_document_ids() == {"a", "b"}


def test_get_existing_document_ids_remote(monkeypatch):
    _patch_init(monkeypatch)
    monkeypatch.setenv("MILVUS_URI", "http://x")
    retriever = MilvusProvider()
    retriever.client = object()
    assert retriever._get_existing_document_ids() == set()


def test_insert_document_chunk_lite_and_error(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    captured = {}

    class DummyMilvusLite:
        def insert(self, collection_name, data):  # noqa: D401
            captured["data"] = data

    retriever.client = DummyMilvusLite()
    retriever._insert_document_chunk(
        doc_id="id1", content="hello", title="T", url="u", metadata={"m": 1}
    )
    assert captured["data"][0][retriever.id_field] == "id1"

    # error path: patch embedding to raise
    def bad_embed(text):  # noqa: D401
        raise RuntimeError("boom")

    retriever.embedding_model.embed_query = bad_embed  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        retriever._insert_document_chunk(
            doc_id="id2", content="err", title="T", url="u", metadata={}
        )


def test_insert_document_chunk_remote(monkeypatch):
    _patch_init(monkeypatch)
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    retriever = MilvusProvider()
    added = {}

    class RemoteClient:
        def add_texts(self, texts, metadatas):  # noqa: D401
            added["texts"] = texts
            added["meta"] = metadatas

    retriever.client = RemoteClient()
    retriever._insert_document_chunk(
        doc_id="idx", content="ct", title="Title", url="urlx", metadata={"k": 2}
    )
    assert added["meta"][0][retriever.id_field] == "idx"


def test_connect_lite_and_error(monkeypatch):
    # patch MilvusClient to a dummy
    class FakeMilvusClient:
        def __init__(self, uri):  # noqa: D401
            self.uri = uri

        def list_collections(self):  # noqa: D401
            return []

        def create_collection(self, **kwargs):  # noqa: D401
            pass

    monkeypatch.setattr(milvus_mod, "MilvusClient", FakeMilvusClient)
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever._connect()
    assert isinstance(retriever.client, FakeMilvusClient)

    # error path: patch MilvusClient to raise
    class BadClient:
        def __init__(self, uri):  # noqa: D401
            raise RuntimeError("fail connect")

    monkeypatch.setattr(milvus_mod, "MilvusClient", BadClient)
    retriever2 = MilvusProvider()
    with pytest.raises(ConnectionError):
        retriever2._connect()


def test_connect_remote(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    created = {}

    class FakeLangchainMilvus:
        def __init__(self, **kwargs):  # noqa: D401
            created.update(kwargs)

    monkeypatch.setattr(milvus_mod, "LangchainMilvus", FakeLangchainMilvus)
    retriever = MilvusProvider()
    retriever._connect()
    assert created["collection_name"] == retriever.collection_name


def test_list_resources_remote_failure(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    # Provide minimal working local examples dir (none -> returns [])
    monkeypatch.setattr(retriever, "_list_local_markdown_resources", lambda: [])

    # patch client to raise inside similarity_search to trigger fallback path
    class BadClient:
        def similarity_search(self, *args, **kwargs):  # noqa: D401
            raise RuntimeError("fail")

    retriever.client = BadClient()
    # Should fallback to [] without raising
    assert retriever.list_resources() == []


def test_list_local_markdown_resources_empty(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    monkeypatch.setenv("MILVUS_EXAMPLES_DIR", "nonexistent_dir")
    retriever.examples_dir = "nonexistent_dir"
    assert retriever._list_local_markdown_resources() == []


def test_query_relevant_documents_error(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.embedding_model.embed_query = lambda text: (  # type: ignore
        _ for _ in ()
    ).throw(RuntimeError("embed fail"))
    with pytest.raises(RuntimeError):
        retriever.query_relevant_documents("q")


def test_create_collection_when_client_exists(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.client = SimpleNamespace(closed=False)
    # remote vs lite path difference handled by _is_milvus_lite
    retriever.create_collection()  # should no-op gracefully


def test_load_examples_force_reload(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.client = SimpleNamespace()
    called = {"clear": 0, "load": 0}
    monkeypatch.setattr(
        retriever, "_clear_example_documents", lambda: called.__setitem__("clear", 1)
    )
    monkeypatch.setattr(
        retriever, "_load_example_files", lambda: called.__setitem__("load", 1)
    )
    retriever.load_examples(force_reload=True)
    assert called == {"clear": 1, "load": 1}


def test_clear_example_documents_remote(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.client = SimpleNamespace()
    # Should just log and not raise
    retriever._clear_example_documents()


def test_clear_example_documents_lite(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    deleted = {}

    class DummyMilvusLite:
        def query(self, **kwargs):  # noqa: D401
            return [
                {retriever.id_field: "ex1"},
                {retriever.id_field: "ex2"},
            ]

        def delete(self, collection_name, ids):  # noqa: D401
            deleted["ids"] = ids

    retriever.client = DummyMilvusLite()
    retriever._clear_example_documents()
    assert deleted["ids"] == ["ex1", "ex2"]


def test_get_loaded_examples_lite_and_error(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()

    class DummyMilvusLite:
        def query(self, **kwargs):  # noqa: D401
            return [
                {
                    retriever.id_field: "id1",
                    retriever.title_field: "T1",
                    retriever.url_field: "u1",
                    "file": "f1",
                }
            ]

    retriever.client = DummyMilvusLite()
    loaded = retriever.get_loaded_examples()
    assert loaded[0]["id"] == "id1"

    # error path
    class BadClient:
        def query(self, **kwargs):  # noqa: D401
            raise RuntimeError("fail")

    retriever.client = BadClient()
    assert retriever.get_loaded_examples() == []


def test_get_loaded_examples_remote(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    retriever.client = SimpleNamespace()
    assert retriever.get_loaded_examples() == []


def test_close_lite_and_remote(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    closed = {"c": 0}

    class DummyMilvusLite:
        def close(self):  # noqa: D401
            closed["c"] += 1

        def list_collections(self):  # noqa: D401
            return []

        def create_collection(self, **kwargs):  # noqa: D401
            pass

    retriever.client = DummyMilvusLite()
    retriever.close()
    assert closed["c"] == 1

    # remote path: no close attr usage expected
    monkeypatch.setenv("MILVUS_URI", "http://remote")
    retriever2 = MilvusProvider()
    retriever2.client = SimpleNamespace()
    retriever2.close()  # should not raise


def test_get_embedding_invalid_output(monkeypatch):
    _patch_init(monkeypatch)
    retriever = MilvusProvider()
    # patch embedding model to return invalid output (empty list)
    retriever.embedding_model.embed_query = lambda text: []  # type: ignore
    with pytest.raises(RuntimeError):
        retriever._get_embedding("text")


def test_dashscope_embeddings_empty_inputs_short_circuit(monkeypatch):
    # Use real class but swap _client to ensure create is never called
    emb = milvus_mod.DashscopeEmbeddings(model="m")

    class FailingClient:
        class _Emb:
            def create(self, *a, **k):
                raise AssertionError("Should not be called for empty input")

        embeddings = _Emb()

    emb._client = FailingClient()  # type: ignore
    assert emb.embed_documents([]) == []


# Tests for _init_embedding_model provider selection logic
def test_init_embedding_model_openai(monkeypatch):
    monkeypatch.setenv("MILVUS_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("MILVUS_EMBEDDING_MODEL", "text-embedding-ada-002")
    captured = {}

    class CapturingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(milvus_mod, "OpenAIEmbeddings", CapturingOpenAI)
    prov = MilvusProvider()
    assert isinstance(prov.embedding_model, CapturingOpenAI)
    # kwargs forwarded
    assert captured["model"] == "text-embedding-ada-002"
    assert captured["encoding_format"] == "float"
    assert captured["dimensions"] == prov.embedding_dim


def test_init_embedding_model_dashscope(monkeypatch):
    monkeypatch.setenv("MILVUS_EMBEDDING_PROVIDER", "dashscope")
    monkeypatch.setenv("MILVUS_EMBEDDING_MODEL", "text-embedding-ada-002")
    captured = {}

    class CapturingDashscope:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(milvus_mod, "DashscopeEmbeddings", CapturingDashscope)
    prov = MilvusProvider()
    assert isinstance(prov.embedding_model, CapturingDashscope)
    assert captured["model"] == "text-embedding-ada-002"
    assert captured["encoding_format"] == "float"
    assert captured["dimensions"] == prov.embedding_dim


def test_init_embedding_model_invalid_provider(monkeypatch):
    monkeypatch.setenv("MILVUS_EMBEDDING_PROVIDER", "not_a_provider")
    with pytest.raises(ValueError):
        MilvusProvider()


def test_load_example_files_directory_missing(monkeypatch):
    _patch_init(monkeypatch)
    missing_dir = "examples_dir_does_not_exist_xyz"
    monkeypatch.setenv("MILVUS_EXAMPLES_DIR", missing_dir)
    retriever = MilvusProvider()
    retriever.examples_dir = missing_dir
    called = {"insert": 0}
    monkeypatch.setattr(
        retriever,
        "_insert_document_chunk",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not insert")),
    )
    retriever._load_example_files()
    assert called["insert"] == 0  # sanity (no insertion attempted)


def test_load_example_files_loads_and_skips_existing(monkeypatch):
    _patch_init(monkeypatch)
    project_root = Path(milvus_mod.__file__).parent.parent.parent
    examples_dir_name = "examples_test_load_skip"
    examples_path = project_root / examples_dir_name
    examples_path.mkdir(exist_ok=True)

    file1 = examples_path / "file1.md"
    file2 = examples_path / "file2.md"
    file1.write_text("# Title One\nContent A", encoding="utf-8")
    file2.write_text("# Title Two\nContent B", encoding="utf-8")

    monkeypatch.setenv("MILVUS_EXAMPLES_DIR", examples_dir_name)
    retriever = MilvusProvider()
    retriever.examples_dir = examples_dir_name

    # Compute doc ids using real method
    doc_id_file1 = retriever._generate_doc_id(file1)
    doc_id_file2 = retriever._generate_doc_id(file2)

    # Existing docs contains file1 so it is skipped
    monkeypatch.setattr(retriever, "_get_existing_document_ids", lambda: {doc_id_file1})
    # Force two chunks for any file to test suffix logic
    monkeypatch.setattr(retriever, "_split_content", lambda content: ["part1", "part2"])

    calls = []

    def record_insert(doc_id, content, title, url, metadata):
        calls.append(
            {
                "doc_id": doc_id,
                "content": content,
                "title": title,
                "url": url,
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(retriever, "_insert_document_chunk", record_insert)

    retriever._load_example_files()

    # Only file2 processed -> two chunk inserts
    assert len(calls) == 2
    expected_ids = {f"{doc_id_file2}_chunk_0", f"{doc_id_file2}_chunk_1"}
    assert {c["doc_id"] for c in calls} == expected_ids
    assert all(c["metadata"]["file"] == "file2.md" for c in calls)
    assert all(c["metadata"]["source"] == "examples" for c in calls)
    assert all(c["title"] == "Title Two" for c in calls)


def test_load_example_files_single_chunk_no_suffix(monkeypatch):
    _patch_init(monkeypatch)
    project_root = Path(milvus_mod.__file__).parent.parent.parent
    examples_dir_name = "examples_test_single_chunk"
    examples_path = project_root / examples_dir_name
    examples_path.mkdir(exist_ok=True)

    file_single = examples_path / "single.md"
    file_single.write_text(
        "# Single Title\nOnly one small paragraph.", encoding="utf-8"
    )

    monkeypatch.setenv("MILVUS_EXAMPLES_DIR", examples_dir_name)
    retriever = MilvusProvider()
    retriever.examples_dir = examples_dir_name

    base_doc_id = retriever._generate_doc_id(file_single)

    monkeypatch.setattr(retriever, "_get_existing_document_ids", lambda: set())
    monkeypatch.setattr(retriever, "_split_content", lambda content: ["onlychunk"])

    captured = {}

    def capture(doc_id, content, title, url, metadata):
        captured["doc_id"] = doc_id
        captured["title"] = title
        captured["metadata"] = metadata

    monkeypatch.setattr(retriever, "_insert_document_chunk", capture)

    retriever._load_example_files()

    assert captured["doc_id"] == base_doc_id  # no _chunk_ suffix
    assert captured["title"] == "Single Title"
    assert captured["metadata"]["file"] == "single.md"
    assert captured["metadata"]["source"] == "examples"
