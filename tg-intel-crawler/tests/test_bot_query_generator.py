"""Tests for QueryGenerator — build bot-search queries from keywords.yaml."""

import pytest

from tg_intel_crawler.collector.bot_query_generator import QueryGenerator


@pytest.fixture
def keywords_file(tmp_path):
    p = tmp_path / "keywords.yaml"
    p.write_text(
        "products:\n"
        "  - 抖音\n"
        "  - 字节\n"
        "actions:\n"
        "  - 买号\n"
        "  - 刷粉\n",
        encoding="utf-8",
    )
    return str(p)


def test_default_generates_product_action_pairs(keywords_file):
    gen = QueryGenerator(keywords_file)
    queries = gen.generate(max_queries=100)
    # 2 products × 2 actions = 4 queries
    assert set(queries) == {"抖音 买号", "抖音 刷粉", "字节 买号", "字节 刷粉"}


def test_max_queries_truncates(keywords_file):
    gen = QueryGenerator(keywords_file)
    queries = gen.generate(max_queries=2)
    assert len(queries) == 2
    # Must remain a subset of all valid pairs.
    full = set(gen.generate(max_queries=100))
    assert all(q in full for q in queries)


def test_explicit_keywords_override_matrix(keywords_file):
    gen = QueryGenerator(keywords_file)
    queries = gen.generate(max_queries=100, override_keywords=["foo", "bar"])
    assert queries == ["foo", "bar"]


def test_override_also_respects_max(keywords_file):
    gen = QueryGenerator(keywords_file)
    queries = gen.generate(max_queries=1, override_keywords=["a", "b", "c"])
    assert queries == ["a"]


def test_empty_products_or_actions_yields_no_queries(tmp_path):
    p = tmp_path / "kw.yaml"
    p.write_text("products: []\nactions: ['x']\n", encoding="utf-8")
    assert QueryGenerator(str(p)).generate(max_queries=10) == []


def test_skips_blank_keyword_entries(tmp_path):
    p = tmp_path / "kw.yaml"
    p.write_text(
        "products:\n  - 抖音\n  - ''\nactions:\n  - 买号\n  - '   '\n",
        encoding="utf-8",
    )
    queries = QueryGenerator(str(p)).generate(max_queries=10)
    assert queries == ["抖音 买号"]


def test_dedupes_identical_overrides(keywords_file):
    gen = QueryGenerator(keywords_file)
    queries = gen.generate(max_queries=10, override_keywords=["foo", "foo", "bar"])
    assert queries == ["foo", "bar"]
