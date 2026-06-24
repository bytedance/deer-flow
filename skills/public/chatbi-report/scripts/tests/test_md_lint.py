"""Unit tests for scripts/md_lint.py."""
from pathlib import Path

import pytest

import md_lint


def test_lint_happy_returns_no_errors(fixture_dir):
    """happy.md fixture 必须产生零 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert report.errors == [], f"unexpected errors: {report.errors}"


def test_lint_no_org_context_is_f19_error(fixture_dir):
    """缺 `> 机构:` 块 → F19 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_org_context.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("机构" in e.message for e in report.errors)


def test_lint_no_time_info_is_f19_error(fixture_dir):
    """缺 `> 时期:` 块 → F19 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_time_info.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("时期" in e.message for e in report.errors)


def test_lint_old_style_placeholder_is_warn_only(fixture_dir):
    """`{{BAS_0263}}` 不带 `data-idx` 属向后兼容 → WARN 而非 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    assert report.errors == []
    assert any("旧式占位符" in w.message or "old-style" in w.message.lower() for w in report.warnings)


def test_lint_chatbi_error_missing_data_idx_on_real_indicator(fixture_dir):
    """纯文本的 `<th>`（既无 `data-idx` 又无 `{{虚拟名}}`）是 chatbi ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "data-idx" in msgs or "real-indicator" in msgs.lower()


def test_lint_chatbi_error_bad_data_idx_format(fixture_dir):
    """`data-idx="bad id"` 不满足 `^[A-Z]+_\\d+$` → ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("^[A-Z]+_\\d+$" in e.message or "regex" in e.message for e in report.errors)


def test_lint_chatbi_error_computed_with_data_idx(fixture_dir):
    """`<th data-idx="BAS_0263" data-unit="%">{{收单商户同比}}</th>` 违反计算列规则
    （必须用 `{{虚拟名}}` 且不得带 `data-idx`）。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "computed" in msgs.lower() or "计算列" in msgs


def test_lint_org_block_format_error(fixture_dir):
    """`> 机构: branch_num=27020199`（无 `branch_short_name`）格式错误。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("branch_short_name" in e.message for e in report.errors)


def test_lint_time_block_format_error(fixture_dir):
    """`> 时期: time_info="2025"`（不是 JSON 数组）格式错误。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("JSON" in e.message or "time_info" in e.message for e in report.errors)


def test_lint_compute_formula_references_unknown_idx(fixture_dir):
    """`> 计算: 营收同比 = 本期MISSING_ID减...` 引用了表头集合中不存在的 idx。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("MISSING_ID" in e.message or "未查询" in e.message or "unknown" in e.message.lower() for e in report.errors)


def test_lint_main_cli_exits_nonzero_on_error(fixture_dir):
    """`python md_lint.py <bad.md>` 退出码 1。"""
    import subprocess, sys
    p = fixture_dir / "sample_md" / "lint_error.md"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "md_lint.py"), str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "ERROR" in proc.stdout or "ERROR" in proc.stderr
