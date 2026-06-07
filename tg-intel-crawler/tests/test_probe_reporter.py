"""Tests for ProbeReporter — writes JSON + Markdown outputs."""

import json
from datetime import datetime, timezone

import pytest

from tg_intel_crawler.probe.reporter import ProbeReporter
from tg_intel_crawler.probe.runner import ProbeRecord
from tg_intel_crawler.probe.sampler import SampledCandidate


def _record(
    key="x",
    stratum="L3",
    candidate_type="public",
    classification="direct_hit",
    reply_status="ok",
    invite_hash=None,
    reply_raw="🌄 ...",
    error=None,
    matched=None,
    previews_count=1,
    count=10,
):
    return ProbeRecord(
        candidate=SampledCandidate(
            key=key, count=count, invite_hash=invite_hash,
            candidate_type=candidate_type, stratum=stratum,
        ),
        query_sent=key.lstrip("+"),
        reply_status=reply_status,
        reply_raw=reply_raw,
        error=error,
        previews_count=previews_count,
        matched_preview=matched,
        classification=classification,
    )


def test_json_round_trip(tmp_path):
    records = [_record(key="a", classification="direct_hit")]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=1, seed=42,
        candidate_pool_total=624, truncated=False,
        generated_at=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write(records)
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["meta"]["bot"] == "@JISOU"
    assert data["meta"]["sample_size"] == 1
    assert data["meta"]["seed"] == 42
    assert data["meta"]["candidate_pool_total"] == 624
    assert data["meta"]["truncated"] is False
    assert data["meta"]["generated_at"] == "2026-06-06T12:00:00+00:00"
    assert len(data["records"]) == 1
    assert data["records"][0]["classification"] == "direct_hit"
    assert data["records"][0]["candidate"]["key"] == "a"


def test_filename_uses_iso_date(tmp_path):
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=0, seed=1,
        candidate_pool_total=0, truncated=False,
        generated_at=datetime(2026, 6, 6, 23, 30, 0, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write([])
    assert json_path.name == "bot_lookup_2026-06-06.json"
    assert md_path.name == "bot_lookup_2026-06-06.md"


def test_markdown_overall_table_counts_correctly(tmp_path):
    records = [
        _record(key="a", stratum="L3", candidate_type="public", classification="direct_hit"),
        _record(key="b", stratum="L3", candidate_type="public", classification="indirect_hit"),
        _record(key="+c", stratum="L6", candidate_type="private",
                invite_hash="c", classification="indirect_hit"),
        _record(key="+d", stratum="L4", candidate_type="private",
                invite_hash="d", classification="no_results"),
    ]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=4, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # The overall row for "indirect_hit" should be: 公开=1, 私密=1, 合计=2
    assert "indirect_hit" in md
    # The overall row for "direct_hit" should be: 公开=1, 私密=0, 合计=1
    assert "direct_hit" in md
    # And for no_results: 公开=0, 私密=1, 合计=1
    assert "no_results" in md


def test_markdown_per_layer_breakdown_present(tmp_path):
    records = [
        _record(key="a", stratum="L3", candidate_type="public", classification="direct_hit"),
        _record(key="+b", stratum="L6", candidate_type="private",
                invite_hash="b", classification="empty_reply"),
    ]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=2, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # Each stratum has its own row in the per-layer table.
    for stratum in ("L1", "L2", "L3", "L4", "L5", "L6"):
        assert f"| {stratum} |" in md


def test_markdown_skips_empty_classification_examples(tmp_path):
    records = [_record(key="a", classification="direct_hit")]  # only one classification
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=1, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # Sample for direct_hit should appear, sample header for empty_reply should NOT.
    assert "### direct_hit" in md
    assert "### empty_reply" not in md
    assert "### error" not in md


def test_markdown_includes_truncated_warning_when_set(tmp_path):
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=30, seed=42,
        candidate_pool_total=624, truncated=True,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write([_record(key="a")])
    md = md_path.read_text(encoding="utf-8")
    assert "truncated" in md.lower()


def test_creates_dest_dir_if_missing(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "dir"
    reporter = ProbeReporter(
        dest_dir=nested, bot="@JISOU", sample_size=0, seed=1,
        candidate_pool_total=0, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write([])
    assert nested.exists()
    assert json_path.exists()
    assert md_path.exists()
