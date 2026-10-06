"""Collection naming and generation hand-off (spec 2026-09-26 D1 乙 / D5-2).

The width became a deployment setting, and the collection names have to say which width
they were built at — otherwise a migration would overwrite the old vectors in place, and
the "build the new generation first, switch only when it is complete" contract (D5-2)
would have nothing to build *into*.

Two rules are load-bearing here:

1. **The default width keeps the names every deployment already has.** ``kb_chunks`` and
   friends were created by every install before this spec and their vectors are the whole
   library; a suffix on 1024 would make them invisible (an untouched deployment must be
   byte-for-byte unchanged, spec §4 验收 6).
2. **A new generation is never created silently while the old one still holds vectors.**
   The empty new collection would answer every query with nothing, which reads as "the
   library was wiped" — so the store refuses and hands the situation to the migration.

Nothing here talks to Qdrant: the client is a local double, so the tests run everywhere
(the Qdrant-backed read/write paths live in ``test_vector_store.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.knowledge.vector_store import DimensionMigrationRequired, KnowledgeVectorStore

LEGACY_NAMES = ("kb_chunks", "kb_entities", "kb_wiki_entries", "kb_manual_cards")


class _FakeQdrant:
    """Just enough of ``AsyncQdrantClient`` to watch what the store decides."""

    def __init__(self, sizes: dict[str, int] | None = None) -> None:
        self.sizes = dict(sizes or {})
        self.created: list[tuple[str, int]] = []
        self.indexes: list[tuple[str, str]] = []

    async def collection_exists(self, name: str) -> bool:
        return name in self.sizes

    async def get_collection(self, name: str):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=self.sizes[name])})))

    async def create_collection(self, *, collection_name: str, vectors_config: dict, sparse_vectors_config: dict) -> None:
        self.created.append((collection_name, vectors_config["dense"].size))
        self.sizes[collection_name] = vectors_config["dense"].size

    async def create_payload_index(self, collection_name: str, field_name: str, field_schema) -> None:
        self.indexes.append((collection_name, field_name))


def _store(client: _FakeQdrant, *, dense_size: int) -> KnowledgeVectorStore:
    return KnowledgeVectorStore(client=client, collection_prefix="kb", dense_size=dense_size)


def test_the_default_width_keeps_the_names_every_deployment_already_has():
    client = _FakeQdrant()
    store = _store(client, dense_size=1024)

    assert store.collection_names == LEGACY_NAMES


def test_a_declared_width_carries_the_suffix():
    client = _FakeQdrant()
    store = _store(client, dense_size=1536)

    assert store.collection_names == ("kb_chunks_1536", "kb_entities_1536", "kb_wiki_entries_1536", "kb_manual_cards_1536")


@pytest.mark.asyncio
async def test_init_creates_the_new_generation_at_the_declared_width():
    client = _FakeQdrant()
    store = _store(client, dense_size=1536)

    await store.init_collections()

    assert client.created == [("kb_chunks_1536", 1536), ("kb_entities_1536", 1536), ("kb_wiki_entries_1536", 1536), ("kb_manual_cards_1536", 1536)]
    assert {name for name, _ in client.indexes} == {f"kb_{kind}_1536" for kind in ("chunks", "entities", "wiki_entries", "manual_cards")}


@pytest.mark.asyncio
async def test_init_refuses_to_create_an_empty_generation_while_the_old_one_still_holds_vectors():
    """The whole library lives in the 1024 collections; a silent new one would read as "wiped"."""
    client = _FakeQdrant({"kb_chunks": 1024, "kb_entities": 1024, "kb_wiki_entries": 1024, "kb_manual_cards": 1024})
    store = _store(client, dense_size=1536)

    with pytest.raises(DimensionMigrationRequired) as excinfo:
        await store.init_collections()

    assert client.created == [], "拒绝之后一个空集合都不许建"
    message = str(excinfo.value)
    assert "1536" in message and "1024" in message
    assert "迁移" in message or "重建" in message, "要说清出路，而不是只说不行"


@pytest.mark.asyncio
async def test_init_creates_a_fresh_generation_when_no_other_one_exists():
    """A deployment born at a non-default width has nothing to migrate — it just creates."""
    client = _FakeQdrant()
    store = _store(client, dense_size=768)

    await store.init_collections()

    assert client.created == [(f"kb_{kind}_768", 768) for kind in ("chunks", "entities", "wiki_entries", "manual_cards")]


@pytest.mark.asyncio
async def test_create_collections_is_the_migration_entry_and_skips_the_hand_off():
    """The migration *is* the answer to the refusal above, so it must be able to build into it."""
    client = _FakeQdrant({"kb_chunks": 1024, "kb_entities": 1024, "kb_wiki_entries": 1024, "kb_manual_cards": 1024})
    store = _store(client, dense_size=1536)

    await store.create_collections()

    assert client.created == [(f"kb_{kind}_1536", 1536) for kind in ("chunks", "entities", "wiki_entries", "manual_cards")]
    assert client.sizes["kb_chunks"] == 1024, "旧的一代原样留着，删除是迁移最后一步的事"
