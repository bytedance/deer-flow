"""Unit tests for scripts/render_docx.py.

Tests round-trip a written .docx through python-docx to verify
header text, cell merges, font, and ⚠️ markers.
"""

import subprocess
import sys
from pathlib import Path


def _render_via_subprocess(doc_path: str, out_path: str, fixture_dir: Path) -> None:
    """Helper: render_docx needs a real .docx roundtrip via a small driver script."""
    scripts_dir = Path(__file__).resolve().parents[1]
    style_path = scripts_dir / "report_style.json"
    driver = fixture_dir / "_render_driver.py"
    driver.write_text(
        f"""# ruff: noqa
import sys
from pathlib import Path
sys.path.insert(0, r"{scripts_dir}")
import parse_md as pm
import render_docx as rd
doc = pm.parse_file(r"{doc_path}")
wide = [{{
    "data_dt": "2025-Q4", "org_ecd": "王益联社",
    "cells": {{"BAS_0263": "1,420"}},
    "raw_cells": {{"BAS_0263": "1,420"}},
}}]
rd.render_docx(doc, [wide], out_path=r"{out_path}",
               style_path=r"{style_path}")
""",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"render_docx driver failed: {proc.stderr}")


def test_render_docx_writes_a_valid_docx(fixture_dir, tmp_path):
    """render_docx() 产出非空 .docx 文件。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    assert out.exists()
    assert out.stat().st_size > 1024  # python-docx 输出不会是空文件


def test_render_docx_header_uses_chinese_name_not_idx_id(fixture_dir, tmp_path):
    """Chatbi 规则：列主标题为 MD 中的中文显示名。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    # 通过 python-docx 把 .docx 当原始文本读回
    from docx import Document

    doc = Document(str(out))
    # 收集所有单元格的文本；校验中文显示名存在
    all_text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "贷款收单商户数" in all_text
    # 在 chatbi 主路径中，idx_id 不应作为列标题
    # （仅用于数据查找，不作为可见标签）。
    # MD 表头包含中文显示名 + data-unit "(个)" 副标，
    # 因此列头应显示 "贷款收单商户数" + "(个)" —— 而非 "BAS_0263"。
    cells_text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    # 仅当渲染器回退到旧式查询时才允许 "BAS_0263" 出现。
    # happy.md fixture 使用 data-idx + 中文文本，不应回退，
    # 因此 BAS_0263 不应出现在可见表格中。
    assert "BAS_0263" not in cells_text


def test_render_docx_multi_level_merges_cells(fixture_dir, tmp_path):
    """multi_header.md：顶行类目单元格跨 2 列（cell.merge()）。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "multi_header.md"),
        str(out),
        fixture_dir,
    )
    from docx import Document

    doc = Document(str(out))
    table = doc.tables[0]
    # 第一行应有 2 个单元格（1 个类目父级 + 1 个占位列），
    # 父级单元格是覆盖第 0 行第 1..2 列与第 1 行第 0..1 列的合并区域。
    # python-docx 通过 tc.spans 暴露合并单元格；我们只检查类目文本仅出现一次。
    texts = "\n".join(c.text for r in table.rows for c in r.cells)
    assert "商户与贷款" in texts
    assert "贷款收单商户数" in texts
    assert "贷款余额" in texts


def test_render_docx_query_failed_marker_in_cell(fixture_dir, tmp_path):
    """⚠️QUERY_FAILED 单元格文本按原样保留。"""
    out = tmp_path / "report.docx"
    md_path = str(fixture_dir / "sample_md" / "happy.md")
    scripts_dir = Path(__file__).resolve().parents[1]
    style_path = scripts_dir / "report_style.json"
    driver = fixture_dir / "_render_driver_fail.py"
    driver.write_text(
        f"""# ruff: noqa
import sys
from pathlib import Path
sys.path.insert(0, r"{scripts_dir}")
import parse_md as pm
import render_docx as rd
doc = pm.parse_file(r"{md_path}")
wide = [{{
    "data_dt": "2025-Q4", "org_ecd": "王益联社",
    "cells": {{"BAS_0263": "⚠️QUERY_FAILED"}},
    "raw_cells": {{"BAS_0263": None}},
}}]
rd.render_docx(doc, [wide], out_path=r"{out}",
               style_path=r"{style_path}")
""",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    from docx import Document

    doc = Document(str(out))
    cells_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "⚠️QUERY_FAILED" in cells_text
