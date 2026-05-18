"""ECharts option sanitizer (design §11.3).

Per §11.3 the platform must reject ECharts options that smuggle code execution:

    "ECharts option 只允许纯 JSON，不允许函数、HTML formatter、外链脚本。"

This module walks an option dict recursively and rejects any:

  - **Function bodies** — string values that start with ``function`` or look
    like JavaScript (``=>``, ``(`` after ``function``). ECharts allows function
    callbacks for ``formatter``, ``label.formatter``, ``axisLabel.formatter``,
    ``tooltip.formatter``, etc.; we forbid all of them.
  - **HTML / script tags** — any string containing ``<script``, ``<iframe``,
    ``<object``, ``<embed``, ``javascript:``, ``data:text/html`` (case-insensitive).
  - **External resource refs in fields ECharts treats as URLs** — ``src``,
    ``backgroundImage``, ``image`` etc. pointing at remote schemes. We allow
    relative refs and ``data:image/...`` blobs for inline SVG/PNG.

Sections that fail sanitization raise :class:`EchartsSanitizeError`; the
runtime turns this into a ``PayloadBuildError`` so the ReportRun fails with a
clear error code instead of silently shipping unsafe content.
"""

from __future__ import annotations

import re
from typing import Any

_FUNCTION_SHAPE_RE = re.compile(
    r"^\s*(?:function\b|\([^)]*\)\s*=>|async\s+function\b|async\s*\([^)]*\)\s*=>)",
    re.IGNORECASE,
)
_DANGEROUS_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|javascript\s*:|data\s*:\s*text/html",
    re.IGNORECASE,
)
_URL_FIELDS = frozenset(
    {"backgroundImage", "image", "src", "url", "href", "imageURL", "logo"}
)
_REMOTE_SCHEME_RE = re.compile(r"^\s*(?:https?|ftp|file)\s*:", re.IGNORECASE)


class EchartsSanitizeError(ValueError):
    """Raised when an ECharts option contains unsafe content."""

    def __init__(self, *, path: str, reason: str, value_preview: str) -> None:
        self.path = path
        self.reason = reason
        self.value_preview = value_preview
        super().__init__(f"{reason} at {path!r}: {value_preview[:80]}")


def sanitize_echart_option(option: Any, *, path: str = "$") -> None:
    """Recursively scan an ECharts option. Raise on first violation.

    Pure inspection — does not mutate. Caller is expected to refuse to ship
    the option if anything is raised.
    """
    if isinstance(option, dict):
        for k, v in option.items():
            child_path = f"{path}.{k}"
            if isinstance(v, str):
                _check_string(v, path=child_path, field_name=str(k))
            else:
                sanitize_echart_option(v, path=child_path)
    elif isinstance(option, list):
        for i, item in enumerate(option):
            sanitize_echart_option(item, path=f"{path}[{i}]")
    elif isinstance(option, str):
        _check_string(option, path=path, field_name="")


def _check_string(value: str, *, path: str, field_name: str) -> None:
    if _FUNCTION_SHAPE_RE.search(value):
        raise EchartsSanitizeError(
            path=path,
            reason="function bodies are forbidden in ECharts option",
            value_preview=value,
        )
    if _DANGEROUS_HTML_RE.search(value):
        raise EchartsSanitizeError(
            path=path,
            reason="HTML/script tags are forbidden in ECharts option",
            value_preview=value,
        )
    if field_name in _URL_FIELDS and _REMOTE_SCHEME_RE.match(value):
        raise EchartsSanitizeError(
            path=path,
            reason="external URLs are forbidden in ECharts option",
            value_preview=value,
        )
