"""Regression tests for report ``list_equipment.py`` Organize API reads."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATHS = [
    ("daily", REPO_ROOT / "skills" / "custom" / "daily-report" / "scripts" / "list_equipment.py"),
    ("weekly", REPO_ROOT / "skills" / "custom" / "weekly-report" / "scripts" / "list_equipment.py"),
    ("monthly", REPO_ROOT / "skills" / "custom" / "monthly-report" / "scripts" / "list_equipment.py"),
]


def _load_module(script_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(f"test_{script_name}_list_equipment", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._body) - self._offset
        start = self._offset
        end = min(len(self._body), start + size)
        self._offset = end
        return self._body[start:end]


def _large_tree_body() -> bytes:
    tree = [
        {
            "id": "area-1",
            "type": 10,
            "label": "Area A",
            "children": [
                {
                    "id": "EQ-001",
                    "type": 6,
                    "label": "X" * 1_100_000,
                    "children": [],
                }
            ],
        }
    ]
    body = json.dumps(tree, ensure_ascii=False).encode("utf-8")
    assert len(body) > 1_048_576
    return body


@pytest.mark.parametrize(("script_name", "script_path"), SCRIPT_PATHS, ids=[name for name, _ in SCRIPT_PATHS])
def test_query_equipment_reads_full_large_organize_response(monkeypatch, script_name: str, script_path: Path):
    module = _load_module(script_name, script_path)
    body = _large_tree_body()

    monkeypatch.setenv("DEER_FLOW_EFFECTIVE_USER_ID", "user-42")
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda req, timeout=30: _FakeResponse(body),
    )

    result = module.query_equipment("static_equipment", "all", "", limit=10)

    assert "error" not in result
    assert result["data_source"] == "organize_api"
    assert result["total_matched"] == 1
    assert result["equipment"][0]["id"] == "EQ-001"
    assert [item["key"] for item in result["available_kpis"]] == module.EQUIPMENT_TYPE_KPIS["static_equipment"]
