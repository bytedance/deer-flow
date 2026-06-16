"""Exporter — Markdown (required) + PDF (optional) export.

§12.2 of the design: Markdown is mandatory for every successful ReportRun,
PDF is optional and gracefully degrades when ``weasyprint`` is unavailable.

This module is a thin wrapper around Phase 0's ``render_markdown_generic``;
the heavy lifting (HTML escape, section type dispatch) already lives there.
We add:

  - File-system contract: write to ``{run_output_dir}/exports/report.md`` (+ ``.pdf``)
  - Idempotency: subsequent calls overwrite the same files
  - Result tuple: ``ExportResult`` with both paths and a ``pdf_skipped_reason``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.report_templates.generic_renderer import (
    RenderError,
    render_markdown_generic,
)

logger = logging.getLogger(__name__)


class ExportError(Exception):
    """Raised when Markdown export fails (PDF failure does not raise — it degrades)."""


@dataclass(frozen=True)
class ExportResult:
    md_path: str
    pdf_path: str | None
    pdf_skipped_reason: str | None  # "weasyprint_unavailable" | "render_error" | None


def export_report(
    *,
    payload: dict[str, Any],
    run_output_dir: Path,
    pdf: bool = True,
) -> ExportResult:
    """Render ``payload`` to Markdown (required) and PDF (best-effort).

    Args:
        payload: ``report_payload.json`` dict, see §12.1.
        run_output_dir: Run-scoped output directory; ``exports/`` is created here.
        pdf: When False, skip PDF entirely. When True, attempt PDF but degrade
            gracefully on missing dependency or render error.

    Returns:
        ``ExportResult`` with absolute paths.

    Raises:
        ExportError: Markdown could not be rendered or written.
    """
    exports_dir = run_output_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # Markdown — required.
    try:
        md_text = render_markdown_generic(payload)
    except RenderError as e:
        raise ExportError(f"Markdown render failed: {e}") from e

    md_path = exports_dir / "report.md"
    md_path.write_text(md_text, encoding="utf-8")

    # PDF — optional.
    if not pdf:
        return ExportResult(
            md_path=str(md_path), pdf_path=None, pdf_skipped_reason=None
        )
    return _attempt_pdf(md_text=md_text, exports_dir=exports_dir, md_path=md_path)


def _attempt_pdf(
    *, md_text: str, exports_dir: Path, md_path: Path
) -> ExportResult:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except Exception:
        # Module not installed (ImportError) or installed but system libs
        # missing — e.g. Windows without GTK (OSError).
        logger.warning("weasyprint unavailable, PDF export skipped", exc_info=True)
        return ExportResult(
            md_path=str(md_path),
            pdf_path=None,
            pdf_skipped_reason="weasyprint_unavailable",
        )

    try:
        # Minimal Markdown → HTML via the stdlib-friendly ``markdown`` lib if
        # available; otherwise fall back to a raw <pre> dump so we still get
        # *something* with weasyprint.
        try:
            import markdown  # type: ignore[import-not-found]

            html_body = markdown.markdown(
                md_text, extensions=["tables", "fenced_code"]
            )
        except ImportError:
            html_body = f"<pre>{_html_escape(md_text)}</pre>"

        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:sans-serif;padding:24px} table{border-collapse:collapse}"
            " td,th{border:1px solid #ccc;padding:4px 8px}</style>"
            "</head><body>" + html_body + "</body></html>"
        )

        pdf_path = exports_dir / "report.pdf"
        HTML(string=html).write_pdf(target=str(pdf_path))
        return ExportResult(
            md_path=str(md_path),
            pdf_path=str(pdf_path),
            pdf_skipped_reason=None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF export failed (gracefully degraded): %s", e)
        return ExportResult(
            md_path=str(md_path),
            pdf_path=None,
            pdf_skipped_reason="render_error",
        )


def _html_escape(text: str) -> str:
    import html

    return html.escape(text)
