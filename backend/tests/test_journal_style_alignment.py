"""Tests for journal-specific style alignment few-shot builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.config.journal_style_config import JournalStyleConfig
from src.research_writing.journal_style import build_journal_style_bundle


def _fake_openalex_response(url: str, **_kwargs) -> dict:
    if "/sources" in url:
        return {
            "results": [
                {
                    "id": "https://openalex.org/S137773608",
                    "display_name": "Nature",
                    "works_count": 300000,
                }
            ]
        }
    if "/works" in url:
        return {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "title": "Mechanistic insights into adaptive systems",
                    "publication_year": 2024,
                    "cited_by_count": 520,
                    "doi": "https://doi.org/10.1000/nature.1",
                    "abstract_inverted_index": {
                        "We": [0],
                        "report": [1],
                        "a": [2, 9],
                        "compact": [3],
                        "story-driven": [4],
                        "framework.": [5],
                        "This": [6],
                        "study": [7],
                        "provides": [8],
                        "high-impact": [10],
                        "narrative.": [11],
                    },
                },
                {
                    "id": "https://openalex.org/W2",
                    "title": "Precision evidence synthesis in life sciences",
                    "publication_year": 2023,
                    "cited_by_count": 410,
                    "doi": "https://doi.org/10.1000/nature.2",
                    "abstract_inverted_index": {
                        "Here": [0],
                        "we": [1],
                        "demonstrate": [2],
                        "structured": [3],
                        "argument": [4],
                        "rhythm.": [5],
                    },
                },
            ]
        }
    raise AssertionError(f"unexpected URL: {url}")


def test_build_journal_style_bundle_with_cache(tmp_path: Path):
    cache_path = tmp_path / "style-cache" / "nature.json"
    config = JournalStyleConfig(enabled=True, sample_size=2, recent_year_window=5, cache_ttl_hours=24)

    with patch("src.research_writing.journal_style._http_get_json", side_effect=_fake_openalex_response):
        payload = build_journal_style_bundle(
            venue_name="Nature",
            cache_path=cache_path,
            force_refresh=True,
            config=config,
        )

    assert payload is not None
    assert payload["resolved_journal_name"] == "Nature"
    assert payload["sample_size"] == 2
    assert payload["cache_hit"] is False
    assert len(payload["few_shot_samples"]) == 2
    assert "Few-shot style exemplars" in payload["prompt_material"]
    assert cache_path.exists()

    with patch("src.research_writing.journal_style._http_get_json", side_effect=AssertionError("should use cache")):
        cached_payload = build_journal_style_bundle(
            venue_name="Nature",
            cache_path=cache_path,
            force_refresh=False,
            config=config,
        )

    assert cached_payload is not None
    assert cached_payload["cache_hit"] is True
    assert cached_payload["sample_size"] == 2
