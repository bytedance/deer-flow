"""Shared data_source banner helper.

Per spec ``equipment-report-data-provider`` "Markdown banner reflecting data
source", the banner string is fully determined by ``data_source`` +
``data_notes``. This module centralizes the formatting so every KPI compute
script and the export_report markdown renderer produce byte-identical output.
"""

from __future__ import annotations

INS_BANNER = "> ✅ 数据来源：InS 实时接入"
DEMO_BANNER_DEFAULT = (
    "> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源"
    "（DEER_FLOW_DATA_PROVIDER 未设置为 ins）"
)
DEMO_BANNER_PREFIX = "> ⚠️ 当前使用演示数据（fallback）。原因："

BANNER_PREFIXES = ("> ✅ ", "> ⚠️ ")


def format_banner(data_source: str | None, data_notes: list[str] | None) -> str:
    """Return the banner line for a payload's ``data_source`` / ``data_notes``.

    Empty / missing ``data_source`` is treated as ``demo_fallback`` so the
    reader always sees a banner — matching the spec's "MUST appear before
    the report title section" requirement.
    """
    notes = data_notes or []
    source = (data_source or "demo_fallback").lower()
    if source == "ins":
        return INS_BANNER
    first_note = next((str(n).strip() for n in notes if str(n).strip()), "")
    if first_note:
        return f"{DEMO_BANNER_PREFIX}{first_note}"
    return DEMO_BANNER_DEFAULT


def is_banner_line(line: str) -> bool:
    """True if ``line`` already starts with the banner prefix.

    Used by export_report to make injection idempotent.
    """
    return line.startswith(BANNER_PREFIXES)
