"""Unit tests for report_templates.records — ID validators + Pydantic shapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.report_templates.records import (
    IndexEntry,
    ReportRunRecord,
    ReportTemplateRecord,
    ReportTemplateVersionRecord,
    TemplateIndex,
    new_report_run_id,
    new_template_id,
    now_iso,
    validate_report_run_id,
    validate_template_id,
    validate_user_tenant_id,
)

# ---------------------------------------------------------------------------
# ID generators and validators
# ---------------------------------------------------------------------------


class TestIdGenerators:
    def test_new_template_id_matches_pattern(self):
        for _ in range(50):
            tid = new_template_id()
            validate_template_id(tid)  # raises on mismatch
            assert tid.startswith("tpl_")
            assert len(tid) >= len("tpl_") + 20

    def test_new_report_run_id_matches_pattern(self):
        for _ in range(50):
            rid = new_report_run_id()
            validate_report_run_id(rid)
            assert rid.startswith("rr_")

    def test_ids_are_unique(self):
        seen = {new_template_id() for _ in range(500)}
        assert len(seen) == 500


class TestIdValidators:
    @pytest.mark.parametrize(
        "bad",
        [
            "tpl_short",
            "TPL_AAAAAAAAAAAAAAAAAAAAAAAA",
            "tpl_aaaaaaaaaaaaaaaaaaaaaaaa",  # lowercase
            "tpl_AA-BB-CC",
            "../escape",
            "",
        ],
    )
    def test_rejects_malformed_template_id(self, bad: str):
        with pytest.raises(ValueError):
            validate_template_id(bad)

    @pytest.mark.parametrize(
        "bad",
        ["rr_short", "rr_aaaaaaaa", "RR_AAAAAAAAAAAAAAAAAAAAAA"],
    )
    def test_rejects_malformed_run_id(self, bad: str):
        with pytest.raises(ValueError):
            validate_report_run_id(bad)

    def test_user_tenant_id_pattern(self):
        validate_user_tenant_id("user_alice")
        validate_user_tenant_id("u-1")
        validate_user_tenant_id("a" * 64)
        with pytest.raises(ValueError):
            validate_user_tenant_id("a" * 65)
        with pytest.raises(ValueError):
            validate_user_tenant_id("../escape")
        with pytest.raises(ValueError):
            validate_user_tenant_id("alice/bob")


# ---------------------------------------------------------------------------
# Records validation
# ---------------------------------------------------------------------------


class TestReportTemplateRecord:
    def _minimal(self) -> dict:
        return {
            "id": new_template_id(),
            "name": "demo",
            "display_name": "Demo",
            "owner_user_id": "user_alice",
            "tenant_id": "tenant_a",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "etag": "abc",
        }

    def test_minimal_parses(self):
        ReportTemplateRecord.model_validate(self._minimal())

    def test_rejects_bad_id(self):
        bad = self._minimal()
        bad["id"] = "tpl_short"
        with pytest.raises(ValidationError):
            ReportTemplateRecord.model_validate(bad)

    def test_rejects_bad_owner(self):
        bad = self._minimal()
        bad["owner_user_id"] = "../etc/passwd"
        with pytest.raises(ValidationError):
            ReportTemplateRecord.model_validate(bad)

    def test_rejects_extra_fields(self):
        bad = self._minimal()
        bad["mystery"] = 1
        with pytest.raises(ValidationError):
            ReportTemplateRecord.model_validate(bad)


class TestVersionRecord:
    def _good(self) -> dict:
        return {
            "template_id": new_template_id(),
            "version": 1,
            "dsl": {"x": 1},
            "dsl_yaml": "x: 1\n",
            "checksum": "sha256:abc",
            "created_by": "user_alice",
            "created_at": now_iso(),
        }

    def test_minimal_parses(self):
        ReportTemplateVersionRecord.model_validate(self._good())

    def test_working_copy_version_zero_allowed(self):
        """v0 is the working-draft slot, see repository.save_draft."""
        good = self._good()
        good["version"] = 0
        ReportTemplateVersionRecord.model_validate(good)

    def test_rejects_negative_version(self):
        bad = self._good()
        bad["version"] = -1
        with pytest.raises(ValidationError):
            ReportTemplateVersionRecord.model_validate(bad)

    def test_source_provenance_optional(self):
        good = self._good()
        good["source_template_id"] = new_template_id()
        good["source_template_version"] = 3
        rec = ReportTemplateVersionRecord.model_validate(good)
        assert rec.source_template_version == 3


class TestReportRunRecord:
    def _good(self) -> dict:
        return {
            "id": new_report_run_id(),
            "template_id": new_template_id(),
            "template_version": 1,
            "thread_id": "thread-1",
            "run_id": "run-1",
            "user_id": "user_alice",
            "tenant_id": "tenant_a",
            "created_at": now_iso(),
        }

    def test_minimal_parses(self):
        ReportRunRecord.model_validate(self._good())

    def test_status_enum(self):
        bad = self._good()
        bad["status"] = "weird"
        with pytest.raises(ValidationError):
            ReportRunRecord.model_validate(bad)


class TestTemplateIndex:
    def test_round_trip(self):
        idx = TemplateIndex(
            schema_version="1",
            updated_at=now_iso(),
            templates=[
                IndexEntry(
                    id=new_template_id(),
                    name="x",
                    display_name="X",
                    visibility="private",
                    status="draft",
                    current_version=0,
                    tags=["t1"],
                    updated_at=now_iso(),
                )
            ],
        )
        raw = idx.model_dump()
        parsed = TemplateIndex.model_validate(raw)
        assert len(parsed.templates) == 1
        assert parsed.templates[0].name == "x"
