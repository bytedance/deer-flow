# tests/test_intel_stats.py
import json

from tg_intel_crawler.storage.intel_stats import IntelStatsAggregator


def test_missing_dir_returns_empty_scores(tmp_path):
    agg = IntelStatsAggregator(str(tmp_path / "filtered_does_not_exist"))
    assert agg.score_for("any_group") == {"high": 0, "medium": 0, "total_msgs": 0}


def test_empty_dir_returns_empty_scores(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("any_group") == {"high": 0, "medium": 0, "total_msgs": 0}


def _write_intel(filt, name, records):
    (filt / name).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_aggregates_within_one_file(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"source_group": "卖号群", "risk_level": "high"},
        {"source_group": "卖号群", "risk_level": "high"},
        {"source_group": "卖号群", "risk_level": "medium"},
        {"source_group": "卖号群", "risk_level": "low"},
        {"source_group": "其他群", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("卖号群") == {"high": 2, "medium": 1, "total_msgs": 4}
    assert agg.score_for("其他群") == {"high": 1, "medium": 0, "total_msgs": 1}


def test_aggregates_across_multiple_files(tmp_path):
    """intel_2026-06-05.json + intel_2026-06-06.json + intel_twitter_*.json all merge."""
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"source_group": "g", "risk_level": "high"},
    ])
    _write_intel(filt, "intel_2026-06-06.json", [
        {"source_group": "g", "risk_level": "medium"},
    ])
    _write_intel(filt, "intel_twitter_2026-06-05.json", [
        {"source_group": "g", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("g") == {"high": 2, "medium": 1, "total_msgs": 3}


def test_skips_records_with_missing_source_group(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"risk_level": "high"},  # no source_group → skip
        {"source_group": "g", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("g") == {"high": 1, "medium": 0, "total_msgs": 1}
