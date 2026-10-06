"""代次回收（spec 2026-10-05 D6）用例。

pin 住的契约：
- ``sweep_generations(*, vector_store, declared_width) -> GenerationReport``
- 严格匹配本部署四集合的家族名（前缀 + 四种 kind + 可选 ``_数字`` 后缀）；
  名字 ≠ 声明宽度代 的即残留代，整集合删、逐个吞错。
- 两道前置：声明代四个集合**全部在位**才动手（防"手改宽度没走迁移"误删唯一副本）。
"""

from __future__ import annotations

from deerflow.knowledge.sweep import sweep_generations

DECLARED = ["kb_chunks", "kb_entities", "kb_wiki_entries", "kb_manual_cards"]
LEFTOVERS = ["kb_chunks_1000", "kb_entities_1000", "kb_wiki_entries_1000", "kb_manual_cards_1000"]
UNRELATED = ["other_collection", "kb_extra", "kb_chunks_1000x", "kb_chunks_backup"]


class FakeGenerationStore:
    collection_prefix = "kb"

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        self.raised: set[str] = set()
        self.absent: set[str] = set()
        self.calls: list[str] = []

    def names_at_width(self, width: int) -> tuple[str, ...]:
        suffix = "" if width == 1024 else f"_{width}"
        return tuple(f"kb_{kind}{suffix}" for kind in ("chunks", "entities", "wiki_entries", "manual_cards"))

    async def list_all_collections(self) -> list[str]:
        return sorted(self.names)

    async def drop_collection(self, name: str) -> bool:
        self.calls.append(name)
        if name in self.absent:
            return False
        if name in self.raised:
            raise RuntimeError("qdrant down (test)")
        self.names.remove(name)
        return True


async def test_leftover_generations_dropped_declared_and_unrelated_kept():
    store = FakeGenerationStore(DECLARED + LEFTOVERS + UNRELATED)

    report = await sweep_generations(vector_store=store, declared_width=1024)

    assert report.dropped == sorted(LEFTOVERS)
    assert report.failed == []
    assert report.skipped is None
    assert store.names == DECLARED + UNRELATED


async def test_gc_skipped_when_declared_generation_incomplete():
    """手改宽度没走迁移：声明代缺一个 ⇒ 旧代是唯一副本，GC 必须停手。"""
    store = FakeGenerationStore([n for n in DECLARED if n != "kb_manual_cards"] + LEFTOVERS)

    report = await sweep_generations(vector_store=store, declared_width=1024)

    assert report.dropped == []
    assert report.skipped is not None
    assert store.calls == []


async def test_drop_failure_recorded_and_others_continue():
    store = FakeGenerationStore(DECLARED + LEFTOVERS)
    store.raised.add("kb_chunks_1000")

    report = await sweep_generations(vector_store=store, declared_width=1024)

    assert report.failed == ["kb_chunks_1000"]
    assert "kb_chunks_1000" in store.names
    assert "kb_entities_1000" not in store.names


async def test_already_absent_collection_is_a_noop():
    """并发删竞态：存在检查与删除之间被别人删了 ⇒ 不算 dropped、不算 failed。"""
    store = FakeGenerationStore(DECLARED + LEFTOVERS)
    store.absent.add("kb_wiki_entries_1000")

    report = await sweep_generations(vector_store=store, declared_width=1024)

    assert "kb_wiki_entries_1000" not in report.dropped
    assert "kb_wiki_entries_1000" not in report.failed
    assert sorted(report.dropped) == ["kb_chunks_1000", "kb_entities_1000", "kb_manual_cards_1000"]


async def test_default_width_leftover_dropped_when_declared_is_non_default():
    store = FakeGenerationStore(["kb_chunks_1536", "kb_entities_1536", "kb_wiki_entries_1536", "kb_manual_cards_1536", *DECLARED])

    report = await sweep_generations(vector_store=store, declared_width=1536)

    assert sorted(report.dropped) == sorted(DECLARED)
    assert "kb_chunks_1536" in store.names
