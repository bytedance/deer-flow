"""Tests for citation memory persistence."""

import tempfile
from pathlib import Path

from src.agents.memory.citation_memory import (
    format_for_injection,
    get_citation_count,
    get_citations_by_tag,
    load_citations,
    remove_citation,
    save_citation,
    search_citations,
)


def _make_tmp_store() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    Path(f.name).unlink()
    return f.name


def test_load_empty_store():
    store = load_citations("/nonexistent/path.json")
    assert store == {"citations": {}, "tags": {}}


def test_save_and_load_citation():
    path = _make_tmp_store()
    try:
        save_citation(
            "vaswani2017",
            {"title": "Attention Is All You Need", "year": 2017, "venue": "NeurIPS"},
            store_path=path,
        )
        store = load_citations(path)
        assert "vaswani2017" in store["citations"]
        assert store["citations"]["vaswani2017"]["year"] == 2017
        assert store["citations"]["vaswani2017"]["title"] == "Attention Is All You Need"
    finally:
        Path(path).unlink(missing_ok=True)


def test_save_citation_with_tags():
    path = _make_tmp_store()
    try:
        save_citation(
            "devlin2019bert",
            {"title": "BERT", "year": 2019},
            tags=["nlp", "transformers"],
            store_path=path,
        )
        store = load_citations(path)
        assert "nlp" in store["tags"]
        assert "devlin2019bert" in store["tags"]["nlp"]
        assert "devlin2019bert" in store["tags"]["transformers"]
    finally:
        Path(path).unlink(missing_ok=True)


def test_save_multiple_citations():
    path = _make_tmp_store()
    try:
        save_citation("paper1", {"title": "Paper 1", "year": 2020}, store_path=path)
        save_citation("paper2", {"title": "Paper 2", "year": 2021}, store_path=path)
        store = load_citations(path)
        assert len(store["citations"]) == 2
    finally:
        Path(path).unlink(missing_ok=True)


def test_remove_citation():
    path = _make_tmp_store()
    try:
        save_citation("to_remove", {"title": "Remove Me"}, tags=["test"], store_path=path)
        assert remove_citation("to_remove", store_path=path) is True
        store = load_citations(path)
        assert "to_remove" not in store["citations"]
        assert "to_remove" not in store["tags"].get("test", [])
    finally:
        Path(path).unlink(missing_ok=True)


def test_remove_nonexistent_citation():
    path = _make_tmp_store()
    try:
        assert remove_citation("nonexistent", store_path=path) is False
    finally:
        Path(path).unlink(missing_ok=True)


def test_search_citations():
    path = _make_tmp_store()
    try:
        save_citation("vaswani2017", {"title": "Attention Is All You Need", "year": 2017}, store_path=path)
        save_citation("devlin2019", {"title": "BERT: Pre-training", "year": 2019}, store_path=path)
        save_citation("brown2020", {"title": "Language Models are Few-Shot Learners", "year": 2020}, store_path=path)

        results = search_citations("attention", store_path=path)
        assert len(results) == 1
        assert results[0]["cite_key"] == "vaswani2017"

        results = search_citations("BERT", store_path=path)
        assert len(results) == 1

        results = search_citations("2020", store_path=path)
        assert len(results) == 1
        assert results[0]["cite_key"] == "brown2020"
    finally:
        Path(path).unlink(missing_ok=True)


def test_search_citations_case_insensitive():
    path = _make_tmp_store()
    try:
        save_citation("test1", {"title": "Transformer Architecture"}, store_path=path)
        results = search_citations("transformer", store_path=path)
        assert len(results) == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_get_citations_by_tag():
    path = _make_tmp_store()
    try:
        save_citation("p1", {"title": "NLP Paper"}, tags=["nlp"], store_path=path)
        save_citation("p2", {"title": "CV Paper"}, tags=["cv"], store_path=path)
        save_citation("p3", {"title": "Both Paper"}, tags=["nlp", "cv"], store_path=path)

        nlp_papers = get_citations_by_tag("nlp", store_path=path)
        assert len(nlp_papers) == 2
        keys = {p["cite_key"] for p in nlp_papers}
        assert keys == {"p1", "p3"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_format_for_injection_empty():
    result = format_for_injection(store_path="/nonexistent/path.json")
    assert result == ""


def test_format_for_injection_with_citations():
    path = _make_tmp_store()
    try:
        save_citation("vaswani2017", {"title": "Attention Is All You Need", "year": 2017}, store_path=path)
        save_citation("devlin2019", {"title": "BERT", "year": 2019}, store_path=path)

        result = format_for_injection(store_path=path)
        assert "<citation_library>" in result
        assert "vaswani2017" in result
        assert "Attention Is All You Need" in result
        assert "2017" in result
    finally:
        Path(path).unlink(missing_ok=True)


def test_format_for_injection_respects_max_entries():
    path = _make_tmp_store()
    try:
        for i in range(10):
            save_citation(f"paper{i}", {"title": f"Paper {i}", "year": 2020 + i}, store_path=path)

        result = format_for_injection(store_path=path, max_entries=3)
        assert result.count("paper") == 3
    finally:
        Path(path).unlink(missing_ok=True)


def test_get_citation_count():
    path = _make_tmp_store()
    try:
        assert get_citation_count(store_path=path) == 0
        save_citation("p1", {"title": "Paper 1"}, store_path=path)
        save_citation("p2", {"title": "Paper 2"}, store_path=path)
        assert get_citation_count(store_path=path) == 2
    finally:
        Path(path).unlink(missing_ok=True)
