"""Unit tests for scripts/compute.py.

All tests use pre-baked source strings — zero monkeypatch, zero LLM mock.
Covers 6 categories per the brief's task 5 step 6 table:
  1. extract_compute_ir (静态解析)
  2. validate_ast
  3. validate_signature
  4. run_smoke
  5. run_example
  6. evaluate_column
"""
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


VALID_SOURCE_QOQ = '''
import pandas as pd

def compute_qoq(df: pd.DataFrame) -> pd.Series:
    return (df["x"] - df["x_prev"]) / df["x_prev"]
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


SOURCE_WITH_DUNDER = '''
import pandas as pd

def compute_yoy(df: pd.DataFrame) -> pd.Series:
    return df.__class__
'''


# ---------- 1. extract_compute_ir (静态解析) ---------- #

def test_extract_ir_parses_computed_columns_md(fixture_dir):
    """computed_columns.md：2 个计算 spec，base_idx_ids 正确。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "computed_columns.md"))
    report = doc.sections[0].reports[0]
    irs = co.extract_compute_ir(report)
    assert len(irs) == 2
    names = {ir.name for ir in irs}
    assert names == {"收单商户同比", "余额较年初"}
    yoy = next(ir for ir in irs if ir.name == "收单商户同比")
    assert "BAS_0263" in yoy.base_idx_ids


def test_extract_ir_captures_examples(fixture_dir):
    """computed_with_examples.md：1 spec + 1 example，example 被解析。"""
    from parse_md import parse_file
    doc = parse_file(str(fixture_dir / "sample_md" / "computed_with_examples.md"))
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


# ---------- CLI 烟雾 ---------- #

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
