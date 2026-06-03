"""Unit tests for ``skills/custom/data-analyst/scripts/_ins_provider.py``.

These cover the internal helpers (``_iter_points``, ``_EVENT_TYPE_MAP``,
``_format_machine_drop_entry``, etc.) still used by ``InsTrendProvider``.
The daily/weekly/monthly report sync wrappers (``fetch_daily_payload``, etc.)
have been removed — the reports now route through the integrations platform
bridge via ``PlatformDailyProvider`` / ``PlatformWeeklyProvider`` /
``PlatformMonthlyProvider`` in ``_data_provider_impls.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_PATH = (
    REPO_ROOT
    / "skills"
    / "custom"
    / "data-analyst"
    / "scripts"
    / "_ins_provider.py"
)


# ---------------------------------------------------------------------------
# Module loader — fresh import per test so module-level env reads are honored
# ---------------------------------------------------------------------------


def _load_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    sys.modules.pop("_ins_provider", None)
    spec = importlib.util.spec_from_file_location("_ins_provider", PROVIDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ins_provider"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INS_FACTORY_ID", raising=False)
    return _load_provider(monkeypatch)


# ---------------------------------------------------------------------------
# Regression: _iter_points must yield nodes that ALREADY carry endpoint_series
# without descending into their children. A parent with endpoint_series set is
# a leaf point in the slim-component tree; descending would double-count.
# ---------------------------------------------------------------------------


def test_iter_points_yields_endpoint_series_node_and_skips_its_children(provider):
    """A node carrying ``endpoint_series`` is itself a measurement point and
    must be yielded as-is. Its ``children`` / ``points`` must NOT be visited
    (they belong to a different traversal layer)."""
    components = [
        {
            "id": "PARENT_AS_POINT",
            "endpoint_series": "8k",
            "type_num": 82,
            "children": [
                {"id": "DECOY_CHILD", "endpoint_series": "2k", "type_num": 23},
            ],
            "points": [
                {"id": "DECOY_POINT", "endpoint_series": "6k", "type_num": 62},
            ],
        }
    ]
    yielded = list(provider._iter_points(components))
    assert [n["id"] for n in yielded] == ["PARENT_AS_POINT"]


def test_iter_points_descends_into_children_when_endpoint_series_missing(provider):
    """When a node lacks ``endpoint_series``, _iter_points must walk into both
    ``children`` and ``points`` to find leaf points. Ordering is unspecified
    (stack-based), so compare as sets."""
    components = [
        {
            "id": "GROUP_A",
            "children": [
                {"id": "LEAF_1", "endpoint_series": "2k", "type_num": 23},
                {
                    "id": "GROUP_B",
                    "children": [
                        {"id": "LEAF_2", "endpoint_series": "6k", "type_num": 62},
                    ],
                },
            ],
            "points": [
                {"id": "LEAF_3", "endpoint_series": "8k", "type_num": 82},
            ],
        }
    ]
    yielded_ids = {n["id"] for n in provider._iter_points(components)}
    assert yielded_ids == {"LEAF_1", "LEAF_2", "LEAF_3"}


def test_iter_points_handles_non_dict_entries_gracefully(provider):
    """Non-dict entries in the input list or in ``children``/``points`` must be
    silently skipped instead of raising."""
    components = [
        None,
        "junk",
        {
            "id": "OK",
            "children": [None, {"id": "L1", "endpoint_series": "2k"}, "x"],
            "points": [{"id": "L2", "endpoint_series": "8k"}, 42],
        },
    ]
    yielded_ids = {n["id"] for n in provider._iter_points(components)}
    assert yielded_ids == {"L1", "L2"}


# ---------------------------------------------------------------------------
# Machine drop events — _EVENT_TYPE_MAP, _event_series_for_eq_type,
# _format_machine_drop_entry.
# ---------------------------------------------------------------------------


def test_event_type_map_covers_all_18_types(provider):
    assert len(provider._EVENT_TYPE_MAP) == 18
    for t in range(1, 19):
        assert t in provider._EVENT_TYPE_MAP, f"type {t} missing from _EVENT_TYPE_MAP"
        label, level = provider._EVENT_TYPE_MAP[t]
        assert isinstance(label, str) and len(label) > 0
        assert level in {"high", "warning", "info"}


def test_event_type_map_critical_types_have_high_level(provider):
    assert provider._EVENT_TYPE_MAP[1][1] == "high"
    assert provider._EVENT_TYPE_MAP[15][1] == "high"


def test_event_type_map_warning_types_have_warning_level(provider):
    warning_types = [2, 6, 7, 8, 9, 10, 11, 12, 14]
    for t in warning_types:
        assert provider._EVENT_TYPE_MAP[t][1] == "warning", f"type {t} expected warning"


def test_event_types_8k_covers_1_to_18(provider):
    assert set(provider._EVENT_TYPES_8K) == set(range(1, 19))


def test_event_types_9k_is_restricted_subset(provider):
    assert set(provider._EVENT_TYPES_9K) == {1, 2, 3, 14, 15}


def test_event_series_for_eq_type_rotating(provider):
    assert provider._event_series_for_eq_type("rotating_machinery") == "8k"


def test_event_series_for_eq_type_reciprocating(provider):
    assert provider._event_series_for_eq_type("reciprocating_machinery") == "9k"


def test_event_series_for_eq_type_none_for_other(provider):
    assert provider._event_series_for_eq_type("pump") is None
    assert provider._event_series_for_eq_type("static_equipment") is None
    assert provider._event_series_for_eq_type("all") is None


def test_format_machine_drop_entry_maps_type_to_label_and_level(provider):
    entry = {
        "posId": "P001",
        "posName": "驱动端振动",
        "types": [1],
        "datatime": 1700000000000,
    }
    result = provider._format_machine_drop_entry(entry)
    assert result is not None
    assert result["level"] == "high"
    assert result["event_type"] == 1
    assert result["event_label"] == "主报警"
    assert "主报警" in result["message"]
    assert "驱动端振动" in result["message"]
    assert result["time"] is not None


def test_format_machine_drop_entry_uses_pos_id_fallback(provider):
    entry = {
        "posId": "P002",
        "types": [14],
        "datatime": 1700000000000,
    }
    result = provider._format_machine_drop_entry(entry)
    assert result is not None
    assert result["level"] == "warning"
    assert result["event_label"] == "预警"
    assert "P002" in result["message"]


def test_format_machine_drop_entry_returns_none_for_empty_types(provider):
    entry = {"posId": "P003", "posName": "x", "types": [], "datatime": 1700000000000}
    assert provider._format_machine_drop_entry(entry) is None
