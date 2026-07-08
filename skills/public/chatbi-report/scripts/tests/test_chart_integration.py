"""chart_integration — End-to-end coverage for the chart integration plan.

Verifies the wiring between parse_md, chart_gen, render_docx:

  1. Each input fixture (bar-grouped, line-trend, pie-composition,
     bar-line-colors) parses its `> 图表:` blocks into ChartSpec lists
     (test_parse_each_fixture_extracted_expected_chart_count).
  2. chart_gen.generate_charts() against a constructed wide produces
     a manifest with the right `ok`/`failed` counts and writes PNGs
     at the expected relative paths (test_chart_gen_runs_for_each_fixture).
  3. input-01.md (no `> 图表:` blocks) produces status="NO_CHARTS" and
     chart_manifest.reports have empty `charts` lists
     (test_no_charts_fixture_writes_no_charts).
  4. render_docx() embeds chart PNGs at the matching (section_idx,
     report_idx) positions when a chart_manifest is passed
     (test_render_docx_embeds_chart_when_manifest_provided).

These tests do NOT exercise Phase 1 / Phase 2 Orchestrator wiring — that
is covered by the existing E2E tests and the manual single-script run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import chart_gen as cg
import parse_md as pm
import render_docx as rd

EXAMPLES = Path(__file__).parents[2] / "example"


def _parse_fixture(name: str) -> pm.ReportDoc:
    return pm.parse_markdown((EXAMPLES / name).read_text(encoding="utf-8"))


def _minimal_wide(*, section_idx: int, report_idx: int, org_count: int) -> list[dict]:
    """Build a wide list of placeholder rows for one report.

    Includes dummy values for common indicator/period combos used by the
    chart fixtures (BAS_0128 / BAS_0130 / BAS_0129 / BAS_0131 at 2025,
    BAS_0263 at 2023-2025) so chart series resolution can find leaves.
    """
    return [
        {
            "section_idx": section_idx,
            "report_idx": report_idx,
            "branch_num": f"270{2010000 + n:07d}",
            "BAS_0263@2023": 100 + n,
            "BAS_0263@2024": 120 + n,
            "BAS_0263@2025": 150 + n,
            "BAS_0128@2025": 1000 + n * 50,
            "BAS_0130@2025": 500 + n * 30,
            "BAS_0129@2025": 0.05 + n * 0.01,
            "BAS_0131@2025": 0.10 + n * 0.02,
        }
        for n in range(org_count)
    ]


# ---------- 1. parse_md extracts chart_specs ---------- #


def test_parse_bar_grouped_has_two_chart_specs():
    doc = _parse_fixture("input-bar-grouped.md")
    reports = doc.sections[0].reports
    assert len(reports) == 1
    assert len(reports[0].chart_specs) == 2
    titles = [c.标题 for c in reports[0].chart_specs]
    assert "贷款余额对比" in titles
    assert "存款日均净增对比" in titles


def test_parse_bar_line_colors_has_one_bar_line_chart():
    doc = _parse_fixture("input-bar-line-colors.md")
    report = doc.sections[0].reports[0]
    assert len(report.chart_specs) == 1
    chart = report.chart_specs[0]
    assert chart.类型 == "bar_line"
    assert "贷款余额" in (chart.y轴左 or [])
    assert "不良率" in (chart.y轴右 or [])
    assert chart.条形配色 == ["#3498db", "#2ecc71"]
    assert chart.折线配色 == ["#e74c3c", "#f39c12"]


def test_parse_pie_composition_has_one_pie_chart():
    doc = _parse_fixture("input-pie-composition.md")
    report = doc.sections[0].reports[0]
    assert len(report.chart_specs) == 1
    assert report.chart_specs[0].类型 == "pie"


def test_parse_line_trend_has_one_line_chart():
    doc = _parse_fixture("input-line-trend.md")
    report = doc.sections[0].reports[0]
    assert len(report.chart_specs) == 1
    assert report.chart_specs[0].类型 == "line"


def test_parse_input01_has_zero_chart_specs():
    doc = _parse_fixture("input-01.md")
    for section in doc.sections:
        for report in section.reports:
            assert report.chart_specs == [], (
                f"input-01.md report `{report.title}` should have no chart specs"
            )


# ---------- 2. chart_gen runs against parsed fixture ---------- #


def test_chart_gen_for_bar_grouped(tmp_path):
    doc = _parse_fixture("input-bar-grouped.md")
    parsed = {
        "title": doc.title,
        "sections": [
            {"title": s.title,
             "reports": [
                 {
                     "title": r.title,
                     "org_contexts": r.to_dict()["org_contexts"],
                     "time_info": r.to_dict()["time_info"],
                     "headers": [[c.to_dict() for c in row] for row in r.headers],
                     "data_rows": [],
                     "computed_specs": [],
                     "chart_specs": [c.to_dict() for c in r.chart_specs],
                 }
                 for r in s.reports
             ]}
            for s in doc.sections
        ],
    }
    wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)
    manifest = cg.generate_charts(
        parsed, wide, str(tmp_path / "charts"),
        str(tmp_path / "charts.json"), stem="input-bar-grouped",
    )
    summary = manifest["summary"]
    assert summary["status"] == "OK"
    assert summary["ok"] == 2
    assert summary["failed"] == 0
    png_files = sorted((tmp_path / "charts").glob("*.png"))
    assert len(png_files) == 2
    slugs = sorted(p.stem for p in png_files)
    assert "s0r0-loan-balance-bar" in slugs
    assert "s0r0-deposit-incr-bar" in slugs


def test_chart_gen_for_no_charts_fixture(tmp_path):
    doc = _parse_fixture("input-01.md")
    parsed = {
        "title": doc.title,
        "sections": [
            {"title": s.title,
             "reports": [
                 {
                     "title": r.title,
                     "org_contexts": r.to_dict()["org_contexts"],
                     "time_info": r.to_dict()["time_info"],
                     "headers": [[c.to_dict() for c in row] for row in r.headers],
                     "data_rows": [],
                     "computed_specs": [],
                     "chart_specs": [],
                 }
                 for r in s.reports
             ]}
            for s in doc.sections
        ],
    }
    wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)
    manifest = cg.generate_charts(
        parsed, wide, str(tmp_path / "charts"),
        str(tmp_path / "charts.json"), stem="input-01",
    )
    summary = manifest["summary"]
    assert summary["status"] == "NO_CHARTS"
    assert summary["ok"] == 0
    assert summary["failed"] == 0
    png_files = list((tmp_path / "charts").glob("*.png"))
    assert png_files == [], "NO_CHARTS should not emit any PNG"


# ---------- 3. render_docx embeds charts when manifest is passed ---------- #


def test_render_docx_embeds_chart_when_manifest_provided(tmp_path):
    """Verify that render_docx places a chart PNG under the matching report."""
    # 1. Parse a fixture with one bar chart
    doc = _parse_fixture("input-pie-composition.md")
    parsed = {
        "title": doc.title,
        "sections": [
            {"title": s.title,
             "reports": [
                 {
                     "title": r.title,
                     "org_contexts": r.to_dict()["org_contexts"],
                     "time_info": r.to_dict()["time_info"],
                     "headers": [[c.to_dict() for c in row] for row in r.headers],
                     "data_rows": [],
                     "computed_specs": [],
                     "chart_specs": [c.to_dict() for c in r.chart_specs],
                 }
                 for r in s.reports
             ]}
            for s in doc.sections
        ],
    }
    wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)

    # 2. Generate chart manifest to tmp_path
    chart_dir = tmp_path / "charts"
    chart_manifest_path = tmp_path / "input-pie-composition.charts.json"
    manifest = cg.generate_charts(
        parsed, wide, str(chart_dir), str(chart_manifest_path),
        stem="input-pie-composition",
    )

    # 3. Reconstruct ReportDoc from parsed (verify doc_from_dict round-trips
    # ChartSpec field — the fix at render_markdown:doc_from_dict).
    report_doc = pm.parse_markdown(
        (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
    )
    assert len(report_doc.sections[0].reports[0].chart_specs) == 1, (
        "doc_from_dict MUST rebuild chart_specs; "
        "if this fails, render_markdown:doc_from_dict regressed"
    )

    # 4. Now render the DOCX with chart_manifest wired through.
    style_path = EXAMPLES / "style.json"
    out_path = tmp_path / "report.docx"
    wide_by_report = [
        [{"data_dt": "", "org_ecd": "王益", "branch_num": r["branch_num"],
          "cells": {}, "raw_cells": []} for r in wide]
    ]
    rd.render_docx(
        report_doc, wide_by_report, out_path=str(out_path),
        style_path=str(style_path), chart_manifest=manifest,
    )
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    # The DOCX should contain at least one image relationship; check the
    # raw zip for `word/media/` entries.
    import zipfile
    with zipfile.ZipFile(str(out_path)) as zf:
        media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert any(m.endswith(".png") for m in media_files), (
        f"DOCX should embed at least one PNG; got {media_files}"
    )


def test_render_docx_skips_chart_when_manifest_absent(tmp_path):
    """Without chart_manifest, no PNG embedding attempted."""
    doc = pm.parse_markdown(
        (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
    )
    style_path = EXAMPLES / "style.json"
    out_path = tmp_path / "report.docx"
    wide_by_report = [
        [{"data_dt": "", "org_ecd": "王益", "branch_num": "27020199",
          "cells": {}, "raw_cells": []}]
    ]
    rd.render_docx(
        doc, wide_by_report, out_path=str(out_path),
        style_path=str(style_path), chart_manifest=None,
    )
    assert out_path.exists()
    import zipfile
    with zipfile.ZipFile(str(out_path)) as zf:
        media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert media_files == [], (
        f"DOCX should NOT embed PNGs when chart_manifest=None; got {media_files}"
    )


# ---------- 4. End-to-end via Orchestrator (lightweight) ---------- #


def test_orchestrator_writes_chart_manifest_for_chart_fixture(tmp_path):
    """Verify pipeline.run_phase_2 writes {stem}.charts.json when input has charts.

    Uses ForceContinue(skip_lint_checkpoint=True, skip_query_checkpoint=True)
    so that idx_ids absent from the MockSQLBot fixture don't block Phase 1.
    Then runs Phase 2 with no compute sources and no descriptions; the chart
    step runs in Step 8c.5 BEFORE attach-description so we get the manifest.
    """
    from sqlbot_client import MockSQLBotClient

    import pipeline as p

    cfg = p.OrchestratorConfig(
        md_path=EXAMPLES / "input-bar-grouped.md",
        out_dir=tmp_path,
    )
    mock_client = MockSQLBotClient(
        str(EXAMPLES / "mock_sqlbot" / "profit_yoy.json")
    )
    orch = p.Orchestrator(cfg, mock_client)

    p1 = orch.run_phase_1(
        force_continue=p.ForceContinue(
            skip_lint_checkpoint=True, skip_query_checkpoint=True,
        ),
    )
    assert isinstance(p1, p.Phase1Result), f"got {type(p1).__name__}: {p1}"

    descriptions_dir = tmp_path / "desc"
    descriptions_dir.mkdir()
    stem = (EXAMPLES / "input-bar-grouped.md").stem
    # No descriptions — the chart step still runs because it's before Step 8d.5
    # description checkpoint; the orchestrator will return CheckpointSignal
    # at 8d.5, having already produced the chart_manifest on disk.

    result = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={},
        descriptions_dir=str(descriptions_dir),
        stem=stem,
    )
    # Result is CheckpointSignal because no description files; chart_manifest
    # has been written to disk by Step 8c.5 before 8d.5 fires.
    assert isinstance(result, p.CheckpointSignal), (
        f"expected CheckpointSignal at 8d.5 (no description files), "
        f"got {type(result).__name__}"
    )

    chart_manifest_path = tmp_path / f"{stem}.charts.json"
    assert chart_manifest_path.exists(), (
        f"Step 8c.5 should have written chart_manifest to {chart_manifest_path}"
    )
    manifest = json.loads(chart_manifest_path.read_text(encoding="utf-8"))
    report_entries = manifest.get("reports", [])
    assert len(report_entries) >= 1
    charts = report_entries[0].get("charts", [])
    assert len(charts) == 2, (
        f"expected 2 chart entries (one per chart_spec), "
        f"got {len(charts)}: {charts}"
    )


# ---------- Defect 1: silent failure when chart_manifest is missing ---------- #


def test_render_docx_warns_when_chart_manifest_missing(tmp_path, capsys):
    """Defect 1: when chart_manifest_path doesn't exist (e.g., Step 8c.5 raised),
    render_docx MUST emit a stderr warning instead of silently shipping a
    chart-less DOCX.

    We exercise the warning emission by patching render_docx's stderr print
    is captured via capsys.
    """
    # No chart_manifest_path, no chart_dir, no manifest — emulate Step 8c.5 raised.
    doc = pm.parse_markdown(
        (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
    )
    style_path = EXAMPLES / "style.json"
    out_path = tmp_path / "report.docx"
    wide_by_report = [[]]
    rd.render_docx(
        doc, wide_by_report, out_path=str(out_path),
        style_path=str(style_path), chart_manifest=None, chart_dir=None,
    )
    # Plain render_docx without an orchestrator-side wrapper doesn't get the
    # orchestrator's stderr warning (that's emitted in _finish_phase_2). The
    # wiring contract is that render_docx itself only embeds when manifest
    # is provided. Test that no false-positive warning fires when manifest=None.
    captured = capsys.readouterr()
    assert "WARN: chart_manifest missing" not in captured.err, (
        f"render_docx should NOT emit orchestrator-level warning; that's "
        f"_finish_phase_2's job. Got: {captured.err!r}"
    )


def test_orchestrator_warns_when_chart_manifest_missing(tmp_path, capsys):
    """Defect 1: end-to-end — when chart_gen raises inside Step 8c.5, the
    orchestrator writes a sidecar with the error and _finish_phase_2 surfaces
    it to stderr (not silently producing a chart-less DOCX).
    """
    # 1. Patch chart_gen.generate_charts at the module level so the orchestrator's
    #    lazy import inside Step 8c.5 picks up the patched version.
    import pipeline as p
    import chart_gen as cg_module

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated chart_gen failure")
    original = cg_module.generate_charts
    cg_module.generate_charts = _explode
    try:
        cfg = p.OrchestratorConfig(
            md_path=EXAMPLES / "input-pie-composition.md",
            out_dir=tmp_path,
        )
        mock_client = type("M", (), {
            "__init__": lambda s: None,
        })()
        orch = p.Orchestrator(cfg, mock_client)

        # 2. Force phase 1 to materialize a minimal Phase1Result so we can
        #    drive phase 2 directly without faking SQLBot.
        #    Build a minimal parsed dict + wide rows manually.
        doc = pm.parse_markdown(
            (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
        )
        parsed = doc.to_dict()
        wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)
        descriptions_dir = tmp_path / "desc"
        descriptions_dir.mkdir()
        stem = (EXAMPLES / "input-pie-composition.md").stem
        # Write description file so 8d/8d.5 don't block.
        (descriptions_dir / f"{stem}.description.report-0.txt").write_text(
            "test description", encoding="utf-8"
        )

        # 3. Run phase 2 — Step 8c.5 will raise (patched), but orchestrator
        #    catches it and writes sidecar; _finish_phase_2 should then warn
        #    to stderr.
        result = orch.run_phase_2(
            parsed=parsed, wide=wide,
            compute_sources={}, descriptions_dir=str(descriptions_dir),
            stem=stem,
        )
        # 4. The run should still produce a RunResult (not checkpoint) because
        #    descriptions are present and Step 8c/8d don't fail.
        assert isinstance(result, p.RunResult), f"got {type(result).__name__}"
        assert result.report_docx is not None
        assert result.report_docx.exists()

        # 5. The sidecar carries the 8c.5 error
        sidecar = json.loads(
            (tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8")
        )
        assert sidecar["chart_gen"]["status"] == "ERROR"
        assert "simulated chart_gen failure" in sidecar["chart_gen"]["error"]

        # 6. Defect 1: stderr warning was emitted
        captured = capsys.readouterr()
        assert "Step 8c.5 raised" in captured.err, (
            f"expected Defect 1 warning; got stderr: {captured.err!r}"
        )
    finally:
        cg_module.generate_charts = original


# ---------- Defect 2: path traversal + cross-process path resolution ---------- #


def test_resolve_chart_png_rejects_escape(tmp_path):
    """Defect 2: a malicious absolute `path` outside chart_dir must be rejected
    even when chart_dir is provided.
    """
    out_dir = tmp_path / "out"
    chart_dir = out_dir / "input.charts"
    chart_dir.mkdir(parents=True)
    # A real escape attempt: chart_entry says the PNG lives at /etc/passwd.
    bad_entry = {
        "title": "escape",
        "status": "ok",
        "path": "/etc/passwd",
        "relative_path": "input.charts/foo.png",  # benign fallback
    }
    resolved = rd._resolve_chart_png(bad_entry, chart_dir=chart_dir)
    assert resolved is None, (
        f"path-traversal must be rejected; got {resolved}"
    )


def test_resolve_chart_png_accepts_relative_path_basename(tmp_path):
    """Defect 2: chart_dir + relative_path → basename only. A relative_path
    with directory components (e.g. `../../etc/passwd`) is reduced to its
    basename and joined with chart_dir, so traversal cannot escape.
    """
    out_dir = tmp_path / "out"
    chart_dir = out_dir / "input.charts"
    chart_dir.mkdir(parents=True)

    # Even though relative_path LOOKS malicious, basename extraction neutralizes it.
    legit_png = chart_dir / "passwd"
    legit_png.write_bytes(b"x")

    entry = {
        "title": "escape",
        "status": "ok",
        "path": "/wrong/path",
        "relative_path": "../../etc/passwd",
    }
    resolved = rd._resolve_chart_png(entry, chart_dir=chart_dir)
    # Falls into chart_dir; the embedded file is a benign fixture file at chart_dir/passwd.
    assert resolved == legit_png.resolve(), (
        f"relative_path should be reduced to basename inside chart_dir; got {resolved}"
    )


def test_resolve_chart_png_uses_relative_path(tmp_path):
    """Defect 2: when both relative_path and chart_dir are available, the PNG
    path is resolved from relative_path + chart_dir (cross-process safe,
    not from absolute `path`).
    """
    out_dir = tmp_path / "out"
    chart_dir = out_dir / "input.charts"
    chart_dir.mkdir(parents=True)
    real_png = chart_dir / "foo.png"
    real_png.write_bytes(b"fake-png")

    entry = {
        "title": "loan",
        "status": "ok",
        # Absolute path is wrong (different machine), but relative_path is right.
        "path": "/wrong/machine/foo.png",
        "relative_path": "input.charts/foo.png",
    }
    resolved = rd._resolve_chart_png(entry, chart_dir=str(chart_dir))
    assert resolved == real_png.resolve(), (
        f"relative_path resolution broken; resolved to {resolved}, expected {real_png.resolve()}"
    )


def test_render_docx_embeds_when_only_relative_path_valid(tmp_path):
    """Defect 2: when chart_gen's absolute `path` is bogus (e.g., manifest moved
    across a path remap), render_docx should still embed via relative_path.
    """
    doc = pm.parse_markdown(
        (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
    )
    parsed = {
        "title": doc.title,
        "sections": [
            {"title": s.title,
             "reports": [
                 {
                     "title": r.title,
                     "org_contexts": r.to_dict()["org_contexts"],
                     "time_info": r.to_dict()["time_info"],
                     "headers": [[c.to_dict() for c in row] for row in r.headers],
                     "data_rows": [],
                     "computed_specs": [],
                     "chart_specs": [c.to_dict() for c in r.chart_specs],
                 }
                 for r in s.reports
             ]}
            for s in doc.sections
        ],
    }
    wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)
    chart_dir = tmp_path / "charts"
    chart_manifest_path = tmp_path / "input-pie-composition.charts.json"
    manifest = cg.generate_charts(
        parsed, wide, str(chart_dir), str(chart_manifest_path),
        stem="input-pie-composition",
    )

    # Simulate path-traversal attack: rewrite manifest's `path` to a bogus
    # location but keep `relative_path` intact.
    for rep in manifest.get("reports", []):
        for ch in rep.get("charts", []):
            ch["path"] = "/completely/wrong/dir/foo.png"
            ch["relative_path"] = "input.charts/foo.png"  # overwritten below

    # Re-derive relative_path to use the same stem as the manifest.
    stem = "input-pie-composition"
    slug_part = list((chart_dir).iterdir())[0].name  # the actual PNG filename
    for rep in manifest.get("reports", []):
        for ch in rep.get("charts", []):
            ch["relative_path"] = f"{stem}.charts/{slug_part}"

    style_path = EXAMPLES / "style.json"
    out_path = tmp_path / "report.docx"
    report_doc = pm.parse_markdown(
        (EXAMPLES / "input-pie-composition.md").read_text(encoding="utf-8")
    )
    wide_by_report = [
        [{"data_dt": "", "org_ecd": "王益", "branch_num": r["branch_num"],
          "cells": {}, "raw_cells": []} for r in wide]
    ]
    rd.render_docx(
        report_doc, wide_by_report, out_path=str(out_path),
        style_path=str(style_path), chart_manifest=manifest,
        chart_dir=str(chart_dir),
    )
    assert out_path.exists()
    import zipfile
    with zipfile.ZipFile(str(out_path)) as zf:
        media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert any(m.endswith(".png") for m in media_files), (
        f"DOCX should embed despite bogus absolute path; got {media_files}"
    )


# ---------- Defect 3: slug uniqueness across reports ---------- #


def test_chart_gen_namespaces_slugs_by_section_report():
    """Defect 3: two reports with the same `输出:` slug must produce distinct
    PNGs (and manifest `path` fields), otherwise the second PNG overwrites
    the first and `_embed_chart` would embed the wrong chart in the wrong
    section.
    """
    parsed = {
        "title": "T",
        "sections": [
            {"title": "S1", "reports": [
                {"title": "R1", "org_contexts": [],
                 "time_info": ["2025"],
                 "headers": [
                     [{"text": "行社", "is_indicator": False, "is_computed": False},
                      {"text": "贷款余额", "is_indicator": True, "is_computed": False,
                       "idx_id": "BAS_0128", "period": "2025", "data_unit": "万元"}],
                 ],
                 "data_rows": [], "computed_specs": [],
                 "chart_specs": [{"标题": "贷款对比", "类型": "bar", "x轴": "行社",
                                  "y轴": "贷款余额", "输出": "loan"}],
                 },
            ]},
            {"title": "S2", "reports": [
                {"title": "R2", "org_contexts": [],
                 "time_info": ["2025"],
                 "headers": [
                     [{"text": "行社", "is_indicator": False, "is_computed": False},
                      {"text": "贷款余额", "is_indicator": True, "is_computed": False,
                       "idx_id": "BAS_0128", "period": "2025", "data_unit": "万元"}],
                 ],
                 "data_rows": [], "computed_specs": [],
                 "chart_specs": [{"标题": "贷款对比", "类型": "bar", "x轴": "行社",
                                  "y轴": "贷款余额", "输出": "loan"}],
                 },
            ]},
        ],
    }
    import tempfile
    wide = _minimal_wide(section_idx=0, report_idx=0, org_count=4)
    # Add second report's wide rows
    wide_s2 = _minimal_wide(section_idx=1, report_idx=0, org_count=4)
    wide_s2 = [{**r, "section_idx": 1, "report_idx": 0} for r in wide_s2]
    wide_all = wide + wide_s2
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        manifest = cg.generate_charts(
            parsed, wide_all, str(td_path / "charts"),
            str(td_path / "m.json"), stem="input",
        )
        paths = {
            ch.get("path") for rep in manifest["reports"] for ch in rep["charts"]
        }
        assert len(paths) == 2, (
            f"two reports with same `输出: loan` must yield distinct PNG paths; "
            f"got {paths}"
        )
        png_files = sorted((td_path / "charts").glob("*.png"))
        assert len(png_files) == 2
        assert png_files[0].stem != png_files[1].stem
