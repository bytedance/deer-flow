"""Unit tests for token_usage.json cleanup script."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.cleanup_token_usage_json import (
    AuditResult,
    CleanupReport,
    archive_json_file,
    audit_token_usage,
    load_json_usage,
    sum_json_tokens,
    within_tolerance,
)


class TestLoadJsonUsage:
    """Tests for load_json_usage()."""

    def test_load_valid_json(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        data = [
            {"timestamp": "2026-01-01T00:00:00", "total_tokens": 100},
            {"timestamp": "2026-01-02T00:00:00", "total_tokens": 200},
        ]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        records = load_json_usage(json_file)
        assert len(records) == 2
        assert records[0]["total_tokens"] == 100
        assert records[1]["total_tokens"] == 200

    def test_load_nonexistent_file(self, tmp_path: Path):
        json_file = tmp_path / "nonexistent.json"
        records = load_json_usage(json_file)
        assert records == []

    def test_load_empty_file(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        json_file.write_text("", encoding="utf-8")

        records = load_json_usage(json_file)
        assert records == []

    def test_load_invalid_json(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        json_file.write_text("not valid json {", encoding="utf-8")

        records = load_json_usage(json_file)
        assert records == []

    def test_load_non_list_json(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        records = load_json_usage(json_file)
        assert records == []


class TestSumJsonTokens:
    """Tests for sum_json_tokens()."""

    def test_sum_tokens(self):
        records = [
            {"total_tokens": 100},
            {"total_tokens": 200},
            {"total_tokens": 300},
        ]
        assert sum_json_tokens(records) == 600

    def test_sum_empty_records(self):
        assert sum_json_tokens([]) == 0

    def test_sum_missing_field(self):
        records = [
            {"total_tokens": 100},
            {"other_field": 200},
        ]
        assert sum_json_tokens(records) == 100


class TestWithinTolerance:
    """Tests for within_tolerance()."""

    def test_exact_match(self):
        assert within_tolerance(1000, 1000, 1.0) is True

    def test_within_tolerance(self):
        # 0.5% difference
        assert within_tolerance(1000, 1005, 1.0) is True
        assert within_tolerance(1005, 1000, 1.0) is True

    def test_exceeds_tolerance(self):
        # 2% difference
        assert within_tolerance(1000, 1020, 1.0) is False
        assert within_tolerance(1020, 1000, 1.0) is False

    def test_both_zero(self):
        assert within_tolerance(0, 0, 1.0) is True

    def test_one_zero(self):
        assert within_tolerance(0, 100, 1.0) is False
        assert within_tolerance(100, 0, 1.0) is False

    def test_custom_tolerance(self):
        # 5% difference with 10% tolerance
        assert within_tolerance(1000, 1050, 10.0) is True
        # 15% difference with 10% tolerance
        assert within_tolerance(1000, 1150, 10.0) is False


class TestArchiveJsonFile:
    """Tests for archive_json_file()."""

    def test_archive_success(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        json_file.write_text('[]', encoding="utf-8")
        backup_dir = tmp_path / "backups"

        result = archive_json_file(json_file, backup_dir)
        assert result is True
        assert not json_file.exists()
        assert (backup_dir / "token_usage.json.bak").exists()

    def test_archive_creates_backup_dir(self, tmp_path: Path):
        json_file = tmp_path / "token_usage.json"
        json_file.write_text('[]', encoding="utf-8")
        backup_dir = tmp_path / "new" / "backups"

        result = archive_json_file(json_file, backup_dir)
        assert result is True
        assert backup_dir.exists()

    def test_archive_nonexistent_file(self, tmp_path: Path):
        json_file = tmp_path / "nonexistent.json"
        backup_dir = tmp_path / "backups"

        result = archive_json_file(json_file, backup_dir)
        assert result is False


class TestAuditTokenUsage:
    """Tests for audit_token_usage()."""

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_no_json_files(self, mock_orm, tmp_path: Path):
        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=False,
        )

        assert report.total_files == 0
        assert report.files_matched == 0
        assert report.files_mismatched == 0
        assert report.files_archived == 0

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_match_scenario(self, mock_orm, tmp_path: Path):
        # Create JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 1000}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        # Mock ORM to return matching value
        mock_orm.return_value = 1005  # 0.5% difference

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=False,
        )

        assert report.total_files == 1
        assert report.files_matched == 1
        assert report.files_mismatched == 0
        assert report.files_archived == 0
        assert len(report.results) == 1
        assert report.results[0].matches is True

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_mismatch_scenario(self, mock_orm, tmp_path: Path):
        # Create JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 1000}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        # Mock ORM to return mismatching value
        mock_orm.return_value = 1100  # 10% difference

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=False,
        )

        assert report.total_files == 1
        assert report.files_matched == 0
        assert report.files_mismatched == 1
        assert len(report.results) == 1
        assert report.results[0].matches is False

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_archive_on_match(self, mock_orm, tmp_path: Path):
        # Create JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 1000}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        # Mock ORM to return matching value
        mock_orm.return_value = 1000

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=True,
        )

        assert report.total_files == 1
        assert report.files_matched == 1
        assert report.files_archived == 1
        assert not json_file.exists()
        assert (tmp_path / "backups" / "token_usage.json.bak").exists()

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_no_archive_on_mismatch(self, mock_orm, tmp_path: Path):
        # Create JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 1000}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        # Mock ORM to return mismatching value
        mock_orm.return_value = 2000

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=True,
        )

        assert report.total_files == 1
        assert report.files_mismatched == 1
        assert report.files_archived == 0
        assert json_file.exists()  # File should still exist

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_empty_json_file(self, mock_orm, tmp_path: Path):
        # Create empty JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        json_file.write_text("[]", encoding="utf-8")

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=False,
        )

        assert report.total_files == 1
        assert len(report.results) == 1
        assert report.results[0].error == "Empty or invalid JSON file"

    @patch("scripts.cleanup_token_usage_json.sum_orm_tokens")
    def test_orm_query_failure(self, mock_orm, tmp_path: Path):
        # Create JSON file
        tenant_dir = tmp_path / "tenants" / "tenant-123"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 1000}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        # Mock ORM to raise exception
        mock_orm.side_effect = Exception("Database connection failed")

        report = audit_token_usage(
            db_url="sqlite:///:memory:",
            base_dir=tmp_path,
            tolerance_pct=1.0,
            archive=False,
        )

        assert report.total_files == 1
        assert len(report.results) == 1
        assert "ORM query failed" in report.results[0].error

    def test_tenant_id_extraction(self, tmp_path: Path):
        # Test tenant ID extraction from path
        tenant_dir = tmp_path / "tenants" / "my-tenant-456"
        tenant_dir.mkdir(parents=True)
        json_file = tenant_dir / "token_usage.json"
        data = [{"total_tokens": 100}]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("scripts.cleanup_token_usage_json.sum_orm_tokens") as mock_orm:
            mock_orm.return_value = 100

            audit_token_usage(
                db_url="sqlite:///:memory:",
                base_dir=tmp_path,
                tolerance_pct=1.0,
                archive=False,
            )

            # Verify tenant_id was extracted correctly
            mock_orm.assert_called_once()
            call_args = mock_orm.call_args
            assert call_args[0][1] == "my-tenant-456"


class TestCleanupReport:
    """Tests for CleanupReport.print_report()."""

    def test_print_report_no_files(self, capsys):
        report = CleanupReport(
            results=[],
            total_files=0,
            files_matched=0,
            files_mismatched=0,
            files_archived=0,
            files_not_found=0,
        )

        report.print_report()
        captured = capsys.readouterr()

        assert "TOKEN USAGE JSON CLEANUP REPORT" in captured.out
        assert "Total JSON files scanned:     0" in captured.out

    def test_print_report_with_results(self, capsys, tmp_path: Path):
        results = [
            AuditResult(
                json_path=tmp_path / "token_usage.json",
                json_records=10,
                orm_total_tokens=1000,
                json_total_tokens=1005,
                tolerance_pct=1.0,
                matches=True,
                archived=True,
            ),
        ]

        report = CleanupReport(
            results=results,
            total_files=1,
            files_matched=1,
            files_mismatched=0,
            files_archived=1,
            files_not_found=0,
        )

        report.print_report()
        captured = capsys.readouterr()

        assert "✓ ARCHIVED" in captured.out
        assert "JSON records: 10" in captured.out
        assert "JSON tokens:  1005" in captured.out
        assert "ORM tokens:   1000" in captured.out
