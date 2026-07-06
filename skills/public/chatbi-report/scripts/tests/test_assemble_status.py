"""Unit tests for scripts/assemble_status.py."""
import json
from pathlib import Path

import pytest

import assemble_status as aus


def test_write_status_success_shape(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=9,
        error_class=None,
        error_detail="",
        outputs={"json": "report.json", "docx": "report.docx", "md": "report.md"},
        metrics={
            "queried_count": 5, "query_failures": 0,
            "computed_count": 2, "compute_validation_failures": 0,
            "llm_calls": 3, "duration_seconds": 12.4,
        },
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["exit_step"] == 9
    assert data["error_class"] is None
    assert data["outputs"]["json"] == "report.json"
    assert data["metrics"]["queried_count"] == 5
    assert data["metrics"]["duration_seconds"] == 12.4


def test_write_status_error_when_error_class_set(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=2, error_class="F1", error_detail="missing > 机构: block",
        outputs={"json": None, "docx": None, "md": None},
        metrics={"queried_count": 0, "query_failures": 0,
                 "computed_count": 0, "compute_validation_failures": 0,
                 "llm_calls": 0, "duration_seconds": 0.3},
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["error_class"] == "F1"
    assert data["exit_step"] == 2
    assert data["outputs"]["json"] is None


def test_write_status_user_aborted_at_description_checkpoint(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step="8d.5",
        error_class="USER_ABORTED",
        error_detail="描述段落已生成：1/1 成功。请修改原始样张里的 `> 描述:` 块后重跑。",
        outputs={"json": None, "docx": None, "md": None},
        metrics={
            "queried_count": 4,
            "query_failures": 0,
            "computed_count": 2,
            "compute_validation_failures": 0,
            "descriptions_generated": 1,
            "description_failures": 0,
            "llm_calls": 3,
            "duration_seconds": 4.2,
        },
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["exit_step"] == "8d.5"
    assert data["error_class"] == "USER_ABORTED"
    assert "描述段落已生成" in data["error_detail"]
    assert data["metrics"]["descriptions_generated"] == 1


def test_write_status_partial_when_description_fails(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=9,
        error_class=None,
        error_detail="",
        outputs={"json": "report.json", "docx": "report.docx", "md": "report.md"},
        metrics={
            "queried_count": 1, "query_failures": 0,
            "computed_count": 0, "compute_validation_failures": 0,
            "descriptions_generated": 1, "description_failures": 1,
            "llm_calls": 1, "duration_seconds": 1.2,
        },
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "partial"
    assert data["metrics"]["descriptions_generated"] == 1
    assert data["metrics"]["description_failures"] == 1
