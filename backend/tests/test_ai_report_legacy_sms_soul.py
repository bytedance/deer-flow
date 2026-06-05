"""Contract tests for legacy weekly/monthly report SOUL SMS integration.

These agents still have a hardcoded legacy entry pipeline (not the unified
DSL runtime). To keep weekly/monthly behavior aligned with legacy daily, the
SOUL must explicitly invoke ``query_sms_abnormal.py`` before KPI calculation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

WEEKLY_SOUL_PATH = REPO_ROOT / "agents" / "builtin" / "ai-report--weekly" / "SOUL.md"
MONTHLY_SOUL_PATH = REPO_ROOT / "agents" / "builtin" / "ai-report--monthly" / "SOUL.md"


@pytest.mark.parametrize(
    ("soul_path", "sms_script", "kpi_script", "required_flags"),
    [
        (
            WEEKLY_SOUL_PATH,
            "query_sms_abnormal.py",
            "weekly_kpi.py",
            ["--week-start", "--type", "--equipment", "--equipment-names"],
        ),
        (
            MONTHLY_SOUL_PATH,
            "query_sms_abnormal.py",
            "monthly_kpi.py",
            ["--report-month", "--type", "--equipment", "--equipment-names"],
        ),
    ],
)
def test_legacy_report_soul_invokes_sms_query_before_kpi(
    soul_path: Path,
    sms_script: str,
    kpi_script: str,
    required_flags: list[str],
):
    """Weekly/monthly legacy pipelines must explicitly query SMS anomalies.

    The legacy SOUL path is still active for these agents, so it cannot rely on
    the builtin DSL template to fetch ``sms_abnormal.json``.
    """

    soul_text = soul_path.read_text(encoding="utf-8")

    assert sms_script in soul_text, f"{soul_path.name} must call {sms_script}"
    assert kpi_script in soul_text, f"{soul_path.name} must call {kpi_script}"
    sms_index = soul_text.index(sms_script)
    kpi_index = soul_text.index(kpi_script)

    assert sms_index < kpi_index, (
        f"{soul_path.name} must run {sms_script} before {kpi_script}"
    )

    sms_window = soul_text[sms_index:kpi_index]
    for flag in required_flags:
        assert flag in sms_window, f"{soul_path.name} SMS step missing CLI flag {flag}"


@pytest.mark.parametrize("soul_path", [WEEKLY_SOUL_PATH, MONTHLY_SOUL_PATH])
def test_legacy_report_soul_documents_sms_failure_as_non_blocking(soul_path: Path):
    """SMS query should be best-effort like the legacy daily path."""

    soul_text = soul_path.read_text(encoding="utf-8")

    sms_index = soul_text.index("query_sms_abnormal.py")
    next_script_index = soul_text.index("_kpi.py", sms_index)
    window = soul_text[sms_index:next_script_index]

    assert "SMS" in window
    assert "error" in window.lower() or "best-effort" in window.lower()
