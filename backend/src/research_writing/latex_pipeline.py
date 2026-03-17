"""Native LaTeX generation and optional PDF compilation pipeline."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LatexEngine = Literal["auto", "none", "latexmk", "pdflatex", "xelatex"]

_INLINE_CITATION_PATTERN = re.compile(r"\[citation:([^\]]+)\]")
_INLINE_DATA_PATTERN = re.compile(r"\[data:([^\]]+)\]")
_FIGURE_REF_PATTERN = re.compile(r"\bFigure\s+(\d+)\b")
_TABLE_REF_PATTERN = re.compile(r"\bTable\s+(\d+)\b")


@dataclass
class LatexBuildResult:
    """Output of LaTeX build and compile stages."""

    tex_file: Path
    compile_status: Literal["success", "failed", "skipped"]
    compiler: str | None
    pdf_file: Path | None
    log_file: Path
    citation_keys: list[str]
    warning: str | None = None


def _sanitize_citation_key(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "-")
    key = re.sub(r"[^a-z0-9:_\-./]", "-", key)
    key = re.sub(r"-{2,}", "-", key).strip("-")
    return key or "citation-key"


def _escape_text_for_latex(text: str) -> str:
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    escaped = []
    for char in text:
        escaped.append(mapping.get(char, char))
    return "".join(escaped)


def _transform_inline_markup(text: str, citation_keys: set[str]) -> str:
    def _citation_repl(match: re.Match[str]) -> str:
        raw_key = match.group(1)
        key = _sanitize_citation_key(raw_key)
        citation_keys.add(key)
        return rf"\cite{{{key}}}"

    def _data_repl(match: re.Match[str]) -> str:
        raw_key = _escape_text_for_latex(match.group(1))
        return rf"\texttt{{[data:{raw_key}]}}"

    transformed = _INLINE_CITATION_PATTERN.sub(_citation_repl, text)
    transformed = _INLINE_DATA_PATTERN.sub(_data_repl, transformed)
    transformed = _FIGURE_REF_PATTERN.sub(r"Figure~\\ref{fig:\1}", transformed)
    transformed = _TABLE_REF_PATTERN.sub(r"Table~\\ref{tab:\1}", transformed)
    return transformed


def markdown_to_latex(markdown_text: str) -> tuple[str, list[str]]:
    """Convert markdown-ish manuscript content into LaTeX body content."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    citation_keys: set[str] = set()
    in_code_block = False
    list_mode: Literal["none", "itemize", "enumerate"] = "none"

    def _close_list_if_needed() -> None:
        nonlocal list_mode
        if list_mode == "itemize":
            out.append(r"\end{itemize}")
        elif list_mode == "enumerate":
            out.append(r"\end{enumerate}")
        list_mode = "none"

    for raw_line in lines:
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            _close_list_if_needed()
            if not in_code_block:
                out.append(r"\begin{verbatim}")
                in_code_block = True
            else:
                out.append(r"\end{verbatim}")
                in_code_block = False
            continue

        if in_code_block:
            out.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            _close_list_if_needed()
            out.append("")
            continue

        heading_level = 0
        while heading_level < len(stripped) and stripped[heading_level] == "#":
            heading_level += 1
        if 1 <= heading_level <= 6 and heading_level < len(stripped) and stripped[heading_level] == " ":
            _close_list_if_needed()
            title = _escape_text_for_latex(stripped[heading_level + 1 :].strip())
            if heading_level == 1:
                out.append(rf"\section{{{title}}}")
            elif heading_level == 2:
                out.append(rf"\subsection{{{title}}}")
            elif heading_level == 3:
                out.append(rf"\subsubsection{{{title}}}")
            else:
                out.append(rf"\paragraph{{{title}}}")
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            if list_mode != "itemize":
                _close_list_if_needed()
                out.append(r"\begin{itemize}")
                list_mode = "itemize"
            item_text = _escape_text_for_latex(bullet_match.group(1))
            item_text = _transform_inline_markup(item_text, citation_keys)
            out.append(rf"\item {item_text}")
            continue

        number_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if number_match:
            if list_mode != "enumerate":
                _close_list_if_needed()
                out.append(r"\begin{enumerate}")
                list_mode = "enumerate"
            item_text = _escape_text_for_latex(number_match.group(1))
            item_text = _transform_inline_markup(item_text, citation_keys)
            out.append(rf"\item {item_text}")
            continue

        _close_list_if_needed()

        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            eq = stripped[2:-2].strip()
            out.append(r"\[")
            out.append(eq)
            out.append(r"\]")
            continue

        paragraph = _escape_text_for_latex(stripped)
        paragraph = _transform_inline_markup(paragraph, citation_keys)
        out.append(paragraph)

    if in_code_block:
        out.append(r"\end{verbatim}")
    if list_mode != "none":
        if list_mode == "itemize":
            out.append(r"\end{itemize}")
        else:
            out.append(r"\end{enumerate}")

    return "\n".join(out).strip(), sorted(citation_keys)


def _build_thebibliography(citation_keys: list[str]) -> str:
    if not citation_keys:
        return ""
    rows = [r"\begin{thebibliography}{99}"]
    for key in citation_keys:
        doi = key
        doi_url = doi
        if doi.startswith("10."):
            doi_url = f"https://doi.org/{doi}"
        rows.append(rf"\bibitem{{{key}}} Citation key: \texttt{{{_escape_text_for_latex(key)}}}. \url{{{doi_url}}}")
    rows.append(r"\end{thebibliography}")
    return "\n".join(rows)


def build_tex_document(
    *,
    title: str,
    body_latex: str,
    abstract_text: str | None = None,
    authors: list[str] | None = None,
    citation_keys: list[str] | None = None,
) -> str:
    """Build full LaTeX manuscript document."""
    safe_title = _escape_text_for_latex(title.strip() or "Untitled Manuscript")
    safe_authors = ", ".join(_escape_text_for_latex(item.strip()) for item in (authors or []) if item.strip()) or "DeerFlow"
    abstract_block = ""
    if abstract_text and abstract_text.strip():
        abstract_body = _escape_text_for_latex(abstract_text.strip())
        abstract_block = f"\\begin{{abstract}}\n{abstract_body}\n\\end{{abstract}}\n"
    bibliography_block = _build_thebibliography(citation_keys or [])
    return (
        r"\documentclass[11pt]{article}"
        "\n"
        r"\usepackage[utf8]{inputenc}"
        "\n"
        r"\usepackage[a4paper,margin=1in]{geometry}"
        "\n"
        r"\usepackage{amsmath,amssymb}"
        "\n"
        r"\usepackage{graphicx}"
        "\n"
        r"\usepackage{booktabs}"
        "\n"
        r"\usepackage{longtable}"
        "\n"
        r"\usepackage{url}"
        "\n"
        r"\usepackage{hyperref}"
        "\n\n"
        rf"\title{{{safe_title}}}"
        "\n"
        rf"\author{{{safe_authors}}}"
        "\n"
        r"\date{\today}"
        "\n\n"
        r"\begin{document}"
        "\n"
        r"\maketitle"
        "\n"
        f"{abstract_block}"
        f"{body_latex}\n\n"
        f"{bibliography_block}\n"
        r"\end{document}"
        "\n"
    )


def _resolve_engine(engine: LatexEngine) -> tuple[str | None, list[str]]:
    if engine == "none":
        return None, []
    if engine == "auto":
        for candidate in ("latexmk", "pdflatex", "xelatex"):
            if shutil.which(candidate):
                if candidate == "latexmk":
                    return candidate, [candidate, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]
                return candidate, [candidate, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]
        return None, []
    if shutil.which(engine) is None:
        return None, []
    if engine == "latexmk":
        return engine, [engine, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]
    return engine, [engine, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]


def compile_tex_project(
    *,
    tex_file: Path,
    engine: LatexEngine = "auto",
    compile_pdf: bool = True,
    timeout_seconds: int = 120,
) -> tuple[Literal["success", "failed", "skipped"], str | None, Path | None, str]:
    """Compile `.tex` into PDF using local TeX engine if available."""
    log_lines: list[str] = []
    if not compile_pdf:
        return "skipped", None, None, "Compilation skipped by request."

    resolved_engine, cmd = _resolve_engine(engine)
    if not resolved_engine or not cmd:
        return "skipped", None, None, "No LaTeX engine found (checked latexmk/pdflatex/xelatex)."

    work_dir = tex_file.parent
    tex_name = tex_file.name
    pdf_file = tex_file.with_suffix(".pdf")
    runs = 2 if resolved_engine in {"pdflatex", "xelatex"} else 1

    for idx in range(runs):
        run_cmd = [*cmd, tex_name]
        try:
            result = subprocess.run(
                run_cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_lines.append(f"[run {idx + 1}] timeout: {exc}")
            return "failed", resolved_engine, None, "\n".join(log_lines)

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        log_lines.append(f"[run {idx + 1}] command: {' '.join(run_cmd)}")
        if stdout.strip():
            log_lines.append(stdout)
        if stderr.strip():
            log_lines.append(stderr)
        if result.returncode != 0:
            log_lines.append(f"[run {idx + 1}] return code={result.returncode}")
            return "failed", resolved_engine, None, "\n".join(log_lines)

    if pdf_file.exists():
        return "success", resolved_engine, pdf_file, "\n".join(log_lines)
    log_lines.append("Compilation command succeeded but PDF file is missing.")
    return "failed", resolved_engine, None, "\n".join(log_lines)


def build_latex_artifacts(
    *,
    output_dir: Path,
    output_stem: str,
    title: str,
    markdown_text: str,
    abstract_text: str | None = None,
    authors: list[str] | None = None,
    engine: LatexEngine = "auto",
    compile_pdf: bool = True,
    compile_timeout_seconds: int = 120,
) -> LatexBuildResult:
    """Generate `.tex` from markdown and optionally compile to PDF."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tex_file = output_dir / f"{output_stem}.tex"
    log_file = output_dir / f"{output_stem}.compile.log"

    body_latex, citation_keys = markdown_to_latex(markdown_text)
    tex_payload = build_tex_document(
        title=title,
        body_latex=body_latex,
        abstract_text=abstract_text,
        authors=authors,
        citation_keys=citation_keys,
    )
    tex_file.write_text(tex_payload, encoding="utf-8")

    status, compiler, pdf_file, log_text = compile_tex_project(
        tex_file=tex_file,
        engine=engine,
        compile_pdf=compile_pdf,
        timeout_seconds=compile_timeout_seconds,
    )
    warning = None
    if status != "success" and compile_pdf:
        warning = "LaTeX compile did not produce PDF; see compile log."
    log_file.write_text(log_text, encoding="utf-8")
    return LatexBuildResult(
        tex_file=tex_file,
        compile_status=status,
        compiler=compiler,
        pdf_file=pdf_file,
        log_file=log_file,
        citation_keys=citation_keys,
        warning=warning,
    )
