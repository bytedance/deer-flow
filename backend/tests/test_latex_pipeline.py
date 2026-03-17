"""Tests for native LaTeX manuscript pipeline."""

from __future__ import annotations

from unittest.mock import patch

from src.config.paths import Paths
from src.research_writing.latex_pipeline import build_latex_artifacts, markdown_to_latex
from src.research_writing.project_state import ResearchProject, SectionDraft
from src.research_writing.runtime_service import build_latex_manuscript, upsert_project


def test_markdown_to_latex_transforms_citations_and_crossrefs():
    body, citation_keys = markdown_to_latex(
        "# Results\n\nWe report a gain [citation:10.1000/demo] with evidence [data:ev-1].\n\nSee Figure 2 and Table 3.\n\n- item one",
    )
    assert r"\section{Results}" in body
    assert r"\cite{10.1000/demo}" in body
    assert r"\texttt{[data:ev-1]}" in body
    assert r"Figure~\ref{fig:2}" in body
    assert r"Table~\ref{tab:3}" in body
    assert citation_keys == ["10.1000/demo"]


def test_build_latex_artifacts_without_compile(tmp_path):
    result = build_latex_artifacts(
        output_dir=tmp_path,
        output_stem="paper-demo",
        title="Demo Paper",
        markdown_text="## Intro\n\nHello world.",
        compile_pdf=False,
        engine="auto",
    )
    assert result.compile_status == "skipped"
    assert result.tex_file.exists()
    assert result.log_file.exists()
    assert "Compilation skipped by request" in result.log_file.read_text(encoding="utf-8")


def test_runtime_build_latex_manuscript_from_project(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread-latex"
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id="p-latex",
                title="Latex Pipeline Project",
                discipline="ai_cs",
                sections=[
                    SectionDraft(
                        section_id="intro",
                        section_name="Introduction",
                        content="This is a markdown section with [citation:10.1000/demo].",
                    )
                ],
            ),
        )
        payload = build_latex_manuscript(
            thread_id,
            project_id="p-latex",
            section_ids=["intro"],
            compile_pdf=False,
            engine="none",
            output_name="p-latex-intro",
        )

    assert payload["project_id"] == "p-latex"
    assert payload["compile_status"] == "skipped"
    assert payload["tex_path"].endswith(".tex")
    assert payload["source_markdown_path"].endswith(".source.md")
    assert payload["summary_artifact_path"].endswith(".json")
    assert payload["latex_quality_gate"]["schema_version"] == "deerflow.engineering_gates.v1"
    assert "compile_status_distribution" in payload["latex_quality_gate"]
    assert "compile_failure_type_clusters" in payload["latex_quality_gate"]
    assert payload["latex_quality_gate_artifact_path"].endswith("latex-gates.json")
