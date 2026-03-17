import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.config.scientific_vision_config import get_scientific_vision_config
from src.gateway.path_utils import resolve_thread_virtual_path
from src.utils.image_report_pdf import generate_image_report_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reports"])


class ImageReportPdfRequest(BaseModel):
    """Request to export an ImageReport (index + per-image artifacts) into a PDF."""

    index_path: str | None = Field(
        default=None,
        description="Optional virtual path to the ImageReport index artifact (e.g. /mnt/user-data/outputs/.../index-xxxx.json).",
    )
    index_payload: dict[str, Any] | None = Field(
        default=None,
        description="Optional inline ImageReport index JSON payload. Used when index_path is unavailable.",
    )
    output_filename: str | None = Field(
        default=None,
        description="Optional output filename (stored under /mnt/user-data/outputs/{artifact_subdir}/pdfs/).",
    )


class ImageReportPdfResponse(BaseModel):
    pdf_path: str


class LatexIssueClusterRequest(BaseModel):
    id: str
    title: str
    severity: str = Field(default="error")
    match_count: int = 0
    matched_lines: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class LatexDiagnosticsMarkdownRequest(BaseModel):
    title: str | None = None
    project_id: str | None = None
    section_id: str | None = None
    source_path: str | None = None
    compile_status: str | None = None
    compiler: str | None = None
    engine_requested: str | None = None
    compile_log_path: str | None = None
    failure_reason: str | None = None
    issue_clusters: list[LatexIssueClusterRequest] = Field(default_factory=list)
    error_preview: list[str] = Field(default_factory=list)
    warning_preview: list[str] = Field(default_factory=list)
    raw_key_log: str | None = None
    output_filename: str | None = None

    @field_validator("output_filename")
    @classmethod
    def _validate_output_filename(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().replace("\\", "/").split("/")[-1]
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-")
        if not normalized:
            return None
        if not normalized.lower().endswith(".md"):
            normalized = f"{normalized}.md"
        return normalized


class LatexDiagnosticsMarkdownResponse(BaseModel):
    report_path: str


def _markdown_outputs_virtual_path(relative_path: Path) -> str:
    rel = relative_path.as_posix().lstrip("/")
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{rel}"


def _detect_runtime_os_family() -> str:
    """Best-effort runtime distro detection for install command templates."""
    try:
        if Path("/etc/alpine-release").exists():
            return "alpine"
    except Exception:
        pass

    try:
        os_release = Path("/etc/os-release")
        if os_release.exists():
            raw = os_release.read_text(encoding="utf-8", errors="replace")
            pairs: dict[str, str] = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", maxsplit=1)
                pairs[key.strip().lower()] = value.strip().strip('"').strip("'").lower()
            id_text = pairs.get("id", "")
            like_text = pairs.get("id_like", "")
            combined = f"{id_text} {like_text}"
            if "alpine" in combined:
                return "alpine"
            if any(token in combined for token in ("debian", "ubuntu", "linuxmint", "pop", "kali")):
                return "debian"
    except Exception:
        pass

    # Default to Debian/Ubuntu template because it is most common in CI images.
    return "debian"


def _latex_install_commands_for_os(os_family: str) -> list[str]:
    if os_family == "alpine":
        return [
            "apk update",
            "apk add --no-cache texlive-full biber fontconfig",
        ]
    return [
        "sudo apt-get update",
        "sudo apt-get install -y latexmk texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended texlive-xetex biber",
    ]


def _font_fix_commands_for_os(os_family: str) -> list[str]:
    if os_family == "alpine":
        return [
            "apk update",
            "apk add --no-cache font-noto font-noto-cjk fontconfig",
            "fc-cache -fv || true",
        ]
    return [
        "sudo apt-get update",
        "sudo apt-get install -y fonts-noto fonts-noto-cjk",
        "fc-cache -fv || true",
    ]


def _build_reproducible_checklist_lines(request: LatexDiagnosticsMarkdownRequest) -> list[str]:
    cluster_ids = {cluster.id for cluster in request.issue_clusters}
    lines: list[str] = []
    detected_os = _detect_runtime_os_family()
    primary_os = "alpine" if detected_os == "alpine" else "debian"
    secondary_os = "debian" if primary_os == "alpine" else "alpine"
    os_labels = {"debian": "Debian/Ubuntu", "alpine": "Alpine"}

    lines.append("## Reproducibility Checklist")
    lines.append("")
    lines.append("可直接复制到 CI 或服务器执行（根据命中问题自动推荐）。")
    lines.append(f"- runtime_os_detected: `{os_labels.get(primary_os, primary_os)}`")
    lines.append(f"- fallback_template: `{os_labels.get(secondary_os, secondary_os)}`")
    lines.append("")

    lines.append("### 0) One-click script entry")
    lines.append("")
    lines.append("```bash")
    lines.append("bash <<'EOF'")
    lines.append("set -euo pipefail")
    lines.append("TARGET_TEX=\"${TARGET_TEX:-main.tex}\"")
    lines.append("DRY_RUN=\"${DRY_RUN:-0}\"")
    lines.append("STRICT=\"${STRICT:-0}\"")
    lines.append("HISTORY_LIMIT=\"${HISTORY_LIMIT:-8}\"")
    lines.append("_CMD_HISTORY=()")
    lines.append("")
    lines.append("record_cmd() {")
    lines.append("  local cmd=\"$1\"")
    lines.append("  _CMD_HISTORY+=(\"${cmd}\")")
    lines.append("  if [ \"${#_CMD_HISTORY[@]}\" -gt 64 ]; then")
    lines.append("    _CMD_HISTORY=(\"${_CMD_HISTORY[@]:1}\")")
    lines.append("  fi")
    lines.append("}")
    lines.append("")
    lines.append("print_recent_cmds() {")
    lines.append("  local limit=\"${HISTORY_LIMIT}\"")
    lines.append("  local total=\"${#_CMD_HISTORY[@]}\"")
    lines.append("  local start=0")
    lines.append("  if [ \"${total}\" -gt \"${limit}\" ]; then")
    lines.append("    start=$((total - limit))")
    lines.append("  fi")
    lines.append("  echo \"Recent command replay (last ${limit}):\" >&2")
    lines.append("  local i")
    lines.append("  for ((i=start; i<total; i++)); do")
    lines.append("    echo \"  [$((i + 1))] ${_CMD_HISTORY[$i]}\" >&2")
    lines.append("  done")
    lines.append("}")
    lines.append("")
    lines.append("run_cmd() {")
    lines.append("  local cmd=\"$1\"")
    lines.append("  record_cmd \"${cmd}\"")
    lines.append("  echo \"+ ${cmd}\"")
    lines.append("  if [ \"${DRY_RUN}\" = \"1\" ]; then")
    lines.append("    return 0")
    lines.append("  fi")
    lines.append("  if bash -lc \"${cmd}\"; then")
    lines.append("    return 0")
    lines.append("  fi")
    lines.append("  local rc=$?")
    lines.append("  echo \"Command failed (exit=${rc}): ${cmd}\" >&2")
    lines.append("  if [ \"${STRICT}\" = \"1\" ]; then")
    lines.append("    echo \"STRICT=1, stop at first failure.\" >&2")
    lines.append("    print_recent_cmds")
    lines.append("    echo \"定位建议: 优先检查首次报错位置（通常是 .log 中第一个 '! ...'）。\" >&2")
    lines.append("    echo \"可尝试: grep -n '^!' *.log | head -n 1\" >&2")
    lines.append("    exit ${rc}")
    lines.append("  fi")
    lines.append("  echo \"STRICT=0, continue to next step.\" >&2")
    lines.append("  return 0")
    lines.append("}")
    lines.append("")
    lines.append("# Generated from DeerFlow LaTeX diagnostics report")
    lines.append(f"echo \"Detected template: {os_labels.get(primary_os, primary_os)}\"")
    lines.append("echo \"DRY_RUN=${DRY_RUN} (set DRY_RUN=1 to print commands only)\"")
    lines.append("echo \"STRICT=${STRICT} (set STRICT=1 to fail fast in CI)\"")
    lines.append("echo \"HISTORY_LIMIT=${HISTORY_LIMIT} (recent command replay size)\"")
    lines.append("")
    lines.append("# Install toolchain (primary template)")
    for cmd in _latex_install_commands_for_os(primary_os):
        lines.append(f"run_cmd '{cmd}'")
    if "font-problem" in cluster_ids:
        lines.append("")
        lines.append("# Install fonts (primary template)")
        for cmd in _font_fix_commands_for_os(primary_os):
            lines.append(f"run_cmd '{cmd}'")
    lines.append("")
    lines.append("# Build sequence")
    if "undefined-reference" in cluster_ids:
        lines.append("run_cmd 'pdflatex -interaction=nonstopmode -file-line-error \"$TARGET_TEX\"'")
        lines.append("run_cmd 'BASE_NAME=\"${TARGET_TEX%.tex}\"; biber \"$BASE_NAME\" || bibtex \"$BASE_NAME\"'")
        lines.append("run_cmd 'pdflatex -interaction=nonstopmode -file-line-error \"$TARGET_TEX\"'")
        lines.append("run_cmd 'pdflatex -interaction=nonstopmode -file-line-error \"$TARGET_TEX\"'")
    else:
        lines.append("run_cmd 'latexmk -pdf -interaction=nonstopmode -file-line-error \"$TARGET_TEX\"'")
    if "font-problem" in cluster_ids:
        lines.append("run_cmd 'latexmk -xelatex -interaction=nonstopmode -file-line-error \"$TARGET_TEX\"'")
    if {"undefined-control-sequence", "tex-emergency-stop"} & cluster_ids:
        lines.append(
            "run_cmd 'latexmk -pdf -interaction=nonstopmode -file-line-error -halt-on-error \"$TARGET_TEX\"'",
        )
    lines.append("echo \"Done. Check *.log for first error (! ...).\"")
    lines.append("EOF")
    lines.append("```")
    lines.append("")

    # Universal baseline checks.
    lines.append("### 1) Baseline environment check")
    lines.append("")
    lines.append("```bash")
    lines.append("set -euo pipefail")
    lines.append("echo \"=== TeX toolchain ===\"")
    lines.append("command -v latexmk || true")
    lines.append("command -v pdflatex || true")
    lines.append("command -v xelatex || true")
    lines.append("command -v biber || true")
    lines.append("latexmk --version || true")
    lines.append("pdflatex --version || true")
    lines.append("xelatex --version || true")
    lines.append("biber --version || true")
    lines.append("```")
    lines.append("")

    if {"missing-tex-binary", "missing-package"} & cluster_ids:
        lines.append(f"### 2) Install missing TeX packages/tools ({os_labels[primary_os]} template)")
        lines.append("")
        lines.append("```bash")
        lines.extend(_latex_install_commands_for_os(primary_os))
        lines.append("```")
        lines.append("")
        lines.append(f"Alternative template ({os_labels[secondary_os]}):")
        lines.append("")
        lines.append("```bash")
        lines.extend(_latex_install_commands_for_os(secondary_os))
        lines.append("```")
        lines.append("")
        lines.append("若你使用 `tlmgr` 管理 CTAN 包，可追加：")
        lines.append("")
        lines.append("```bash")
        lines.append("tlmgr update --self || true")
        lines.append("tlmgr install collection-latexextra collection-fontsextra || true")
        lines.append("```")
        lines.append("")

    if "font-problem" in cluster_ids:
        lines.append(f"### 3) Font troubleshooting ({os_labels[primary_os]} template, prefer xelatex)")
        lines.append("")
        lines.append("```bash")
        lines.extend(_font_fix_commands_for_os(primary_os))
        lines.append("```")
        lines.append("")
        lines.append(f"Alternative template ({os_labels[secondary_os]}):")
        lines.append("")
        lines.append("```bash")
        lines.extend(_font_fix_commands_for_os(secondary_os))
        lines.append("```")
        lines.append("")
        lines.append("推荐引擎切换：")
        lines.append("")
        lines.append("```bash")
        lines.append("latexmk -xelatex -interaction=nonstopmode -file-line-error main.tex")
        lines.append("```")
        lines.append("")

    if "undefined-reference" in cluster_ids:
        lines.append("### 4) Citation/Cross-reference rebuild sequence")
        lines.append("")
        lines.append("```bash")
        lines.append("pdflatex -interaction=nonstopmode -file-line-error main.tex || true")
        lines.append("biber main || bibtex main || true")
        lines.append("pdflatex -interaction=nonstopmode -file-line-error main.tex || true")
        lines.append("pdflatex -interaction=nonstopmode -file-line-error main.tex || true")
        lines.append("```")
        lines.append("")

    if "missing-input-file" in cluster_ids:
        lines.append("### 5) Missing input file checks")
        lines.append("")
        lines.append("```bash")
        lines.append("pwd")
        lines.append("ls -lah")
        lines.append("ls -lah figures || true")
        lines.append("ls -lah *.bib || true")
        lines.append("```")
        lines.append("")
        lines.append("确认 `\\includegraphics{}`、`\\input{}`、`\\bibliography{}` 的相对路径均以编译目录为基准。")
        lines.append("")

    if {"undefined-control-sequence", "tex-emergency-stop"} & cluster_ids:
        lines.append("### 6) First-error focused compile")
        lines.append("")
        lines.append("```bash")
        lines.append("latexmk -pdf -interaction=nonstopmode -file-line-error -halt-on-error main.tex")
        lines.append("```")
        lines.append("")
        lines.append("优先修复日志中首个 `!` 错误，再重新编译，避免被连锁错误误导。")
        lines.append("")

    preferred_engine = request.engine_requested or "auto"
    lines.append("### 7) Recommended engine switch")
    lines.append("")
    lines.append("当前请求引擎：")
    lines.append(f"- `{preferred_engine}`")
    lines.append("")
    lines.append("可尝试：")
    lines.append("")
    lines.append("```bash")
    lines.append("latexmk -pdf -interaction=nonstopmode -file-line-error main.tex")
    lines.append("latexmk -xelatex -interaction=nonstopmode -file-line-error main.tex")
    lines.append("```")
    lines.append("")

    return lines


def _build_latex_diagnostics_markdown(request: LatexDiagnosticsMarkdownRequest, *, thread_id: str) -> str:
    now = datetime.now(UTC).isoformat()
    lines: list[str] = []
    title = request.title or "LaTeX Troubleshooting Report"
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Metadata")
    lines.append(f"- generated_at: `{now}`")
    lines.append(f"- thread_id: `{thread_id}`")
    if request.project_id:
        lines.append(f"- project_id: `{request.project_id}`")
    if request.section_id:
        lines.append(f"- section_id: `{request.section_id}`")
    if request.source_path:
        lines.append(f"- source_path: `{request.source_path}`")
    if request.compile_status:
        lines.append(f"- compile_status: `{request.compile_status}`")
    if request.compiler:
        lines.append(f"- compiler: `{request.compiler}`")
    if request.engine_requested:
        lines.append(f"- engine_requested: `{request.engine_requested}`")
    if request.compile_log_path:
        lines.append(f"- compile_log_path: `{request.compile_log_path}`")
    lines.append("")

    if request.failure_reason:
        lines.append("## Failure Summary")
        lines.append("")
        lines.append(f"- reason: {request.failure_reason}")
        lines.append("")

    if request.issue_clusters:
        lines.append("## Error Type Clusters")
        lines.append("")
        for idx, cluster in enumerate(request.issue_clusters, start=1):
            lines.append(f"### {idx}. {cluster.title}")
            lines.append(f"- id: `{cluster.id}`")
            lines.append(f"- severity: `{cluster.severity}`")
            lines.append(f"- hits: `{cluster.match_count}`")
            lines.append("")
            if cluster.matched_lines:
                lines.append("Matched log lines:")
                lines.append("```text")
                lines.extend(cluster.matched_lines[:80])
                lines.append("```")
                lines.append("")
            if cluster.suggestions:
                lines.append("Actionable suggestions:")
                for suggestion in cluster.suggestions[:20]:
                    lines.append(f"- {suggestion}")
                lines.append("")

    if request.error_preview:
        lines.append("## Key Error Lines")
        lines.append("")
        lines.append("```text")
        lines.extend(request.error_preview[:120])
        lines.append("```")
        lines.append("")

    if request.warning_preview:
        lines.append("## Key Warning Lines")
        lines.append("")
        lines.append("```text")
        lines.extend(request.warning_preview[:120])
        lines.append("```")
        lines.append("")

    if request.raw_key_log:
        lines.append("## Raw Key Log Excerpt")
        lines.append("")
        lines.append("```text")
        lines.append(request.raw_key_log[:120_000])
        lines.append("```")
        lines.append("")

    lines.extend(_build_reproducible_checklist_lines(request))

    return "\n".join(lines).strip() + "\n"


@router.post(
    "/threads/{thread_id}/reports/image_report_pdf",
    summary="Export ImageReport to PDF",
    description="Generate an audit-friendly PDF report from ImageReport JSON artifacts stored under /mnt/user-data.",
    response_model=ImageReportPdfResponse,
)
async def export_image_report_pdf(thread_id: str, request: ImageReportPdfRequest) -> ImageReportPdfResponse:
    cfg = get_scientific_vision_config()

    index_virtual_path = request.index_path
    index_payload: dict[str, Any] | None = None

    if index_virtual_path:
        try:
            physical = resolve_thread_virtual_path(thread_id, index_virtual_path)
            index_payload = json.loads(physical.read_text(encoding="utf-8"))
            if not isinstance(index_payload, dict):
                raise ValueError("index payload must be an object")
        except Exception as exc:
            logger.warning("Failed to read index_path=%s for thread_id=%s: %s", index_virtual_path, thread_id, exc)
            index_payload = None

    if index_payload is None:
        if request.index_payload is None:
            raise HTTPException(status_code=400, detail="Either index_path or index_payload must be provided")
        if not isinstance(request.index_payload, dict):
            raise HTTPException(status_code=400, detail="index_payload must be an object")
        index_payload = request.index_payload

    try:
        pdf_path = generate_image_report_pdf(
            thread_id=thread_id,
            index_payload=index_payload,
            artifact_subdir=cfg.artifact_subdir,
            output_filename=request.output_filename,
            index_virtual_path=index_virtual_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to export ImageReport PDF (thread_id=%s): %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to export PDF") from exc

    return ImageReportPdfResponse(pdf_path=pdf_path)


@router.post(
    "/threads/{thread_id}/reports/latex_diagnostics_markdown",
    summary="Export LaTeX diagnostics report as markdown",
    description="Persist clustered LaTeX compile diagnostics into a markdown artifact under /mnt/user-data/outputs/research-writing/latex/reports/.",
    response_model=LatexDiagnosticsMarkdownResponse,
)
async def export_latex_diagnostics_markdown(
    thread_id: str,
    request: LatexDiagnosticsMarkdownRequest,
) -> LatexDiagnosticsMarkdownResponse:
    try:
        outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        reports_rel_dir = Path("research-writing") / "latex" / "reports"
        reports_physical_dir = outputs_dir / reports_rel_dir
        reports_physical_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = request.output_filename or f"latex-diagnostics-{timestamp}.md"
        target_physical = reports_physical_dir / filename

        markdown = _build_latex_diagnostics_markdown(request, thread_id=thread_id)
        target_physical.write_text(markdown, encoding="utf-8")

        report_path = _markdown_outputs_virtual_path(reports_rel_dir / filename)
        return LatexDiagnosticsMarkdownResponse(report_path=report_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Failed to export LaTeX diagnostics markdown (thread_id=%s): %s",
            thread_id,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to export LaTeX diagnostics markdown",
        ) from exc

