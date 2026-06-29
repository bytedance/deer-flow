"""Unit tests for scripts/compute.py.

All tests use pre-baked source strings — zero monkeypatch, zero LLM mock.
Covers 7 categories per the brief's task 5 step 6 table:
  1. extract_compute_ir (静态解析)
  2. validate_ast
  3. validate_signature
  4. run_smoke
  5. run_example
  6. evaluate_column
  7. assemble_wide_table (wide-wide 协议)
"""
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import compute as co


# ---------- Fixtures: pre-baked source strings ---------- #

VALID_SOURCE = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    """YoY = (current - prior) / prior."""
    return (df["BAS_0263"] - df["BAS_0263_prior"]) / df["BAS_0263_prior"]
'''


NO_TYPE_ANNOTATION = '''
import pandas as pd

def compute_yoy(df):
    return (df["a"] - df["b"]) / df["b"]
'''


WRONG_NAME = '''
import pandas as pd

def other_function(df: pd.DataFrame) -> pd.Series:
    return df["a"]
'''


WRONG_RETURN_ANNOT = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> int:
    return 0
'''


SOURCE_WITH_IMPORT_OS = '''
import os
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    return df["a"]
'''


SOURCE_WITH_EVAL = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    return eval("df['a']")
'''


# ---------- 1. extract_compute_ir (静态解析) ---------- #

def test_extract_ir_parses_multi_period_specs(fixture_dir):
    """multi_org.md：3 个 利润同比 spec，公式以自然语言描述，无 idx_id 字面量。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    report = doc.sections[0].reports[0]
    irs = co.extract_compute_ir(report)
    assert len(irs) == 3
    names = {ir.name for ir in irs}
    assert names == {"2023利润同比", "2024利润同比", "2025利润同比"}
    # 自然语言公式不含 [A-Z]+_\\d+，所以 base_idx_ids 为空（LLM codegen 阶段再注入）
    for ir in irs:
        assert ir.base_idx_ids == []


def test_extract_ir_captures_idx_id_in_formula(fixture_dir):
    """single_org.md 公式含 BAS_0263 → base_idx_ids 自动捕获。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    report = doc.sections[0].reports[0]
    irs = co.extract_compute_ir(report)
    assert len(irs) == 1
    yoy = irs[0]
    assert yoy.name == "收单商户同比"
    assert "BAS_0263" in yoy.base_idx_ids
    # 公式含"本期""去年同期" → periods 被识别
    assert "本期" in yoy.periods
    assert "去年同期" in yoy.periods


def test_extract_ir_captures_examples(fixture_dir):
    """single_org.md：1 spec + 1 example，example 被解析。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    report = doc.sections[0].reports[0]
    irs = co.extract_compute_ir(report)
    assert len(irs) == 1
    yoy = irs[0]
    assert yoy.name == "收单商户同比"
    assert len(yoy.examples) == 1
    assert yoy.examples[0]["inputs"]["current"] == "1420"
    assert yoy.examples[0]["inputs"]["yoy_same"] == "1200"
    assert yoy.examples[0]["expected"] == "0.1833"


# ---------- 2. validate_ast ---------- #

def test_validate_ast_rejects_import_os():
    """显式 `import os` 被拒。"""
    with pytest.raises(co.ComputeValidationError):
        co.validate_ast(SOURCE_WITH_IMPORT_OS)


def test_validate_ast_rejects_eval_call():
    """`eval(...)` Call 节点被拒。"""
    with pytest.raises(co.ComputeValidationError):
        co.validate_ast(SOURCE_WITH_EVAL)


def test_validate_ast_accepts_pandas_sum():
    """合法 pandas 调用链 + 算术通过。"""
    co.validate_ast(VALID_SOURCE)  # 不抛


# ---------- 3. validate_signature ---------- #

def test_validate_signature_rejects_no_type_annotation():
    """R3 关键测试：无 `: pd.DataFrame` 注解被拒。"""
    with pytest.raises(co.ComputeValidationError):
        co.validate_signature(NO_TYPE_ANNOTATION, "compute_yoy")


def test_validate_signature_rejects_wrong_function_name():
    """函数名不符被拒。"""
    with pytest.raises(co.ComputeValidationError):
        co.validate_signature(WRONG_NAME, "compute_yoy")


def test_validate_signature_accepts_valid_signature():
    """合法签名（pd.DataFrame 输入 + pd.Series 返回）通过。"""
    co.validate_signature(VALID_SOURCE, "compute_yoy")


# ---------- 4. run_smoke ---------- #

def test_run_smoke_rejects_source_without_signature():
    """内部调 validate_signature：缺注解的源码在 smoke 阶段就被拒（R3 修复）。"""
    df = pd.DataFrame({"a": [1.0], "b": [1.0]})
    with pytest.raises(co.ComputeValidationError):
        co.run_smoke(NO_TYPE_ANNOTATION, "compute_yoy", df)


def test_run_smoke_returns_pandas_series():
    """合法源码：返回 pd.Series 且行数与 df 一致。"""
    df = pd.DataFrame({"BAS_0263": [1420.0, 1500.0],
                       "BAS_0263_prior": [1200.0, 1300.0]})
    out = co.run_smoke(VALID_SOURCE, "compute_yoy", df)
    assert isinstance(out, pd.Series)
    assert len(out) == 2


# ---------- 5. run_example ---------- #

def test_run_example_passes_for_yoy_1833():
    """BAS_0263 current=1420, yoy_same=1200 -> 0.1833 通过。"""
    df = pd.DataFrame({"BAS_0263.current": [1420.0],
                       "BAS_0263.yoy_same": [1200.0]})
    source = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    cur = df["BAS_0263.current"]
    pri = df["BAS_0263.yoy_same"]
    return (cur - pri) / pri
'''
    assert co.run_example(source, "compute_yoy", df, expected="0.1833") is True


def test_run_example_fails_for_wrong_expected():
    """期望值与实际不符时返回 False（不抛错 —— 调用方决定如何重试）。"""
    df = pd.DataFrame({"BAS_0263.current": [1420.0],
                       "BAS_0263.yoy_same": [1200.0]})
    source = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    cur = df["BAS_0263.current"]
    pri = df["BAS_0263.yoy_same"]
    return (cur - pri) / pri
'''
    assert co.run_example(source, "compute_yoy", df, expected="0.5") is False


# ---------- 6. evaluate_column ---------- #

def test_evaluate_column_fills_decimal_series():
    """evaluate_column 顶层 API：返回 pd.Series（数值经 Decimal 化）。"""
    df = pd.DataFrame({"BAS_0263": [1420.0, 1500.0],
                       "BAS_0263_prior": [1200.0, 1300.0]})
    out = co.evaluate_column(VALID_SOURCE, "compute_yoy", df)
    assert isinstance(out, pd.Series)
    assert len(out) == 2
    # 1420/1200 - 1 = 0.18333...
    assert float(out.iloc[0]) == pytest.approx(0.1833, rel=1e-3)


def test_evaluate_column_rejects_non_series():
    """源码返回非 pd.Series（int/int）抛 ComputeValidationError。"""
    df = pd.DataFrame({"a": [1.0]})
    with pytest.raises(co.ComputeValidationError):
        co.evaluate_column(WRONG_RETURN_ANNOT, "compute_yoy", df)


# ---------- 7. assemble_wide_table (wide-wide 协议) ---------- #

def test_assemble_wide_table_wide_wide_shape(fixture_dir):
    """multi_org.md (3 期间 × 4 机构) → 列名 `BAS_0263@YYYY`，行按 branch_num。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    report = doc.sections[0].reports[0]
    per_idx_responses = [
        {"idx_id": "BAS_0263", "period": "2023", "results": [
            {"branch_num": "27020199", "raw_value": "1000", "success": True},
            {"branch_num": "27020100", "raw_value": "800", "success": True},
            {"branch_num": "AVG_TONGCHUAN", "raw_value": "900", "success": True},
            {"branch_num": "AVG_PROVINCE", "raw_value": "950", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2024", "results": [
            {"branch_num": "27020199", "raw_value": "1200", "success": True},
            {"branch_num": "27020100", "raw_value": "850", "success": True},
            {"branch_num": "AVG_TONGCHUAN", "raw_value": "1025", "success": True},
            {"branch_num": "AVG_PROVINCE", "raw_value": "1100", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2025", "results": [
            {"branch_num": "27020199", "raw_value": "1500", "success": True},
            {"branch_num": "27020100", "raw_value": "900", "success": True},
            {"branch_num": "AVG_TONGCHUAN", "raw_value": "1200", "success": True},
            {"branch_num": "AVG_PROVINCE", "raw_value": "1300", "success": True},
        ]},
    ]
    wide = co.assemble_wide_table(per_idx_responses, report)
    assert len(wide) == 4
    # 列名格式：`BAS_0263@2023/2024/2025`（按 thead 顺序）
    row = next(r for r in wide if r["branch_num"] == "27020199")
    assert set(row.keys()) >= {"branch_num", "BAS_0263@2023", "BAS_0263@2024", "BAS_0263@2025"}
    # 数值以 Decimal 累加（无 float）
    assert row["BAS_0263@2023"] == Decimal("1000")
    assert row["BAS_0263@2024"] == Decimal("1200")
    assert row["BAS_0263@2025"] == Decimal("1500")


def test_assemble_wide_table_includes_time_info_only_period_for_computation(fixture_dir):
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    report = doc.sections[0].reports[0]
    per_idx_responses = [
        {"idx_id": "BAS_0263", "period": "2022", "results": [
            {"branch_num": "27020199", "raw_value": "900", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2023", "results": [
            {"branch_num": "27020199", "raw_value": "1000", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2024", "results": [
            {"branch_num": "27020199", "raw_value": "1200", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2025", "results": [
            {"branch_num": "27020199", "raw_value": "1500", "success": True},
        ]},
    ]

    wide = co.assemble_wide_table(per_idx_responses, report)

    row = next(r for r in wide if r["branch_num"] == "27020199")
    assert row["BAS_0263@2022"] == Decimal("900")
    assert row["BAS_0263@2023"] == Decimal("1000")
    assert row["BAS_0263@2024"] == Decimal("1200")
    assert row["BAS_0263@2025"] == Decimal("1500")



    """success=False → ⚠️QUERY_FAILED 哨兵；不影响其它列。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    report = doc.sections[0].reports[0]
    per_idx_responses = [
        {"idx_id": "BAS_0263", "period": "2023", "results": [
            {"branch_num": "27020199", "raw_value": "1000", "success": True},
        ]},
        {"idx_id": "BAS_0263", "period": "2024", "results": [
            {"branch_num": "27020199", "raw_value": "", "success": False},
        ]},
        {"idx_id": "BAS_0263", "period": "2025", "results": [
            {"branch_num": "27020199", "raw_value": "1500", "success": True},
        ]},
    ]
    wide = co.assemble_wide_table(per_idx_responses, report)
    assert len(wide) == 1
    row = wide[0]
    assert row["BAS_0263@2023"] == Decimal("1000")
    assert row["BAS_0263@2024"] == co.QUERY_FAILED_SENTINEL
    assert row["BAS_0263@2025"] == Decimal("1500")


def test_assemble_wide_table_single_period_no_at_suffix(fixture_dir):
    """single_org.md (单期) → 列名 `BAS_0263` 不带 `@period`。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "single_org.md"))
    report = doc.sections[0].reports[0]
    per_idx_responses = [
        {"idx_id": "BAS_0263", "period": None, "results": [
            {"branch_num": "27020199", "raw_value": "1420", "success": True},
        ]},
    ]
    wide = co.assemble_wide_table(per_idx_responses, report)
    assert len(wide) == 1
    row = wide[0]
    assert "BAS_0263" in row
    assert "BAS_0263@None" not in row
    assert row["BAS_0263"] == Decimal("1420")


def test_end_to_end_real_output_via_mock_client(fixture_dir):
    """端到端：multi_org.md + mock SQLBot → wide table → 与 output.md 真实值一致。"""
    import sqlbot_client as sc
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "multi_org.md"))
    report = doc.sections[0].reports[0]
    client = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "profit_yoy.json")
    )
    per_idx_responses = []
    for cell in (c for row in report.headers for c in row if c.is_indicator and c.idx_id):
        resp = client.query_report_info(
            org_info=[],
            index_info=[{"idx_id": cell.idx_id}],
            time_info=[cell.period] if cell.period else [],
        )
        results = [
            {
                "branch_num": str(r.get("org_ecd", "")),
                "raw_value": r.get("value", ""),
                "success": True,
            }
            for r in resp.data[0]["data"]
        ]
        per_idx_responses.append({
            "idx_id": cell.idx_id, "period": cell.period, "results": results,
        })
    wide = co.assemble_wide_table(per_idx_responses, report)
    # 验证 王益 行 3 期间值与 output.md 一致
    wangyi = next(r for r in wide if r["branch_num"] == "王益")
    assert wangyi["BAS_0263@2023"] == Decimal("188.01")
    assert wangyi["BAS_0263@2024"] == Decimal("495.83")
    assert wangyi["BAS_0263@2025"] == Decimal("322.78")
    # 验证 全省平均值 行（最大数）
    province = next(r for r in wide if r["branch_num"] == "全省平均值")
    assert province["BAS_0263@2023"] == Decimal("3440.55")
    assert province["BAS_0263@2024"] == Decimal("3716.53")
    assert province["BAS_0263@2025"] == Decimal("3871.30")


# ---------- CLI 烟雾 ---------- #


def test_apply_computed_results_merges_values_by_branch_num():
    wide = [
        {"branch_num": "27020100", "BAS_0263@2025": "350.62"},
        {"branch_num": "27020199", "BAS_0263@2025": "322.78"},
    ]
    computed = {
        "2025利润同比": {"index": ["27020100", "27020199"], "values": ["-0.3327", "-0.3490"]},
    }

    out = co.apply_computed_results(wide, computed)

    assert out[0]["2025利润同比"] == "-0.3327"
    assert out[1]["2025利润同比"] == "-0.3490"


def test_apply_computed_results_uses_payload_name_over_slug_filename():
    wide = [
        {"branch_num": "27020199", "BAS_0263@2025": "322.78"},
    ]
    computed = {
        "2025_profit_yoy": {
            "name": "2025利润同比",
            "index": ["27020199"],
            "values": ["-0.3490"],
        },
    }

    out = co.apply_computed_results(wide, computed)

    assert out[0]["2025利润同比"] == "-0.3490"
    assert "2025_profit_yoy" not in out[0]


def test_apply_computed_results_mismatched_branch_num_skips_row():
    """computed.index 里的 branch_num 在 wide 中找不到时，该行不写入。"""
    wide = [
        {"branch_num": "27020100", "BAS_0263@2025": "350.62"},
        {"branch_num": "27020199", "BAS_0263@2025": "322.78"},
    ]
    computed = {
        "2025利润同比": {"index": ["27020100", "UNKNOWN"], "values": ["-0.3327", "-0.9999"]},
    }

    out = co.apply_computed_results(wide, computed)

    assert out[0]["2025利润同比"] == "-0.3327"
    assert "2025利润同比" not in out[1]


def test_cli_apply_computed_dispatches(tmp_path):
    import json
    import subprocess
    import sys
    script = str(Path(__file__).resolve().parents[1] / "compute.py")
    wide = tmp_path / "input.wide.json"
    wide.write_text(json.dumps([
        {"branch_num": "27020100", "BAS_0263@2025": "350.62"},
    ], ensure_ascii=False), encoding="utf-8")
    computed = tmp_path / "input.computed.2025利润同比.json"
    computed.write_text(json.dumps({
        "index": ["27020100"],
        "values": ["-0.3327"],
    }, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run([
        sys.executable, script, "apply-computed",
        "--wide", str(wide),
        "--computed-dir", str(tmp_path),
        "--stem", "input",
    ], capture_output=True, text=True)

    assert r.returncode == 0
    merged = json.loads(wide.read_text(encoding="utf-8"))
    assert merged[0]["2025利润同比"] == "-0.3327"


def test_cli_help_runs(tmp_path):
    """CLI --help 不报错。"""
    import subprocess
    import sys
    script = str(Path(__file__).resolve().parents[1] / "compute.py")
    r = subprocess.run([sys.executable, script, "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "extract-ir" in r.stdout
    assert "assemble-wide" in r.stdout
    assert "validate" in r.stdout
    assert "evaluate" in r.stdout
    assert "apply-computed" in r.stdout


def test_cli_validate_accepts_scalar_json_example_input(tmp_path):
    import json
    import subprocess
    import sys
    script = str(Path(__file__).resolve().parents[1] / "compute.py")
    source = tmp_path / "input.compute.2024利润同比.py"
    source.write_text('''
import pandas as pd
from decimal import Decimal


def compute_2024利润同比(df: pd.DataFrame) -> pd.Series:
    cur = df["BAS_0263@2024"].apply(lambda v: Decimal(str(v)))
    pri = df["BAS_0263@2023"].apply(lambda v: Decimal(str(v)))
    return ((cur - pri) / pri).astype(float)
''', encoding="utf-8")
    wide = tmp_path / "input.wide.json"
    wide.write_text(json.dumps([
        {"branch_num": "27020199", "BAS_0263@2023": "1000", "BAS_0263@2024": "1200"},
    ], ensure_ascii=False), encoding="utf-8")

    r = subprocess.run([
        sys.executable, script, "validate",
        "--source", str(source),
        "--function", "compute_2024利润同比",
        "--df", str(wide),
        "--example-input", '{"2024":"1200","2023":"1000"}',
        "--example-expected", "0.2",
    ], capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
    assert "OK: validated" in r.stdout


def test_cli_extract_ir_dispatches(tmp_path):
    """CLI extract-ir 子命令能派发（即使输入文件不存在会报 clear error）。"""
    import subprocess
    import sys
    script = str(Path(__file__).resolve().parents[1] / "compute.py")
    r = subprocess.run([sys.executable, script, "extract-ir",
                         "--parsed", "/nonexistent.json",
                         "--out", str(tmp_path / "out.json")],
                        capture_output=True, text=True)
    # /nonexistent.json 必失败；关键是子命令被派发（exit != 2 = argparse error）
    assert r.returncode != 2
