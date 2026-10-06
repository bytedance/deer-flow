"""Tests for the golden retrieval-evaluation dataset (spec 2026-08-23 §5).

Pure validation coverage of the golden JSONL contract: schema fields, enum
values, ``<doc_id>#NNNN`` chunk-id format, duplicate ids, and a guard test
that loads the real checked-in ``golden.jsonl`` so dirty questions can never
silently pollute the metrics. No IO beyond tmp_path / the repo fixture file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.knowledge.eval.dataset import (
    GoldenDatasetError,
    GoldenQuestion,
    load_golden,
    validate_question,
)

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "rag_eval" / "golden.jsonl"

VALID_RAW = {
    "id": "q001",
    "query": "String、StringBuffer 和 StringBuilder 有什么区别？",
    "expected_path": "vector",
    "relevant_chunk_ids": ["e1b9e365f63747958337431dc755c620#0007"],
    "relevant_entities": ["StringBuffer", "StringBuilder"],
    "reference_answer": "String 不可变；StringBuffer 可变且线程安全；StringBuilder 可变但非线程安全。",
    "category": "fact",
}


def _raw(**overrides) -> dict:
    raw = dict(VALID_RAW)
    raw.update(overrides)
    return raw


class TestValidateQuestion:
    def test_valid_full(self):
        q = validate_question(VALID_RAW)

        assert isinstance(q, GoldenQuestion)
        assert q.id == "q001"
        assert q.expected_paths == ("vector",)
        assert q.relevant_chunk_ids == ("e1b9e365f63747958337431dc755c620#0007",)
        assert q.relevant_entities == ("StringBuffer", "StringBuilder")
        assert q.category == "fact"
        assert q.reference_answer is not None

    def test_valid_minimal_without_reference_answer(self):
        raw = _raw()
        del raw["reference_answer"]

        q = validate_question(raw)

        assert q.reference_answer is None

    @pytest.mark.parametrize(
        "field",
        ["id", "query", "expected_path", "relevant_chunk_ids", "relevant_entities", "category"],
    )
    def test_rejects_missing_required_field(self, field: str):
        raw = _raw()
        del raw[field]

        with pytest.raises(GoldenDatasetError, match=field):
            validate_question(raw)

    def test_rejects_unknown_field(self):
        with pytest.raises(GoldenDatasetError, match="categroy"):
            validate_question(_raw(categroy="fact"))

    @pytest.mark.parametrize("category", ["facts", "", "GLOBAL", None, 1])
    def test_rejects_invalid_category(self, category):
        with pytest.raises(GoldenDatasetError, match="category"):
            validate_question(_raw(category=category))

    @pytest.mark.parametrize("path", ["vectors", "", "GRAPH", None, 1])
    def test_rejects_invalid_expected_path(self, path):
        with pytest.raises(GoldenDatasetError, match="expected_path"):
            validate_question(_raw(expected_path=path))

    # ── expected_paths 多路集合（spec 2026-08-28 §3）──────────────────

    def test_accepts_expected_paths_list(self):
        raw = _raw()
        del raw["expected_path"]
        raw["expected_paths"] = ["vector", "graph"]

        q = validate_question(raw)

        assert q.expected_paths == ("vector", "graph")
        # 首路读取在 Task 3 后无兼容属性——断言全量集合即可。

    def test_normalizes_legacy_single_expected_path(self):
        q = validate_question(VALID_RAW)

        assert q.expected_paths == ("vector",)

    def test_expected_paths_dedupes_preserving_order(self):
        raw = _raw()
        del raw["expected_path"]
        raw["expected_paths"] = ["graph", "vector", "graph"]

        assert validate_question(raw).expected_paths == ("graph", "vector")

    def test_rejects_both_expected_path_keys(self):
        raw = _raw(expected_paths=["vector"])

        with pytest.raises(GoldenDatasetError) as exc_info:
            validate_question(raw)

        message = str(exc_info.value)
        assert "expected_path" in message and "expected_paths" in message

    def test_rejects_missing_both_expected_path_keys(self):
        raw = _raw()
        del raw["expected_path"]

        with pytest.raises(GoldenDatasetError, match="expected_path"):
            validate_question(raw)

    @pytest.mark.parametrize("paths", [[], ["vectors"], ["vector", 1], "vector", None])
    def test_rejects_invalid_expected_paths(self, paths):
        raw = _raw()
        del raw["expected_path"]
        raw["expected_paths"] = paths

        with pytest.raises(GoldenDatasetError, match="expected_paths"):
            validate_question(raw)

    @pytest.mark.parametrize(
        "chunk_id",
        [
            "no-hash-separator",
            "e1b9e365f63747958337431dc755c620",  # missing #NNNN
            "e1b9e365f63747958337431dc755c620#007",  # 3 digits
            "E1B9E365F63747958337431DC755C620#0007",  # uppercase doc id
            "e1b9e365f63747958337431dc755c62#0007",  # 31-char doc id
            "e1b9e365f63747958337431dc755c620#00007",  # 5 digits
        ],
    )
    def test_rejects_malformed_chunk_id(self, chunk_id: str):
        with pytest.raises(GoldenDatasetError, match="relevant_chunk_ids"):
            validate_question(_raw(relevant_chunk_ids=[chunk_id]))

    def test_allows_empty_chunk_and_entity_lists(self):
        q = validate_question(_raw(relevant_chunk_ids=[], relevant_entities=[]))

        assert q.relevant_chunk_ids == ()
        assert q.relevant_entities == ()

    @pytest.mark.parametrize("query", ["", "   ", None, 42])
    def test_rejects_blank_or_non_string_query(self, query):
        with pytest.raises(GoldenDatasetError, match="query"):
            validate_question(_raw(query=query))

    def test_rejects_non_list_chunk_ids(self):
        with pytest.raises(GoldenDatasetError, match="relevant_chunk_ids"):
            validate_question(_raw(relevant_chunk_ids="e1b9e365f63747958337431dc755c620#0007"))

    def test_rejects_empty_reference_answer_string(self):
        with pytest.raises(GoldenDatasetError, match="reference_answer"):
            validate_question(_raw(reference_answer=""))

    def test_error_message_includes_source_context(self):
        with pytest.raises(GoldenDatasetError, match="golden.jsonl:3"):
            validate_question(_raw(category="nope"), source="golden.jsonl:3")


class TestLoadGolden:
    def _write(self, tmp_path: Path, lines: list[str]) -> Path:
        path = tmp_path / "golden.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_loads_jsonl_and_skips_blank_lines(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            [
                json.dumps(VALID_RAW, ensure_ascii=False),
                "",
                json.dumps(_raw(id="q002", category="global", relevant_chunk_ids=[], relevant_entities=[], reference_answer=None), ensure_ascii=False),
                "   ",
            ],
        )

        questions = load_golden(path)

        assert [q.id for q in questions] == ["q001", "q002"]
        assert questions[1].reference_answer is None

    def test_rejects_malformed_json_line_with_line_number(self, tmp_path: Path):
        path = self._write(tmp_path, [json.dumps(VALID_RAW, ensure_ascii=False), "{not json"])

        with pytest.raises(GoldenDatasetError, match="line 2"):
            load_golden(path)

    def test_rejects_duplicate_ids(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            [json.dumps(VALID_RAW, ensure_ascii=False), json.dumps(_raw(query="另一个问题"), ensure_ascii=False)],
        )

        with pytest.raises(GoldenDatasetError, match="duplicate"):
            load_golden(path)

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(GoldenDatasetError, match="not found"):
            load_golden(tmp_path / "absent.jsonl")


class TestGoldenFileGuard:
    """The checked-in golden dataset must always stay valid — dirty questions
    silently pollute every metric built on top of them."""

    def test_golden_file_exists_and_is_valid(self):
        questions = load_golden(GOLDEN_PATH)

        assert len(questions) >= 20, "cold-start floor: at least 20 annotated questions"

    def test_golden_covers_all_categories(self):
        questions = load_golden(GOLDEN_PATH)

        assert {q.category for q in questions} == {"fact", "relation", "concept", "global"}

    def test_golden_legacy_single_path_normalizes_to_paths_tuple(self):
        # 存量 fixture 是单值形态（零迁移策略）——加载器必须归一化为集合。
        questions = load_golden(GOLDEN_PATH)

        assert all(len(q.expected_paths) == 1 for q in questions)


class TestMixedFormatFile:
    """存量单值行与新格式多路行可在同一文件长期共存（§9 兼容纪律）。"""

    def test_loads_legacy_and_new_format_lines_together(self, tmp_path: Path):
        legacy = json.dumps(VALID_RAW, ensure_ascii=False)
        modern = json.dumps(_raw(id="q002", query="多路题"), ensure_ascii=False).replace('"expected_path": "vector"', '"expected_paths": ["vector", "graph"]')
        path = tmp_path / "golden.jsonl"
        path.write_text(legacy + "\n" + modern + "\n", encoding="utf-8")

        questions = load_golden(path)

        assert questions[0].expected_paths == ("vector",)
        assert questions[1].expected_paths == ("vector", "graph")
