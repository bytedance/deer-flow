"""Unit tests for scripts/md_lint.py."""
import subprocess
import sys
from pathlib import Path

import pytest

import md_lint


# ---------- 新格式 fixture 测试 ---------- #

def test_lint_single_org_block_passes(fixture_dir):
    """single_org.md：1 机构多行块 —— 0 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "single_org.md"))
    assert report.errors == [], f"unexpected errors: {report.errors}"


def test_lint_multi_org_block_passes(fixture_dir):
    """multi_org.md：4 机构多行块 + 多期 + 计算列带 period —— 0 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    assert report.errors == [], f"unexpected errors: {report.errors}"


def test_lint_colspan_group_header_exempt(fixture_dir):
    """multi_org.md：colspan=3 父级表头（利润总额 / 同比增速）不带 data-idx 不报错。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "利润总额" not in msgs
    assert "同比增速" not in msgs
    assert "CHATBI-DATAIDX-MISSING" not in msgs


def test_lint_period_on_computed_column_allowed(fixture_dir):
    """multi_org.md：3 个计算列 {{...}} 带 data-period —— 不报 ORPHAN。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    assert not any("CHATBI-PERIOD-ORPHAN" in e.message for e in report.errors)


# ---------- F1 / F19 / time / compute rule（tmp_path 写新格式 MD） ---------- #

def test_lint_no_org_context_is_f19_error(tmp_path):
    """缺 `> 机构:` 块 → F19 ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "F19" and "机构" in e.message for e in r.errors)


def test_lint_org_block_must_be_multi_line(tmp_path):
    """旧式单行 `> 机构: ...` 仍可解析为 multi-line 第一行 → F1 ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构: branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("multi-line format" in e.message for e in r.errors)


def test_lint_no_time_info_is_f19_error(tmp_path):
    """缺 `> 时期:` 块 → F19 ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "F19" and "时期" in e.message for e in r.errors)


def test_lint_time_block_must_be_json_array(tmp_path):
    """`> 时期: time_info=\"2025\"`（非 JSON 数组）→ F1 ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=\"2025\"\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("JSON" in e.message or "time_info" in e.message for e in r.errors)


def test_lint_compute_formula_references_unknown_idx(tmp_path):
    """`> 计算: 公式 = MISSING_ID` 引用了表头集合中不存在的 idx → ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 计算:\n"
        ">   x = 本期MISSING_ID\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th><th>{{x}}</th></tr></thead>"
        "<tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("MISSING_ID" in e.message for e in r.errors)


def test_lint_org_block_duplicate_branch_num(tmp_path):
    """同一 branch_num 重复出现 → F1 ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A1; branch_short_name=机构A\n"
        ">   branch_num=A1; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("duplicate branch_num" in e.message for e in r.errors)


# ---------- CHATBI-DATAIDX-* 测试（tmp_path） ---------- #

def test_lint_chatbi_error_missing_data_idx_on_real_indicator(tmp_path):
    """无 data-idx 又无 {{虚拟名}} 的 <th> → CHATBI-DATAIDX-MISSING ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-unit=\"个\">无属性</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("CHATBI-DATAIDX-MISSING" in e.message or "real-indicator" in e.message.lower() for e in r.errors)


def test_lint_chatbi_error_bad_data_idx_format(tmp_path):
    """`data-idx=\"bad id\"` 不满足 `^[A-Z]+_\\d+$` → CHATBI-DATAIDX-FORMAT ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-idx=\"bad id\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any("CHATBI-DATAIDX-FORMAT" in e.message or "^[A-Z]+_\\d+$" in e.message for e in r.errors)


def test_lint_chatbi_error_computed_with_data_idx(tmp_path):
    """计算列 `<th data-idx=\"...\" data-unit=\"%\">{{name}}</th>` → CHATBI-COMPUTED-WITH-IDX ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 计算:\n"
        ">   c = 本期BAS_0263\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th><th data-idx=\"BAS_0263\" data-unit=\"%\">{{c}}</th></tr></thead>"
        "<tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-COMPUTED-WITH-IDX" for e in r.errors)


# ---------- CHATBI-PERIOD-* 测试 ---------- #

def test_lint_period_required_when_data_idx_repeated(tmp_path):
    """同 data-idx 多次出现但缺 data-period → CHATBI-PERIOD-MISSING ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        ">   branch_num=B; branch_short_name=Y\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\" data-unit=\"万元\">2023</th>"
        "<th data-idx=\"BAS_0263\" data-unit=\"万元\">2024</th>"
        "</tr></thead><tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-PERIOD-MISSING" for e in r.errors)


def test_lint_period_duplicate_data_period(tmp_path):
    """同 data-idx 下两个 data-period 相同 → CHATBI-PERIOD-DUPLICATE ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        ">   branch_num=B; branch_short_name=Y\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\" data-period=\"2023\" data-unit=\"万元\">2023</th>"
        "<th data-idx=\"BAS_0263\" data-period=\"2023\" data-unit=\"万元\">2023again</th>"
        "</tr></thead><tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-PERIOD-DUPLICATE" for e in r.errors)


def test_lint_period_format_invalid(tmp_path):
    """`data-period=\"abc\"`（非 YYYY / YYYY-Qn / YYYY-Hn / YYYY-Mn）→ CHATBI-PERIOD-FORMAT ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\" data-period=\"abc\" data-unit=\"万元\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-PERIOD-FORMAT" for e in r.errors)


def test_lint_period_orphan_without_data_idx_and_not_computed(tmp_path):
    """data-period 在既无 data-idx 也非 {{name}} 的 <th> 上 → CHATBI-PERIOD-ORPHAN ERROR。"""
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "<table><thead><tr><th data-period=\"2023\" data-unit=\"万元\">孤立的</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-PERIOD-ORPHAN" for e in r.errors)


def test_lint_description_block_allows_prompt_lines(tmp_path):
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 描述:\n"
        ">   请生成经营分析描述。\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert r.errors == []
    assert not any(w.code == "CHATBI-DESC-1" for w in r.warnings)


def test_lint_description_block_warns_when_empty(tmp_path):
    md = tmp_path / "x.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 描述:\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert r.errors == []
    assert any(w.code == "CHATBI-DESC-1" for w in r.warnings)


# ---------- CLI smoke ---------- #

def test_lint_main_cli_exits_nonzero_on_error(fixture_dir):
    """`python md_lint.py <bad.md>` 退出码 1。"""
    p = fixture_dir / "sample_md" / "multi_org.md"
    # multi_org.md 现在合法（加了 data-period）—— 暂时不能直接用；改用 single_org.md 但去掉 data-period
    # 构造一个坏文件（缺 > 时期:）
    bad = p.parent / "_tmp_bad.md"
    bad.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=X\n"
        "<table><thead><tr><th data-idx=\"BAS_0263\">X</th></tr></thead>"
        "<tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "md_lint.py"), str(bad)],
        capture_output=True, text=True,
    )
    bad.unlink()
    assert proc.returncode == 1
    assert "ERROR" in proc.stdout or "ERROR" in proc.stderr


def test_lint_main_cli_exits_zero_on_clean(fixture_dir):
    """`python md_lint.py <good.md>` 退出码 0。"""
    p = fixture_dir / "sample_md" / "single_org.md"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "md_lint.py"), str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0


# ---------- chart block lint tests ---------- #

def test_lint_chart_block_missing_y(tmp_path):
    md = tmp_path / "bad_chart.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: line\n"
        ">   x轴: 时期\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\">X</th>"
        "</tr></thead><tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-CHART-MISSING" and "y轴" in e.message for e in r.errors)


def test_lint_chart_block_invalid_type(tmp_path):
    md = tmp_path / "bad_type.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: bubble\n"
        ">   x轴: 时期\n"
        ">   y轴: 利润\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\">X</th>"
        "</tr></thead><tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-CHART-TYPE" and "bubble" in e.message for e in r.errors)


def test_lint_chart_block_path_traversal_output(tmp_path):
    md = tmp_path / "bad_out.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: line\n"
        ">   x轴: 时期\n"
        ">   y轴: 利润\n"
        ">   输出: ../etc/passwd\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0263\">X</th>"
        "</tr></thead><tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-CHART-OUTPUT" and "/" in e.message for e in r.errors)


def test_lint_chart_block_bar_line_no_y_axis_error(tmp_path):
    """C2 fix: bar_line must NOT report 'missing y轴' (uses y轴左/y轴右 instead)."""
    md = tmp_path / "barline_ok.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: bar_line\n"
        ">   x轴: 行社\n"
        ">   y轴左: 贷款余额\n"
        ">   y轴右: 不良率\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0128\">贷款余额</th>"
        "<th data-idx=\"BAS_0129\">不良率</th>"
        "</tr></thead><tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    missing_errors = [e for e in r.errors if e.code == "CHATBI-CHART-MISSING"]
    assert missing_errors == [], f"unexpected missing errors: {missing_errors}"


def test_lint_chart_block_bar_line_missing_y_left(tmp_path):
    """C3 fix: bar_line missing y轴左 is caught (field is now recognized)."""
    md = tmp_path / "barline_no_left.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: bar_line\n"
        ">   x轴: 行社\n"
        ">   y轴右: 不良率\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0129\">不良率</th>"
        "</tr></thead><tbody><tr><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-CHART-MISSING" and "y轴左" in e.message for e in r.errors)


def test_lint_chart_block_invalid_color(tmp_path):
    """C3 fix: invalid color format in 条形配色 is caught."""
    md = tmp_path / "bad_color.md"
    md.write_text(
        "# T\n\n## S\n\n### R\n\n"
        "> 机构:\n"
        ">   branch_num=A; branch_short_name=机构A\n"
        "> 时期: time_info=[\"2025\"]\n"
        "> 图表:\n"
        ">   标题: A\n"
        ">   类型: bar_line\n"
        ">   x轴: 行社\n"
        ">   y轴左: 贷款余额\n"
        ">   y轴右: 不良率\n"
        ">   条形配色: notacolor\n"
        "<table><thead><tr>"
        "<th data-idx=\"BAS_0128\">贷款余额</th>"
        "<th data-idx=\"BAS_0129\">不良率</th>"
        "</tr></thead><tbody><tr><td></td><td></td></tr></tbody></table>\n",
        encoding="utf-8",
    )
    r = md_lint.lint_file(str(md))
    assert any(e.code == "CHATBI-CHART-COLOR" and "notacolor" in e.message for e in r.errors)
