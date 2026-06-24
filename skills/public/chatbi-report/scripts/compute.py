"""Compute pipeline for chatbi-report skill.

零 LLM 依赖（参考 skills/public/data-analysis/scripts/analyze.py）：
- extract_compute_ir()：从 ReportDoc.computed_specs 用 regex/AST 静态解析公式字符串
- assemble_wide_table()：SQLBot 长表 -> chatbi 宽表（按 branch_num × period 透视）
- validate_ast() / validate_signature() / run_smoke() / run_example()：四层校验
- evaluate_column()：列填充顶层 API
- CLI: extract-ir / assemble-wide / validate / evaluate（4 个子命令）

LLM codegen（生成 pandas 函数源码）不在本模块 —— 由 lead agent 在 SKILL.md
step 7 读取 prompts/compute_codegen.md + ComputeIR JSON 拼装 prompt 调用模型，
生成的源码作为字符串传入本模块的校验/执行函数（或通过 CLI 子命令读盘）。
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from parse_md import Report


# ---------- 错误类型 ---------- #

class ComputeValidationError(Exception):
    """compute.py 校验链（AST / 签名 / smoke / example / evaluate）的统一异常。"""


# ---------- IR 数据结构 ---------- #

IDX_ID_RE = re.compile(r"([A-Z]+_\d+)")
PERIOD_TOKENS = ("本期", "上期", "去年同期", "年初", "年末", "环比", "同比")


@dataclass
class ComputeIR:
    """单条计算列的 LLM 输入载荷（与 prompts/compute_codegen.md 对齐）。"""

    name: str
    formula_repr: str
    base_idx_ids: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "formula_repr": self.formula_repr,
            "base_idx_ids": list(self.base_idx_ids),
            "periods": list(self.periods),
            "examples": list(self.examples),
        }


# ---------- extract_compute_ir（静态解析） ---------- #

def extract_compute_ir(report: Report) -> list[ComputeIR]:
    """从 Report.computed_specs 静态解析为 ComputeIR 列表（零 LLM）。

    每个 ComputeIR 携带：
    - name: 计算列名
    - formula_repr: 原始 "name = expr" 字符串（送入 LLM）
    - base_idx_ids: regex 提取的 [A-Z]+_\\d+（公式里出现的基础指标）
    - periods: 公式中的时期标识符（本期/上期/去年同期/...）
    - examples: 来自 .示例: 行的 [{inputs, expected}] 列表
    """
    out: list[ComputeIR] = []
    for spec in report.computed_specs:
        expr = spec.prompt.split("=", 1)[1].strip() if "=" in spec.prompt else spec.prompt
        base = sorted(set(IDX_ID_RE.findall(expr)))
        periods = [p for p in PERIOD_TOKENS if p in expr]
        out.append(ComputeIR(
            name=spec.name,
            formula_repr=spec.prompt,
            base_idx_ids=base,
            periods=periods,
            examples=list(spec.examples),
        ))
    return out


# ---------- assemble_wide_table ---------- #

QUERY_FAILED_SENTINEL = "⚠️QUERY_FAILED"


def assemble_wide_table(per_idx_responses: list[dict], report: Report) -> list[dict]:
    """将 SQLBot 长表（每个 idx_id 一份 {branch_num, period, results: [...]})
    透视为 chatbi 宽表行：每个 (branch_num, period) 一行，列 = idx_id 列 + 计算列占位。

    所有数值列以 Decimal 累加（无 float 精度损失）；失败单元格以
    ⚠️QUERY_FAILED 标记。
    """
    # 收集所有 (branch_num, period) 组合
    keys: set[tuple[str, str]] = set()
    for resp in per_idx_responses:
        for row in resp.get("results", []):
            keys.add((str(row.get("branch_num", "")),
                      str(row.get("period", ""))))
    sorted_keys = sorted(keys)

    # 索引：idx_id -> {(branch_num, period): raw_value}
    idx_index: dict[str, dict[tuple[str, str], str]] = {}
    for resp in per_idx_responses:
        idx = resp.get("idx_id")
        if not idx:
            continue
        per_row = idx_index.setdefault(idx, {})
        for row in resp.get("results", []):
            k = (str(row.get("branch_num", "")),
                 str(row.get("period", "")))
            if row.get("success") is True:
                per_row[k] = str(row.get("raw_value", ""))
            else:
                per_row[k] = QUERY_FAILED_SENTINEL

    # 全部 idx_id（来自 thead）
    all_idx: list[str] = []
    for row in report.headers:
        for cell in row:
            if cell.is_indicator and cell.idx_id and cell.idx_id not in all_idx:
                all_idx.append(cell.idx_id)

    wide: list[dict] = []
    for k in sorted_keys:
        line: dict = {"branch_num": k[0], "period": k[1]}
        for idx in all_idx:
            raw = idx_index.get(idx, {}).get(k, "")
            if raw == QUERY_FAILED_SENTINEL:
                line[idx] = QUERY_FAILED_SENTINEL
            elif raw == "":
                line[idx] = None
            else:
                try:
                    line[idx] = Decimal(raw.replace(",", "").strip())
                except Exception:
                    line[idx] = QUERY_FAILED_SENTINEL
        wide.append(line)
    return wide


# ---------- validate_ast ---------- #

# 黑名单：拒绝这些 Attribute 链（防止 __class__/__subclasses__/os.system 沙箱逃逸）
_BLOCKED_ATTR_NAMES = {"os", "sys", "subprocess", "builtins"}
_BLOCKED_DUNDER = True  # 拒绝所有以双下划线开头/结尾的属性


def validate_ast(source: str) -> None:
    """AST 白名单校验：拒绝 import os / eval / __import__ / dunder 属性访问。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ComputeValidationError(f"SyntaxError: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BLOCKED_ATTR_NAMES:
                    raise ComputeValidationError(
                        f"import `{alias.name}` is forbidden by AST whitelist"
                    )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _BLOCKED_ATTR_NAMES:
                raise ComputeValidationError(
                    f"from {node.module} import ... is forbidden by AST whitelist"
                )
        elif isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            raise ComputeValidationError(
                f"`{type(node).__name__}` statement is forbidden"
            )
        elif isinstance(node, ast.Call):
            # 拒绝 eval/exec/__import__/compile/open 等危险调用
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec", "__import__", "compile", "open"}:
                raise ComputeValidationError(
                    f"call to `{func.id}()` is forbidden"
                )
        elif isinstance(node, ast.Attribute):
            # 拒绝 dunder 属性（__class__, __subclasses__, __init_subclass__ ...）
            if _BLOCKED_DUNDER and (node.attr.startswith("__") and node.attr.endswith("__")):
                raise ComputeValidationError(
                    f"dunder attribute access `.{node.attr}` is forbidden"
                )
            # 拒绝 os.* / sys.* / subprocess.*
            if isinstance(node.value, ast.Name) and node.value.id in _BLOCKED_ATTR_NAMES:
                raise ComputeValidationError(
                    f"access to `{node.value.id}.{node.attr}` is forbidden"
                )


# ---------- validate_signature ---------- #

def validate_signature(source: str, expected_name: str) -> None:
    """函数签名校验：名称 + (df: pd.DataFrame) + -> pd.Series。

    R3 修复关键点：强制 `: pd.DataFrame` 类型注解 + `-> pd.Series` 返回注解。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ComputeValidationError(f"SyntaxError: {e}") from e

    func: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == expected_name:
            func = node
            break
    if func is None:
        raise ComputeValidationError(
            f"function `{expected_name}` not found in source"
        )

    # 参数注解：第一个参数必须是 df: pd.DataFrame
    args = func.args.args
    if not args:
        raise ComputeValidationError("function has no parameters")
    first = args[0]
    if first.arg != "df":
        raise ComputeValidationError(
            f"first parameter must be named `df`, got `{first.arg}`"
        )
    if first.annotation is None:
        raise ComputeValidationError(
            "first parameter `df` must have type annotation (R3: required `: pd.DataFrame`)"
        )
    if not _is_pd_dataframe_annotation(first.annotation):
        raise ComputeValidationError(
            f"first parameter must be annotated as `pd.DataFrame`, got `{ast.unparse(first.annotation)}`"
        )

    # 返回注解：必须是 pd.Series
    if func.returns is None:
        raise ComputeValidationError(
            "return annotation required (R3: required `-> pd.Series`)"
        )
    if not _is_pd_series_annotation(func.returns):
        raise ComputeValidationError(
            f"return annotation must be `pd.Series`, got `{ast.unparse(func.returns)}`"
        )


def _is_pd_dataframe_annotation(node: ast.AST) -> bool:
    """匹配 `pd.DataFrame` 或 `pandas.DataFrame` 属性链。"""
    if isinstance(node, ast.Attribute) and node.attr == "DataFrame":
        if isinstance(node.value, ast.Name) and node.value.id in {"pd", "pandas"}:
            return True
    return False


def _is_pd_series_annotation(node: ast.AST) -> bool:
    """匹配 `pd.Series` 或 `pandas.Series` 属性链。"""
    if isinstance(node, ast.Attribute) and node.attr == "Series":
        if isinstance(node.value, ast.Name) and node.value.id in {"pd", "pandas"}:
            return True
    return False


# ---------- run_smoke ---------- #

def run_smoke(source: str, function_name: str, df: pd.DataFrame,
              smoke_rows: int = 3) -> pd.Series:
    """执行源码 + 调用函数 + 断言 isinstance(out, pd.Series)。

    R3 修复：头部先调 validate_signature —— 无类型注解的源码在 smoke 阶段就被拒。
    """
    validate_signature(source, function_name)
    validate_ast(source)
    ns = _exec_source(source)
    fn = ns[function_name]
    sample = df.head(smoke_rows)
    out = fn(sample)
    if not isinstance(out, pd.Series):
        raise ComputeValidationError(
            f"function `{function_name}` returned {type(out).__name__}, expected pd.Series"
        )
    return out


# ---------- run_example ---------- #

def run_example(source: str, function_name: str, df: pd.DataFrame, *,
                expected: str) -> bool:
    """执行示例（df 单行）+ math.isclose 校验。

    返回 bool（不抛错）—— 调用方决定如何重试（与 lead agent 失败-重试约定对齐）。
    """
    validate_signature(source, function_name)
    validate_ast(source)
    ns = _exec_source(source)
    fn = ns[function_name]
    out = fn(df)
    if not isinstance(out, pd.Series) or len(out) == 0:
        return False
    actual = float(out.iloc[0])
    try:
        target = float(expected)
    except (TypeError, ValueError):
        return False
    return math.isclose(actual, target, rel_tol=1e-3, abs_tol=1e-3)


# ---------- evaluate_column ---------- #

def evaluate_column(source: str, function_name: str, df: pd.DataFrame) -> pd.Series:
    """列填充顶层 API：执行源码 + 调用函数 + 校验返回值类型。

    返回 pd.Series（数值经 Decimal 化）。非 Series 返回值抛 ComputeValidationError。
    """
    validate_signature(source, function_name)
    validate_ast(source)
    ns = _exec_source(source)
    fn = ns[function_name]
    out = fn(df)
    if not isinstance(out, pd.Series):
        raise ComputeValidationError(
            f"function `{function_name}` returned {type(out).__name__}, expected pd.Series"
        )
    # Decimal 化：避免后续 float 精度漂移
    return out.apply(lambda x: Decimal(str(x)) if _is_finite_number(x) else x)


def _is_finite_number(x: object) -> bool:
    """判断 x 是否可被转换为有限数（用于 Decimal 化）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v)


def _exec_source(source: str) -> dict:
    """受限 ns 的 exec()。返回命名空间。"""
    ns: dict = {"pd": pd, "pandas": pd, "Decimal": Decimal}
    try:
        exec(compile(source, "<compute-source>", "exec"), ns)  # noqa: S102
    except Exception as e:
        raise ComputeValidationError(f"exec() failed: {e}") from e
    return ns


# ---------- CLI 入口 ---------- #

def _cli_extract_ir(args: argparse.Namespace) -> int:
    """从 parsed.json -> ir.json。"""
    from parse_md import Report, ReportDoc, OrgContext, Th  # 延迟导入（避免 unit_conversion 路径下无关 import）

    with open(args.parsed, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 反序列化 Report -> Report 对象（构造最小 IR 抽取路径所需字段）
    doc_dict = data if "sections" in data else data
    irs: list[dict] = []
    for sec in doc_dict.get("sections", []):
        for rep_dict in sec.get("reports", []):
            report = _dict_to_report(rep_dict)
            for ir in extract_compute_ir(report):
                irs.append(ir.to_dict())

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"compute_irs": irs}, f, ensure_ascii=False, indent=2)
    print(f"OK: extracted {len(irs)} ComputeIR -> {args.out}")
    return 0


def _dict_to_report(d: dict) -> Report:
    """最小 Report 重建（仅供 extract_compute_ir 所需字段）。"""
    from parse_md import Report, OrgContext, Th
    org = OrgContext(**d["org_context"])
    headers: list[list[Th]] = []
    for row in d.get("headers", []):
        cells: list[Th] = []
        for c in row:
            cells.append(Th(
                text=c["text"],
                is_indicator=c["is_indicator"],
                is_computed=c["is_computed"],
                idx_id=c.get("idx_id"),
                data_unit=c.get("data_unit"),
                rowspan=c.get("rowspan"),
                colspan=c.get("colspan"),
            ))
        headers.append(cells)
    return Report(
        title=d["title"],
        org_context=org,
        time_info=d["time_info"],
        headers=headers,
        data_rows=d.get("data_rows", []),
        computed_specs=_specs_from_dict(d.get("computed_specs", [])),
    )


def _specs_from_dict(specs: list[dict]) -> list:
    from parse_md import ComputedSpec
    return [ComputedSpec(name=s["name"], prompt=s["prompt"], examples=s.get("examples", []))
            for s in specs]


def _cli_assemble_wide(args: argparse.Namespace) -> int:
    """从 query.json + parsed.json -> wide.json。"""
    with open(args.query, "r", encoding="utf-8") as f:
        query = json.load(f)
    with open(args.parsed, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    per_idx_responses = query.get("results", query if isinstance(query, list) else [query])
    rep = _dict_to_report(parsed["sections"][0]["reports"][0])
    wide = assemble_wide_table(per_idx_responses, rep)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(wide, f, ensure_ascii=False, indent=2, default=str)
    print(f"OK: pivoted {len(wide)} wide rows -> {args.out}")
    return 0


def _cli_validate(args: argparse.Namespace) -> int:
    """四层校验（AST + signature + smoke + example）。"""
    df = pd.read_json(args.df) if args.df.endswith(".json") else pd.DataFrame(json.loads(args.df))
    source = Path(args.source).read_text(encoding="utf-8") if args.source != "-" else sys.stdin.read()

    try:
        validate_signature(source, args.function)
        validate_ast(source)
        run_smoke(source, args.function, df)
        if args.example_input and args.example_expected is not None:
            ex_df = pd.DataFrame(json.loads(args.example_input) if args.example_input.startswith("{") else _parse_kv(args.example_input))
            ok = run_example(source, args.function, ex_df, expected=str(args.example_expected))
            if not ok:
                print(f"FAIL: example mismatch (expected {args.example_expected})", file=sys.stderr)
                return 1
        print("OK: validated")
        return 0
    except ComputeValidationError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


def _parse_kv(s: str) -> list[dict]:
    """`BAS_0263.current=1420,BAS_0263.yoy_same=1200` -> DataFrame。"""
    row: dict = {}
    for kv in s.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        row[k.strip()] = float(v)
    return [row]


def _cli_evaluate(args: argparse.Namespace) -> int:
    """执行函数返回 pd.Series（序列化为 JSON）。"""
    df = pd.read_json(args.df) if args.df.endswith(".json") else pd.DataFrame(json.loads(args.df))
    source = Path(args.source).read_text(encoding="utf-8") if args.source != "-" else sys.stdin.read()
    out = evaluate_column(source, args.function, df)
    payload = {"index": [str(i) for i in out.index], "values": [str(v) for v in out.values]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"OK: evaluated {len(out)} values -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compute", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ir = sub.add_parser("extract-ir", help="从 parsed.json 抽取 ComputeIR")
    p_ir.add_argument("--parsed", required=True)
    p_ir.add_argument("--out", required=True)
    p_ir.set_defaults(func=_cli_extract_ir)

    p_wide = sub.add_parser("assemble-wide", help="SQLBot 长表 -> chatbi 宽表")
    p_wide.add_argument("--query", required=True)
    p_wide.add_argument("--parsed", required=True)
    p_wide.add_argument("--out", required=True)
    p_wide.set_defaults(func=_cli_assemble_wide)

    p_val = sub.add_parser("validate", help="四层校验（AST + signature + smoke + example）")
    p_val.add_argument("--source", required=True, help="pandas 源码路径（- 为 stdin）")
    p_val.add_argument("--function", required=True)
    p_val.add_argument("--df", required=True, help="宽表 JSON 路径")
    p_val.add_argument("--example-input", default=None)
    p_val.add_argument("--example-expected", default=None)
    p_val.set_defaults(func=_cli_validate)

    p_eval = sub.add_parser("evaluate", help="执行函数返回 pd.Series（序列化为 JSON）")
    p_eval.add_argument("--source", required=True)
    p_eval.add_argument("--function", required=True)
    p_eval.add_argument("--df", required=True)
    p_eval.add_argument("--out", required=True)
    p_eval.set_defaults(func=_cli_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
