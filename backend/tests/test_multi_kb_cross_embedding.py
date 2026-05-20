"""Tests for cross-embedding-model multi-KB retrieval (Sprint B.3.4).

When a user selects 5 KBs across 3 different embedding models, we must:

1. Build exactly 3 embedding providers (deduped by ``embedding_model``),
   not one per KB — same ``query`` text only needs to be embedded once
   per model.
2. Use each KB's own embedder when querying its collection — using the
   global default would produce vectors of the wrong dim or wrong
   space, making cosine similarity meaningless.
3. Record ``embedding_model`` in per-KB stats and the
   ``embedding_models_used`` summary so traces show which models the
   query was run against.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.config.tenant import get_current_tenant_id, reset_tenant_id, set_current_tenant_id
from deerflow.knowledge_base.retrieval import multi_kb_retrieve
from deerflow.rag.retrieval import RetrievalResult
from deerflow.rag.vector_store import SearchResult


def _make_kb(
    *, kb_id: str, name: str, embedding_model: str | None
) -> dict[str, Any]:
    return {
        "id": kb_id,
        "name": name,
        "collection_name": f"col_{kb_id}",
        "visibility": "private",
        "embedding_model": embedding_model,
    }


class TestCrossEmbeddingModelRetrieval:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_dedupes_embedders_by_model(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kbs = [
            _make_kb(kb_id="a", name="A", embedding_model="openai:m1"),
            _make_kb(kb_id="b", name="B", embedding_model="openai:m1"),
            _make_kb(kb_id="c", name="C", embedding_model="openai:m2"),
            _make_kb(kb_id="d", name="D", embedding_model="local:m3"),
            _make_kb(kb_id="e", name="E", embedding_model="openai:m2"),
        ]

        captured_specs: list[str | None] = []

        def fake_provider(spec: str | None = None):
            captured_specs.append(spec)
            embedder = MagicMock()
            embedder.embed_query.return_value = [0.1, 0.2, 0.3]
            return embedder

        def fake_retrieve(self, *, query, collection, top_k):
            return RetrievalResult(query=query, results=[], collection=collection)

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_provider,
        ), patch(
            "deerflow.rag.retrieval.DocumentRetriever.retrieve",
            new=fake_retrieve,
        ):
            multi_kb_retrieve(kbs, query="q", top_k=4)

        # 3 unique embedding models → 3 calls, regardless of how many
        # KBs reuse them.
        assert sorted(filter(None, captured_specs)) == [
            "local:m3",
            "openai:m1",
            "openai:m2",
        ]

    def test_each_kb_uses_its_own_embedder(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kbs = [
            _make_kb(kb_id="a", name="A", embedding_model="openai:m1"),
            _make_kb(kb_id="b", name="B", embedding_model="openai:m2"),
        ]

        # Map each provider mock to a distinct fingerprint so we can
        # check which one each KB's retriever ended up holding.
        providers: dict[str, MagicMock] = {}

        def fake_provider(spec: str | None = None):
            if spec not in providers:
                p = MagicMock(name=f"embedder-{spec}")
                p.spec_value = spec
                p.embed_query.return_value = [0.0]
                providers[spec] = p
            return providers[spec]

        seen: list[tuple[str, Any]] = []

        def fake_retrieve(self, *, query, collection, top_k):
            seen.append((collection, getattr(self._embedder, "spec_value", None)))
            return RetrievalResult(query=query, results=[], collection=collection)

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_provider,
        ), patch(
            "deerflow.rag.retrieval.DocumentRetriever.retrieve",
            new=fake_retrieve,
        ):
            multi_kb_retrieve(kbs, query="q", top_k=4)

        # Each (collection, embedder spec) pair must match the KB's
        # configured model.
        seen_map = dict(seen)
        assert seen_map["col_a"] == "openai:m1"
        assert seen_map["col_b"] == "openai:m2"

    def test_multi_kb_retrieve_restores_explicit_tenant_context_in_workers(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kbs = [
            _make_kb(kb_id="a", name="A", embedding_model="openai:m1"),
            _make_kb(kb_id="b", name="B", embedding_model="openai:m2"),
        ]

        observed: list[tuple[str, str]] = []

        def fake_provider(spec: str | None = None):
            embedder = MagicMock()
            embedder.embed_query.return_value = [0.0]
            return embedder

        def fake_retrieve(self, *, query, collection, top_k):
            observed.append((collection, get_current_tenant_id()))
            return RetrievalResult(query=query, results=[], collection=collection)

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_provider,
        ), patch(
            "deerflow.rag.retrieval.DocumentRetriever.retrieve",
            new=fake_retrieve,
        ):
            multi_kb_retrieve(
                kbs,
                query="q",
                top_k=4,
                tenant_id="tenant-acme",
                user_id="user-1",
            )

        assert observed
        assert {tenant_id for _, tenant_id in observed} == {"tenant-acme"}

    def test_multi_kb_retrieve_inherits_current_tenant_context_when_not_explicit(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        token = set_current_tenant_id("tenant-inherited")
        try:
            kbs = [
                _make_kb(kb_id="a", name="A", embedding_model="openai:m1"),
            ]

            observed: list[str] = []

            def fake_provider(spec: str | None = None):
                embedder = MagicMock()
                embedder.embed_query.return_value = [0.0]
                return embedder

            def fake_retrieve(self, *, query, collection, top_k):
                observed.append(get_current_tenant_id())
                return RetrievalResult(query=query, results=[], collection=collection)

            with patch(
                "deerflow.knowledge_base.retrieval.get_embedding_provider",
                side_effect=fake_provider,
            ), patch(
                "deerflow.rag.retrieval.DocumentRetriever.retrieve",
                new=fake_retrieve,
            ):
                multi_kb_retrieve(kbs, query="q", top_k=4)
        finally:
            reset_tenant_id(token)

        assert observed == ["tenant-inherited"]

    def test_logs_embedding_models_used(self, caplog) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kbs = [
            _make_kb(kb_id="a", name="A", embedding_model="openai:m1"),
            _make_kb(kb_id="b", name="B", embedding_model="openai:m2"),
        ]

        def fake_provider(spec: str | None = None):
            embedder = MagicMock()
            embedder.embed_query.return_value = [0.1]
            return embedder

        def fake_retrieve(self, *, query, collection, top_k):
            return RetrievalResult(
                query=query,
                collection=collection,
                results=[
                    SearchResult(
                        chunk_id="c1",
                        content=f"hit-{collection}",
                        metadata={"document_id": f"d-{collection}"},
                        score=0.5,
                    )
                ],
            )

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_provider,
        ), patch(
            "deerflow.rag.retrieval.DocumentRetriever.retrieve",
            new=fake_retrieve,
        ), caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
            results = multi_kb_retrieve(kbs, query="q", top_k=4)

        log_text = " ".join(
            r.getMessage()
            for r in caplog.records
            if r.name == "deerflow.knowledge_base.retrieval"
        )
        assert "embedding_models_used" in log_text
        assert "openai:m1" in log_text
        assert "openai:m2" in log_text
        assert {r.metadata.get("embedding_model") for r in results} == {
            "openai:m1",
            "openai:m2",
        }

    def test_legacy_kb_without_embedding_model_falls_back_to_global(
        self,
    ) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kbs = [_make_kb(kb_id="legacy", name="L", embedding_model=None)]

        captured: list[str | None] = []

        def fake_provider(spec: str | None = None):
            captured.append(spec)
            embedder = MagicMock()
            embedder.embed_query.return_value = [0.0]
            return embedder

        def fake_retrieve(self, *, query, collection, top_k):
            return RetrievalResult(query=query, results=[], collection=collection)

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_provider,
        ), patch(
            "deerflow.rag.retrieval.DocumentRetriever.retrieve",
            new=fake_retrieve,
        ):
            multi_kb_retrieve(kbs, query="q", top_k=4)

        # ``None`` triggers the global-default branch in get_embedding_provider().
        assert captured == [None]
