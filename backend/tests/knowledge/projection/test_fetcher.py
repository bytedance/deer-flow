"""Tests for the projection fetcher (spec §5 P2).

Pure unit tests with duck-typed fakes — no Qdrant, no DB. The fetcher's
contract: merge the four collections into one tagged point set, subsample
chunks only (ID-first, then a batched retrieve), join chunk previews from the
business DB, and keep the matrix row-aligned with the surviving points.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from deerflow.knowledge.projection.fetcher import fetch_projection_vectors

_DIMS = 8  # fake vectors stay tiny; the fetcher is dimension-agnostic


def _vec(seed: float) -> list[float]:
    return [float(seed)] * _DIMS


def _chunk_record(i: int, *, kb_id: str = "kb-1", doc: str = "doc-1") -> tuple[str, dict[str, Any], list[float]]:
    cid = f"{doc}#{i:04d}"
    return (f"pt-{cid}", {"chunk_id": cid, "kb_id": kb_id, "doc_id": doc, "doc_name": f"{doc}.pdf", "entities": []}, _vec(i + 1))


class _FakeVectorStore:
    """Duck-typed stand-in for KnowledgeVectorStore (scroll + retrieve only)."""

    chunks_collection = "c_chunks"
    entities_collection = "c_entities"
    wiki_entries_collection = "c_wiki"
    manual_cards_collection = "c_cards"

    def __init__(self, data: dict[str, list[tuple[str, dict[str, Any], list[float]]]]) -> None:
        self._data = data
        self.drop_on_retrieve: set[str] = set()
        self.scrolled: list[str] = []
        self.retrieve_calls: list[list[Any]] = []

    async def scroll_collection(self, collection: str, kb_id: str, *, with_vectors: bool = False, batch_size: int = 512):
        self.scrolled.append(collection)
        return [SimpleNamespace(id=pid, payload=dict(payload)) for pid, payload, _dense in self._data.get(collection, [])]

    async def retrieve_vectors(self, collection: str, point_ids):
        self.retrieve_calls.append(list(point_ids))
        lut = {pid: dense for pid, _payload, dense in self._data.get(collection, [])}
        return {str(pid): lut[pid] for pid in point_ids if pid in lut and str(pid) not in self.drop_on_retrieve}


class _FakeStore:
    """Duck-typed stand-in for KnowledgeStore (chunk preview join only)."""

    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self._rows = rows

    async def get_chunks_by_ids(self, chunk_ids):
        return [self._rows[cid] for cid in chunk_ids if cid in self._rows]


def _vs(**data: list[tuple[str, dict[str, Any], list[float]]]) -> _FakeVectorStore:
    return _FakeVectorStore({f"c_{key}": value for key, value in data.items()})


async def test_merges_all_collections_and_tags_source_type() -> None:
    vs = _vs(
        chunks=[_chunk_record(0)],
        entities=[("pt-e1", {"kb_id": "kb-1", "name": "JVM", "type": "技术", "description": "Java 虚拟机"}, _vec(10))],
        wiki=[("pt-w1", {"kb_id": "kb-1", "entry_id": "entry-1", "title": "JVM"}, _vec(11))],
        cards=[("pt-c1", {"kb_id": "kb-1", "card_id": "card-1", "title": "速记"}, _vec(12))],
    )
    store = _FakeStore({"doc-1#0000": {"chunk_id": "doc-1#0000", "text": "堆内存存放对象实例", "heading_path": ["第1章"]}})

    result = await fetch_projection_vectors(vs, store, "kb-1")

    assert result.sampled is False
    assert result.total_points == 4
    by_type = {p.source_type: p for p in result.points}
    assert set(by_type) == {"chunk", "entity", "wiki", "card"}
    # chunk: label=doc_name, color_key=doc_id, preview from the DB row
    assert by_type["chunk"].id == "doc-1#0000"
    assert by_type["chunk"].label == "doc-1.pdf"
    assert by_type["chunk"].color_key == "doc-1"
    assert by_type["chunk"].preview == "堆内存存放对象实例"
    assert by_type["chunk"].heading_path == ("第1章",)
    # entity: label=name, color_key=type, preview=description
    assert by_type["entity"].label == "JVM"
    assert by_type["entity"].color_key == "技术"
    assert by_type["entity"].entity_type == "技术"
    assert by_type["entity"].preview == "Java 虚拟机"
    # wiki/card: single-tone color_key, title as label+preview
    assert by_type["wiki"].id == "entry-1"
    assert by_type["wiki"].color_key == "wiki"
    assert by_type["card"].id == "card-1"
    assert by_type["card"].color_key == "card"
    # matrix stays row-aligned with the points
    assert result.matrix.shape == (4, _DIMS)


async def test_no_sampling_below_threshold() -> None:
    vs = _vs(chunks=[_chunk_record(i) for i in range(3)])
    store = _FakeStore({})

    result = await fetch_projection_vectors(vs, store, "kb-1", sample_size=5)

    assert result.sampled is False
    assert result.total_points == 3
    assert len(result.points) == 3
    assert len(vs.retrieve_calls[0]) == 3


async def test_subsamples_chunks_above_threshold_id_first() -> None:
    vs = _vs(chunks=[_chunk_record(i) for i in range(20)])
    store = _FakeStore({})

    rng = np.random.default_rng(42)
    result = await fetch_projection_vectors(vs, store, "kb-1", sample_size=5, rng=rng)

    assert result.sampled is True
    assert result.total_points == 20
    assert len(result.points) == 5
    # retrieve only asked for the chosen subset (not all 20)
    assert len(vs.retrieve_calls[0]) == 5
    # same seed → identical subset (deterministic for tests & cache keys)
    rng2 = np.random.default_rng(42)
    again = await fetch_projection_vectors(vs, store, "kb-1", sample_size=5, rng=rng2)
    assert [p.id for p in again.points] == [p.id for p in result.points]


async def test_only_chunks_are_sampled() -> None:
    vs = _vs(
        chunks=[_chunk_record(i) for i in range(3)],
        entities=[(f"pt-e{i}", {"kb_id": "kb-1", "name": f"实体{i}", "type": "概念", "description": ""}, _vec(i + 10)) for i in range(20)],
    )
    store = _FakeStore({})

    result = await fetch_projection_vectors(vs, store, "kb-1", sample_size=5)

    assert result.sampled is False  # entities overflow does not count as sampling
    assert len([p for p in result.points if p.source_type == "entity"]) == 20


async def test_chunk_preview_truncates_long_text() -> None:
    vs = _vs(chunks=[_chunk_record(0)])
    store = _FakeStore({"doc-1#0000": {"chunk_id": "doc-1#0000", "text": "字" * 200, "heading_path": []}})

    result = await fetch_projection_vectors(vs, store, "kb-1")

    assert len(result.points[0].preview) == 120


async def test_chunk_preview_falls_back_to_doc_name_when_db_row_missing() -> None:
    vs = _vs(chunks=[_chunk_record(0)])
    store = _FakeStore({})  # no DB row for the chunk

    result = await fetch_projection_vectors(vs, store, "kb-1")

    assert result.points[0].preview == "doc-1.pdf"


async def test_missing_vectors_are_dropped_but_alignment_holds() -> None:
    vs = _vs(chunks=[_chunk_record(0), _chunk_record(1), _chunk_record(2)])
    # Simulate a point deleted between scroll and retrieve.
    vs.drop_on_retrieve.add("pt-doc-1#0001")
    store = _FakeStore({})

    result = await fetch_projection_vectors(vs, store, "kb-1")

    assert result.total_points == 3  # scroll saw three
    assert len(result.points) == 2  # one vanished before retrieve
    assert result.matrix.shape == (2, _DIMS)
    # every surviving point still has its own vector row
    for point, row in zip(result.points, result.matrix, strict=True):
        expected_seed = int(point.id.split("#")[1]) + 1
        assert row[0] == pytest.approx(expected_seed)


async def test_empty_kb_returns_empty() -> None:
    result = await fetch_projection_vectors(_vs(), _FakeStore({}), "kb-1")

    assert result.points == ()
    assert result.total_points == 0
    assert result.sampled is False
    assert result.matrix.size == 0


async def test_collection_selection_limits_fetching() -> None:
    vs = _vs(
        chunks=[_chunk_record(0)],
        wiki=[("pt-w1", {"kb_id": "kb-1", "entry_id": "entry-1", "title": "JVM"}, _vec(11))],
    )
    store = _FakeStore({})

    result = await fetch_projection_vectors(vs, store, "kb-1", collections=("wiki",))

    assert vs.scrolled == ["c_wiki"]
    assert [p.source_type for p in result.points] == ["wiki"]
    assert result.total_points == 1


async def test_sample_size_hard_cap() -> None:
    vs = _vs(chunks=[_chunk_record(i) for i in range(10_001)])
    store = _FakeStore({})

    result = await fetch_projection_vectors(vs, store, "kb-1", sample_size=99_999)

    assert result.total_points == 10_001
    assert len(result.points) == 10_000  # capped at MAX_SAMPLE_SIZE
    assert result.sampled is True


async def test_unknown_collection_rejected() -> None:
    with pytest.raises(ValueError, match="collection"):
        await fetch_projection_vectors(_vs(), _FakeStore({}), "kb-1", collections=("bogus",))
