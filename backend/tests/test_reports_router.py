"""Tests for reports gateway router."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_paths(base_dir: Path):
    from src.config.paths import Paths

    return Paths(base_dir=base_dir)


def _make_app() -> FastAPI:
    from src.gateway.routers.reports import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_export_latex_diagnostics_markdown(tmp_path: Path):
    paths_instance = _make_paths(tmp_path)
    with patch("src.gateway.routers.reports.get_paths", return_value=paths_instance):
        app = _make_app()
        with TestClient(app) as client:
            response = client.post(
                "/api/threads/thread-report/reports/latex_diagnostics_markdown",
                json={
                    "title": "Compile diagnostics",
                    "project_id": "p-report",
                    "section_id": "discussion",
                    "compile_status": "failed",
                    "compiler": "latexmk",
                    "compile_log_path": "/mnt/user-data/outputs/research-writing/latex/p-report.compile.log",
                    "failure_reason": "! LaTeX Error: File `booktabs.sty' not found.",
                    "issue_clusters": [
                        {
                            "id": "missing-package",
                            "title": "缺少 LaTeX 宏包（.sty）",
                            "severity": "error",
                            "match_count": 2,
                            "matched_lines": [
                                "L31: ! LaTeX Error: File `booktabs.sty' not found.",
                                "L32: ! Emergency stop.",
                            ],
                            "suggestions": [
                                "tlmgr install booktabs",
                                "apt install texlive-latex-extra",
                            ],
                        }
                    ],
                    "error_preview": ["L31: ! LaTeX Error: File `booktabs.sty' not found."],
                    "warning_preview": ["L12: LaTeX Warning: There were undefined references."],
                    "raw_key_log": "L31: ! LaTeX Error: File `booktabs.sty' not found.",
                    "output_filename": "diag-report.md",
                },
            )

            assert response.status_code == 200
            payload = response.json()
            report_path = payload["report_path"]
            assert report_path.startswith("/mnt/user-data/outputs/research-writing/latex/reports/")
            assert report_path.endswith("diag-report.md")

            physical = paths_instance.resolve_virtual_path("thread-report", report_path)
            assert physical.exists()
            text = physical.read_text(encoding="utf-8")
            assert "# Compile diagnostics" in text
            assert "## Error Type Clusters" in text
            assert "missing-package" in text
            assert "booktabs.sty" in text
            assert "## Reproducibility Checklist" in text
            assert "### 0) One-click script entry" in text
            assert "bash <<'EOF'" in text
            assert "DRY_RUN=\"${DRY_RUN:-0}\"" in text
            assert "STRICT=\"${STRICT:-0}\"" in text
            assert "HISTORY_LIMIT=\"${HISTORY_LIMIT:-8}\"" in text
            assert "set DRY_RUN=1 to print commands only" in text
            assert "set STRICT=1 to fail fast in CI" in text
            assert "run_cmd 'sudo apt-get update'" in text
            assert "STRICT=1, stop at first failure." in text
            assert "Recent command replay (last ${limit}):" in text
            assert "print_recent_cmds" in text
            assert "sudo apt-get install -y latexmk" in text
            assert "latexmk -pdf -interaction=nonstopmode -file-line-error main.tex" in text


def test_export_latex_diagnostics_markdown_alpine_template(tmp_path: Path):
    paths_instance = _make_paths(tmp_path)
    with (
        patch("src.gateway.routers.reports.get_paths", return_value=paths_instance),
        patch("src.gateway.routers.reports._detect_runtime_os_family", return_value="alpine"),
    ):
        app = _make_app()
        with TestClient(app) as client:
            response = client.post(
                "/api/threads/thread-report-alpine/reports/latex_diagnostics_markdown",
                json={
                    "title": "Compile diagnostics alpine",
                    "compile_status": "failed",
                    "issue_clusters": [
                        {
                            "id": "missing-tex-binary",
                            "title": "缺少 TeX 命令",
                            "severity": "error",
                            "match_count": 1,
                            "matched_lines": ["L9: latexmk: command not found"],
                            "suggestions": ["install latexmk"],
                        },
                        {
                            "id": "font-problem",
                            "title": "字体问题",
                            "severity": "error",
                            "match_count": 1,
                            "matched_lines": ["L15: Package fontspec Error: The font ... cannot be found."],
                            "suggestions": ["install fonts"],
                        },
                    ],
                    "output_filename": "diag-alpine.md",
                },
            )
            assert response.status_code == 200
            report_path = response.json()["report_path"]
            physical = paths_instance.resolve_virtual_path("thread-report-alpine", report_path)
            text = physical.read_text(encoding="utf-8")
            assert "runtime_os_detected: `Alpine`" in text
            assert "bash <<'EOF'" in text
            assert "DRY_RUN=\"${DRY_RUN:-0}\"" in text
            assert "STRICT=\"${STRICT:-0}\"" in text
            assert "HISTORY_LIMIT=\"${HISTORY_LIMIT:-8}\"" in text
            assert "apk add --no-cache texlive-full biber fontconfig" in text
            assert "apk add --no-cache font-noto font-noto-cjk fontconfig" in text

