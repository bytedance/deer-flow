"""Tests for the site wind/snow lookup skill script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills-icad" / "public" / "site-wind-snow-lookup" / "scripts" / "query_wind_snow.py"


def _run_query(region: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), region],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_exact_city_match_returns_wind_and_snow_pressures():
    result = _run_query("北京市")

    assert result["status"] == "found"
    assert result["match"]["city"] == "北京市"
    assert result["match"]["province"] == "北京"
    assert result["match"]["wind_pressure_kN_per_m2"]["r50"] == 0.45
    assert result["match"]["snow_pressure_kN_per_m2"]["r50"] == 0.4


def test_normalized_city_match_supports_suffix_free_queries():
    result = _run_query("北京")

    assert result["status"] == "found"
    assert result["match"]["city"] == "北京市"


def test_missing_region_returns_fallback_guidance():
    result = _run_query("火星基地")

    assert result["status"] == "not_found"
    assert result["query"] == "火星基地"
    assert result["next_action"] == "search_web_then_ask_user"
