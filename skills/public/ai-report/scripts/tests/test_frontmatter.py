from pathlib import Path

import pytest

from ai_report.frontmatter import merge_table_designs, parse_table_md, parse_table_md_dir


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_table_md_extracts_required_frontmatter(tmp_path: Path):
    md = _write(tmp_path / "deposit_balance.md", """---
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告
section_key: deposit_loan
section_title: 二、存贷款业务情况
section_order: 20
table_id: deposit_balance
table_title: 存款余额表
table_order: 10
---

### 存款余额表

| branch | value |
|---|---|
""")
    partial = parse_table_md(md)

    assert partial["report"]["report_id"] == "business_analysis"
    assert partial["report"]["report_title"] == "2024年经营分析报告"
    assert partial["sections"][0]["section_id"] == "deposit_loan"
    assert partial["sections"][0]["section_order"] == 20
    assert partial["tables"][0]["table_id"] == "deposit_balance"
    assert partial["tables"][0]["section_id"] == "deposit_loan"


def test_parse_table_md_rejects_missing_keys(tmp_path: Path):
    md = _write(tmp_path / "incomplete.md", """---
report_id: business_analysis
table_id: deposit_balance
---
""")
    with pytest.raises(ValueError, match="Missing required frontmatter keys"):
        parse_table_md(md)


def test_parse_table_md_rejects_unterminated_frontmatter(tmp_path: Path):
    md = _write(tmp_path / "unterminated.md", """---
report_id: business_analysis
""")
    with pytest.raises(ValueError, match="Unterminated YAML frontmatter"):
        parse_table_md(md)


def test_merge_table_designs_dedupes_sections(tmp_path: Path):
    p1 = parse_table_md(_write(tmp_path / "t1.md", """---
report_id: r1
report_name: 经营分析报告
report_title: 2024年
section_key: s1
section_title: S1
section_order: 10
table_id: tbl1
table_title: T1
table_order: 10
---
"""))
    p2 = parse_table_md(_write(tmp_path / "t2.md", """---
report_id: r1
report_name: 经营分析报告
report_title: 2024年
section_key: s1
section_title: S1
section_order: 10
table_id: tbl2
table_title: T2
table_order: 20
---
"""))
    p3 = parse_table_md(_write(tmp_path / "t3.md", """---
report_id: r1
report_name: 经营分析报告
report_title: 2024年
section_key: s2
section_title: S2
section_order: 20
table_id: tbl3
table_title: T3
table_order: 10
---
"""))

    merged = merge_table_designs(p1, p2, p3)

    assert merged["report"]["report_id"] == "r1"
    assert [s["section_key"] for s in merged["sections"]] == ["s1", "s2"]
    assert [t["table_id"] for t in merged["tables"]] == ["tbl1", "tbl2", "tbl3"]


def test_merge_table_designs_rejects_mixed_report_ids(tmp_path: Path):
    p1 = parse_table_md(_write(tmp_path / "a.md", """---
report_id: r1
report_name: R1
report_title: T1
section_key: s1
section_title: S
section_order: 10
table_id: tbl1
table_title: T
table_order: 10
---
"""))
    p2 = parse_table_md(_write(tmp_path / "b.md", """---
report_id: r2
report_name: R2
report_title: T2
section_key: s1
section_title: S
section_order: 10
table_id: tbl1
table_title: T
table_order: 10
---
"""))
    with pytest.raises(ValueError, match="share one report_id"):
        merge_table_designs(p1, p2)


def test_parse_table_md_dir_reads_all_md_files(tmp_path: Path):
    _write(tmp_path / "a.md", """---
report_id: r1
report_name: R1
report_title: T
section_key: s1
section_title: S
section_order: 10
table_id: tbl1
table_title: T1
table_order: 10
---
""")
    _write(tmp_path / "b.md", """---
report_id: r1
report_name: R1
report_title: T
section_key: s1
section_title: S
section_order: 10
table_id: tbl2
table_title: T2
table_order: 20
---
""")
    _write(tmp_path / "ignored.txt", "not a markdown file")
    partials = parse_table_md_dir(tmp_path)
    assert [p["tables"][0]["table_id"] for p in partials] == ["tbl1", "tbl2"]


def test_parse_table_md_dir_rejects_empty_directory(tmp_path: Path):
    with pytest.raises(ValueError, match="No `\\*\\.md` table files found"):
        parse_table_md_dir(tmp_path)