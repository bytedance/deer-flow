import json
import csv
import pytest
from pathlib import Path
from datetime import datetime

from tg_intel_crawler.storage.exporter import Exporter, IntelRecord


@pytest.fixture
def exporter(tmp_path):
    return Exporter(output_dir=str(tmp_path), formats=["json", "csv"])


@pytest.fixture
def sample_record():
    return IntelRecord(
        id="msg_123",
        source_group="test_group",
        date=datetime(2026, 5, 24, 14, 30, 0),
        original_text="抖音账号出售50元一个",
        risk_type="账号交易",
        risk_level="high",
        entities={
            "accounts": ["dy_xxx"],
            "contacts": ["wx: seller"],
            "links": [],
            "tools": [],
            "prices": ["50元/个"],
        },
        summary="出售抖音实名账号",
        llm_model="ep-test",
    )


def test_export_json(exporter, sample_record, tmp_path):
    """Should write record to JSON file with correct structure."""
    exporter.export_filtered([sample_record])
    json_files = list((tmp_path / "filtered").glob("*.json"))
    assert len(json_files) == 1
    with open(json_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "msg_123"
    assert data[0]["risk_type"] == "账号交易"


def test_export_csv(exporter, sample_record, tmp_path):
    """Should write record to CSV file with correct columns."""
    exporter.export_filtered([sample_record])
    csv_files = list((tmp_path / "filtered").glob("*.csv"))
    assert len(csv_files) == 1
    with open(csv_files[0], "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["id"] == "msg_123"
    assert rows[0]["risk_type"] == "账号交易"


def test_export_raw(exporter, tmp_path):
    """Should write raw messages to group-specific JSON file."""
    raw_messages = [
        {"msg_id": 1, "group_name": "test_group", "text": "hello", "date": "2026-05-24T14:30:00"},
        {"msg_id": 2, "group_name": "test_group", "text": "world", "date": "2026-05-24T14:31:00"},
    ]
    exporter.export_raw(raw_messages, group_name="test_group")
    raw_files = list((tmp_path / "raw").glob("*.json"))
    assert len(raw_files) == 1
    with open(raw_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2


def test_export_empty_records(exporter, tmp_path):
    """Should not create files for empty record list."""
    exporter.export_filtered([])
    json_files = list((tmp_path / "filtered").glob("*.json"))
    assert len(json_files) == 0


def test_export_filtered_with_suffix_creates_separate_file(exporter, tmp_path):
    """file_suffix='twitter' should produce intel_twitter_<date>.json, not intel_<date>.json."""
    record = IntelRecord(
        id="tweet_123",
        source_group="抖音 刷粉",
        date=datetime(2026, 5, 24, 14, 30, 0),
        sender_name="Douyin Seller",
        sender_username="douyin_seller",
        original_text="抖音账号出售",
        risk_type="账号交易",
        risk_level="high",
        summary="出售抖音账号",
        llm_model="ep-test",
        source_platform="twitter",
        source_url="https://twitter.com/douyin_seller/status/123",
    )
    exporter.export_filtered([record], file_suffix="twitter")

    json_files = sorted((tmp_path / "filtered").glob("*.json"))
    assert len(json_files) == 1
    assert "intel_twitter_" in json_files[0].name

    with open(json_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["source_platform"] == "twitter"
    assert data[0]["source_url"].endswith("/status/123")


def test_export_raw_with_subdir(exporter, tmp_path):
    """subdir='twitter' should write under raw/twitter/."""
    raw = [{"tweet_id": "1", "text": "hello"}]
    exporter.export_raw(raw, group_name="search_kw", subdir="twitter")
    files = list((tmp_path / "raw" / "twitter").glob("*.json"))
    assert len(files) == 1
    assert "search_kw" in files[0].name


def test_intel_record_default_platform_is_telegram(sample_record):
    """Existing call sites that don't pass source_platform stay on telegram."""
    assert sample_record.source_platform == "telegram"
    assert sample_record.source_url == ""
