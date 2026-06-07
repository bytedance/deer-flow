# tests/test_raw_lookup.py
import json
from pathlib import Path

import pytest

from tg_intel_crawler.storage.raw_lookup import RawMessageLookup


def test_missing_dir_returns_empty_lookup(tmp_path):
    """Missing raw/ dir is not an error — every lookup just misses."""
    lookup = RawMessageLookup(str(tmp_path / "does_not_exist"))
    assert lookup.get("any_group", 123) is None
    assert lookup.size() == 0


def test_empty_dir_returns_empty_lookup(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.get("any_group", 123) is None


def _write_raw(raw_dir, date_str, group_name, records):
    path = raw_dir / f"{date_str}_{group_name}.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_index_finds_message_in_single_file(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "group_a", [
        {"msg_id": 100, "group_name": "group_a", "text": "卖抖音号 联系 @x"},
        {"msg_id": 101, "group_name": "group_a", "text": "今天天气好"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 2
    assert lookup.get("group_a", 100) == "卖抖音号 联系 @x"
    assert lookup.get("group_a", 999) is None


def test_index_merges_across_dates(tmp_path):
    """Same group across multiple date files all get indexed."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "g", [
        {"msg_id": 1, "group_name": "g", "text": "t1"},
    ])
    _write_raw(raw_dir, "2026-06-06", "g", [
        {"msg_id": 2, "group_name": "g", "text": "t2"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 2
    assert lookup.get("g", 1) == "t1"
    assert lookup.get("g", 2) == "t2"


def test_index_skips_malformed_files(tmp_path):
    """A broken JSON file shouldn't kill the whole index."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "2026-06-05_broken.json").write_text("{not json", encoding="utf-8")
    _write_raw(raw_dir, "2026-06-05", "good", [
        {"msg_id": 1, "group_name": "good", "text": "ok"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.get("good", 1) == "ok"


def test_index_skips_records_without_required_fields(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "g", [
        {"text": "no msg_id"},
        {"msg_id": 1, "text": "no group"},
        {"msg_id": 2, "group_name": "g", "text": "valid"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 1
    assert lookup.get("g", 2) == "valid"
