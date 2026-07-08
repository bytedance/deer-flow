import argparse
import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from validators import quote_identifier, validate_table_name
from logging_config import get_logger, configure_logging

# Initialize logging
configure_logging()
logger = get_logger(__name__)


def _quote_column(column: str) -> str:
    """Quote a DuckDB column name without imposing table-name rules."""
    if not column or not isinstance(column, str):
        raise ValueError("列名不能为空")
    return '"' + column.replace('"', '""') + '"'


def _load_rules(config_path: str | None) -> dict[str, Any]:
    if not config_path:
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(config or {})
    config.setdefault("type_conversions", [])
    config.setdefault("missing_values", {})
    config.setdefault("outliers", [])
    config.setdefault("normalization", [])
    config.setdefault("text_cleaning", [])
    config.setdefault("boolean_mappings", {})
    config.setdefault("derived_features", [])
    config.setdefault("masking", [])
    config.setdefault("rules", [])
    config.setdefault("cross_table_rules", [])
    return config


def _clean_money_series(series, decimals: int = 2):
    cleaned = (
        series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.strip()
    )
    return cleaned.pipe(lambda s: __import__("pandas").to_numeric(s, errors="coerce")).round(decimals)


def _apply_type_conversions(df, conversions: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    for rule in conversions:
        column = rule.get("column")
        target_type = str(rule.get("type", "")).lower()
        if column not in df.columns:
            report["warnings"].append(f"类型转换跳过：列不存在 {column}")
            continue

        before_nulls = int(df[column].isna().sum())
        if target_type in {"date", "datetime"}:
            df[column] = pd.to_datetime(df[column], errors="coerce", format=rule.get("format"))
            if target_type == "date":
                df[column] = df[column].dt.date
        elif target_type in {"money", "decimal"}:
            df[column] = _clean_money_series(df[column], int(rule.get("decimals", 2)))
        elif target_type in {"float", "number", "numeric"}:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        elif target_type in {"int", "integer"}:
            df[column] = pd.to_numeric(df[column], errors="coerce").round().astype("Int64")
        elif target_type in {"string", "text"}:
            df[column] = df[column].astype("string")
        elif target_type in {"bool", "boolean"}:
            true_values = set(map(str, rule.get("true_values", ["true", "1", "yes", "是", "Y"])))
            false_values = set(map(str, rule.get("false_values", ["false", "0", "no", "否", "N"])))
            normalized = df[column].astype("string").str.strip()
            df[column] = normalized.map(
                lambda v: True if str(v) in true_values else False if str(v) in false_values else pd.NA
            ).astype("boolean")
        else:
            report["warnings"].append(f"未知类型转换：{column} -> {target_type}")
            continue

        after_nulls = int(df[column].isna().sum())
        report["type_conversions"].append({
            "column": column,
            "type": target_type,
            "new_nulls": max(after_nulls - before_nulls, 0),
        })


def _apply_missing_values(df, rules: dict[str, Any], report: dict[str, Any]) -> None:
    for column, spec in rules.items():
        if column not in df.columns:
            report["warnings"].append(f"缺失值处理跳过：列不存在 {column}")
            continue
        if isinstance(spec, str):
            spec = {"strategy": spec}
        strategy = spec.get("strategy", "none")
        before = int(df[column].isna().sum())
        if strategy == "drop":
            df.dropna(subset=[column], inplace=True)
        elif strategy == "mean":
            df[column] = df[column].fillna(df[column].mean())
        elif strategy == "median":
            df[column] = df[column].fillna(df[column].median())
        elif strategy == "mode":
            mode = df[column].mode(dropna=True)
            if not mode.empty:
                df[column] = df[column].fillna(mode.iloc[0])
        elif strategy == "constant":
            df[column] = df[column].fillna(spec.get("value"))
        elif strategy in {"none", "ask"}:
            pass
        else:
            report["warnings"].append(f"未知缺失值策略：{column} -> {strategy}")
            continue
        after = int(df[column].isna().sum()) if column in df.columns else 0
        report["missing_values"].append({
            "column": column,
            "strategy": strategy,
            "before": before,
            "after": after,
        })


def _apply_text_cleaning(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    for rule in rules:
        column = rule.get("column")
        if column not in df.columns:
            report["warnings"].append(f"文本清洗跳过：列不存在 {column}")
            continue
        series = df[column].astype("string")
        if rule.get("strip", True):
            series = series.str.strip()
        case = rule.get("case")
        if case == "lower":
            series = series.str.lower()
        elif case == "upper":
            series = series.str.upper()
        if rule.get("remove_special"):
            series = series.str.replace(r"[^\w\s\u4e00-\u9fff-]", "", regex=True)
        if "replace" in rule:
            for old, new in rule["replace"].items():
                series = series.str.replace(old, new, regex=False)
        df[column] = series
        report["text_cleaning"].append({"column": column, "rule": rule})


def _apply_boolean_mappings(df, mappings: dict[str, Any], report: dict[str, Any]) -> None:
    import pandas as pd

    for column, spec in mappings.items():
        if column not in df.columns:
            report["warnings"].append(f"布尔映射跳过：列不存在 {column}")
            continue
        true_values = set(map(str, spec.get("true_values", ["是", "true", "1", "yes"])))
        false_values = set(map(str, spec.get("false_values", ["否", "false", "0", "no"])))
        normalized = df[column].astype("string").str.strip()
        df[column] = normalized.map(
            lambda v: True if str(v) in true_values else False if str(v) in false_values else pd.NA
        ).astype("boolean")
        report["boolean_mappings"].append({"column": column})


def _apply_normalization(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    for rule in rules:
        column = rule.get("column")
        if column not in df.columns:
            report["warnings"].append(f"标准化跳过：列不存在 {column}")
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        method = rule.get("method", "minmax")
        target = rule.get("target_column", f"{column}_{method}")
        if method == "minmax":
            span = values.max() - values.min()
            df[target] = 0 if span == 0 else (values - values.min()) / span
        elif method == "zscore":
            std = values.std()
            df[target] = 0 if not std else (values - values.mean()) / std
        else:
            report["warnings"].append(f"未知标准化方法：{column} -> {method}")
            continue
        report["normalization"].append({"column": column, "method": method, "target_column": target})


def _apply_derived_features(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    for rule in rules:
        name = rule.get("name")
        method = rule.get("method")
        if not name or not method:
            report["warnings"].append("派生特征跳过：缺少 name 或 method")
            continue
        if method == "date_part":
            source = rule.get("source")
            if source not in df.columns:
                report["warnings"].append(f"派生特征跳过：列不存在 {source}")
                continue
            dates = pd.to_datetime(df[source], errors="coerce")
            part = rule.get("part", "year")
            if part == "year":
                df[name] = dates.dt.year
            elif part == "month":
                df[name] = dates.dt.month
            elif part == "day":
                df[name] = dates.dt.day
            elif part == "weekday":
                df[name] = dates.dt.weekday
            elif part == "is_weekend":
                df[name] = dates.dt.weekday >= 5
            else:
                report["warnings"].append(f"未知日期派生字段：{part}")
                continue
        elif method == "ratio":
            numerator = rule.get("numerator")
            denominator = rule.get("denominator")
            if numerator not in df.columns or denominator not in df.columns:
                report["warnings"].append(f"派生比率跳过：列不存在 {name}")
                continue
            denom = pd.to_numeric(df[denominator], errors="coerce").replace(0, pd.NA)
            df[name] = pd.to_numeric(df[numerator], errors="coerce") / denom
            if "decimals" in rule:
                df[name] = df[name].round(int(rule["decimals"]))
        elif method == "concat":
            columns = rule.get("columns", [])
            missing = [c for c in columns if c not in df.columns]
            if missing:
                report["warnings"].append(f"派生拼接跳过：列不存在 {', '.join(missing)}")
                continue
            sep = rule.get("sep", "")
            df[name] = df[columns].astype("string").agg(sep.join, axis=1)
        else:
            report["warnings"].append(f"未知派生特征方法：{method}")
            continue
        report["derived_features"].append({"name": name, "method": method})


def _apply_masking(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    for rule in rules:
        column = rule.get("column")
        if column not in df.columns:
            report["warnings"].append(f"脱敏跳过：列不存在 {column}")
            continue
        method = rule.get("method", "middle")
        series = df[column].astype("string")
        if method == "middle":
            start = int(rule.get("keep_start", 3))
            end = int(rule.get("keep_end", 4))
            mask = rule.get("mask", "****")
            df[column] = series.map(
                lambda v: v[:start] + mask + v[-end:] if isinstance(v, str) and len(v) > start + end else v
            )
        elif method == "hash":
            import hashlib

            salt = str(rule.get("salt", ""))
            df[column] = series.map(lambda v: hashlib.sha256((salt + str(v)).encode("utf-8")).hexdigest() if v is not None else v)
        else:
            report["warnings"].append(f"未知脱敏方法：{column} -> {method}")
            continue
        report["masking"].append({"column": column, "method": method})


def _apply_outliers(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    for rule in rules:
        column = rule.get("column")
        if column not in df.columns:
            report["warnings"].append(f"异常值处理跳过：列不存在 {column}")
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        method = rule.get("method", "bounds")
        if method == "bounds":
            mask = pd.Series(False, index=df.index)
            if "min" in rule:
                mask |= values < rule["min"]
            if "max" in rule:
                mask |= values > rule["max"]
        elif method == "iqr":
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1
            mask = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
        elif method == "zscore":
            std = values.std()
            mask = pd.Series(False, index=df.index) if not std else ((values - values.mean()).abs() / std) > rule.get("threshold", 3)
        else:
            report["warnings"].append(f"未知异常值方法：{column} -> {method}")
            continue

        count = int(mask.fillna(False).sum())
        action = rule.get("action", "flag")
        if action == "null":
            df.loc[mask, column] = pd.NA
        elif action == "drop":
            df.drop(index=df[mask].index, inplace=True)
        elif action == "clip":
            if "min" in rule:
                df[column] = values.clip(lower=rule["min"])
            if "max" in rule:
                df[column] = pd.to_numeric(df[column], errors="coerce").clip(upper=rule["max"])
        else:
            flag_column = rule.get("flag_column", f"{column}_outlier_flag")
            df[flag_column] = mask.fillna(False)
        report["outliers"].append({"column": column, "method": method, "action": action, "affected_rows": count})


def _apply_deduplication(df, config: dict[str, Any], report: dict[str, Any]) -> None:
    unique_key = config.get("unique_key") or config.get("unique_keys")
    if not unique_key:
        before = len(df)
        df.drop_duplicates(inplace=True)
        report["deduplication"] = {"mode": "full_row", "removed_rows": before - len(df)}
        return

    if isinstance(unique_key, str):
        unique_key = [c.strip() for c in unique_key.split(",") if c.strip()]
    missing = [c for c in unique_key if c not in df.columns]
    if missing:
        raise ValueError(f"唯一键列不存在: {', '.join(missing)}")

    before = len(df)
    order_by = config.get("duplicate_order_by")
    keep = config.get("duplicate_keep", "first")
    if order_by:
        if order_by not in df.columns:
            raise ValueError(f"duplicate_order_by 列不存在: {order_by}")
        ascending = bool(config.get("duplicate_order_ascending", True))
        df.sort_values(order_by, ascending=ascending, inplace=True)
        keep = "last" if config.get("duplicate_keep", "latest") == "latest" else keep
    df.drop_duplicates(subset=unique_key, keep=keep if keep in {"first", "last", False} else "first", inplace=True)
    report["deduplication"] = {
        "mode": "unique_key",
        "unique_key": unique_key,
        "removed_rows": before - len(df),
        "keep": config.get("duplicate_keep", keep),
    }


def _evaluate_rules(df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    ops = {
        "<": lambda l, r: l < r,
        "<=": lambda l, r: l <= r,
        ">": lambda l, r: l > r,
        ">=": lambda l, r: l >= r,
        "==": lambda l, r: l == r,
        "!=": lambda l, r: l != r,
    }
    for rule in rules:
        name = rule.get("name", "rule")
        left = rule.get("left")
        right = rule.get("right")
        op = rule.get("op")
        right_is_column = isinstance(right, str) and right in df.columns
        if left not in df.columns or (not right_is_column and "right_value" not in rule):
            report["warnings"].append(f"规则跳过：字段不存在 {name}")
            continue
        if op not in ops:
            report["warnings"].append(f"规则跳过：不支持操作符 {name} {op}")
            continue
        right_values = df[right] if isinstance(right, str) and right in df.columns else rule.get("right_value")
        valid = ops[op](df[left], right_values)
        valid = valid.fillna(False) if hasattr(valid, "fillna") else pd.Series(bool(valid), index=df.index)
        violations = ~valid
        count = int(violations.sum())
        flag_column = rule.get("flag_column", f"{name}_violation")
        if rule.get("action", "flag") == "drop":
            df.drop(index=df[violations].index, inplace=True)
        else:
            df[flag_column] = violations
        report["rules"].append({"name": name, "violations": count, "action": rule.get("action", "flag")})


def _evaluate_cross_table_rules(conn, df, rules: list[dict[str, Any]], report: dict[str, Any]) -> None:
    import pandas as pd

    ops = {
        "<": lambda l, r: l < r,
        "<=": lambda l, r: l <= r,
        ">": lambda l, r: l > r,
        ">=": lambda l, r: l >= r,
        "==": lambda l, r: l == r,
        "!=": lambda l, r: l != r,
    }
    for rule in rules:
        name = rule.get("name", "cross_table_rule")
        other_table = validate_table_name(rule.get("table", ""))
        left_keys = rule.get("left_key") or rule.get("left_keys") or rule.get("key")
        right_keys = rule.get("right_key") or rule.get("right_keys") or rule.get("key")
        if isinstance(left_keys, str):
            left_keys = [left_keys]
        if isinstance(right_keys, str):
            right_keys = [right_keys]
        if not left_keys or not right_keys or len(left_keys) != len(right_keys):
            report["warnings"].append(f"跨表规则跳过：键配置无效 {name}")
            continue
        other_df = conn.execute(f"SELECT * FROM {quote_identifier(other_table)}").fetchdf()
        right_col = rule.get("right")
        left_col = rule.get("left")
        op = rule.get("op")
        if left_col not in df.columns or right_col not in other_df.columns or op not in ops:
            report["warnings"].append(f"跨表规则跳过：字段或操作符无效 {name}")
            continue
        right_check_col = f"__right_{right_col}"
        right_columns = list(dict.fromkeys(right_keys + [right_col]))
        other_subset = other_df[right_columns].rename(columns={right_col: right_check_col})
        merged = df.merge(other_subset, left_on=left_keys, right_on=right_keys, how="left")
        valid = ops[op](merged[left_col], merged[right_check_col])
        violations = (~valid.fillna(False))
        report["cross_table_rules"].append({"name": name, "violations": int(violations.sum())})


def clean_table_data(
    db_path: str,
    table_name: str,
    output_table: str | None = None,
    config: dict[str, Any] | None = None,
    config_path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Clean a DuckDB table using configurable rules and save the result.

    Python applies explicit rules only. Agents should use
    `workflow_specs/data_cleaning_workflow.md` to ask for business-specific
    rules before calling this function.
    """
    import pandas as pd

    table_name = validate_table_name(table_name)
    config = _normalize_config({**_load_rules(config_path), **(config or {})})
    output_table = validate_table_name(output_table or config.get("output_table") or f"{table_name}_cleaned")

    report: dict[str, Any] = {
        "source_table": table_name,
        "output_table": output_table,
        "dry_run": dry_run,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "warnings": [],
        "type_conversions": [],
        "missing_values": [],
        "text_cleaning": [],
        "boolean_mappings": [],
        "normalization": [],
        "derived_features": [],
        "masking": [],
        "outliers": [],
        "rules": [],
        "cross_table_rules": [],
    }

    repo = get_repository(db_path)
    with repo.connection() as conn:
        df = conn.execute(f"SELECT * FROM {quote_identifier(table_name)}").fetchdf()
        report["input_rows"] = int(len(df))
        report["input_columns"] = list(map(str, df.columns))

        _apply_type_conversions(df, config["type_conversions"], report)
        _apply_text_cleaning(df, config["text_cleaning"], report)
        _apply_boolean_mappings(df, config["boolean_mappings"], report)
        _apply_missing_values(df, config["missing_values"], report)
        _apply_outliers(df, config["outliers"], report)
        _apply_normalization(df, config["normalization"], report)
        _apply_derived_features(df, config["derived_features"], report)
        _apply_masking(df, config["masking"], report)
        _evaluate_rules(df, config["rules"], report)
        _evaluate_cross_table_rules(conn, df, config["cross_table_rules"], report)
        _apply_deduplication(df, config, report)

        report["output_rows"] = int(len(df))
        report["removed_rows"] = report["input_rows"] - report["output_rows"]
        report["output_columns"] = list(map(str, df.columns))

        if not dry_run:
            conn.register("_cleaned_df", df)
            conn.execute(f"CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS SELECT * FROM _cleaned_df")
            conn.unregister("_cleaned_df")

        if config.get("report_path"):
            path = Path(config["report_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("数据清洗完成", source_table=table_name, output_table=output_table, rows=report["output_rows"])
    return report

def clean_old_data(db_path, days=30):
    """
    Clean up tables and metadata that haven't been used in the specified number of days.
    """
    repo = get_repository(db_path)

    with repo.connection() as conn:
        # Check if metadata table exists
        exists_result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = '_data_skill_meta'"
        ).fetchone()
        if not exists_result:
            logger.info("未找到元数据表，无需清理")
            return

        # Calculate the cutoff date
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        # Find tables to drop
        stale_records = conn.execute('''
            SELECT table_name, file_name, last_used_time
            FROM _data_skill_meta
            WHERE last_used_time < ?
        ''', [cutoff_date]).fetchall()

        if not stale_records:
            logger.info("未找到过期数据", days=days)
            return

        logger.info("开始清理过期数据", count=len(stale_records), days=days)

        for record in stale_records:
            table_name, file_name, last_used = record
            logger.info("删除过期表", table_name=table_name, file_name=file_name, last_used=last_used)

            # Validate table name before using in SQL to prevent injection
            try:
                validated_name = validate_table_name(table_name)
            except ValueError as e:
                logger.warning("跳过无效表名", table_name=table_name, reason=str(e))
                continue

            # Drop the actual table
            conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(validated_name)}")

            # Remove from metadata
            conn.execute("DELETE FROM _data_skill_meta WHERE table_name = ?", [table_name])

        conn.commit()
        logger.info("清理完成", deleted_count=len(stale_records))

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean DuckDB data or remove old unused tables")
    subparsers = parser.add_subparsers(dest="command")

    old_parser = subparsers.add_parser("old", help="Clean old unused data from metadata")
    old_parser.add_argument("--db", default="workspace.duckdb", help="Path to DuckDB database file")
    old_parser.add_argument("--days", type=int, default=30, help="Number of days of inactivity before cleaning")

    table_parser = subparsers.add_parser("table", help="Clean table content with configurable rules")
    table_parser.add_argument("table", help="Source table name")
    table_parser.add_argument("--db", default="workspace.duckdb", help="Path to DuckDB database file")
    table_parser.add_argument("--output-table", help="Output table name")
    table_parser.add_argument("--config", help="JSON cleaning rule file")
    table_parser.add_argument("--unique-key", help="Comma-separated unique key columns for deduplication")
    table_parser.add_argument("--duplicate-keep", default="first", choices=["first", "last", "latest"], help="Duplicate keep strategy")
    table_parser.add_argument("--duplicate-order-by", help="Column used when duplicate-keep=latest")
    table_parser.add_argument("--dry-run", action="store_true", help="Return report without writing cleaned table")

    # Backward-compatible root args for old cleanup behavior.
    parser.add_argument("--db", default="workspace.duckdb", help=argparse.SUPPRESS)
    parser.add_argument("--days", type=int, default=30, help=argparse.SUPPRESS)
    return parser


if __name__ == "__main__":  # pragma: no cover
    parser = _build_parser()
    args = parser.parse_args()

    command = args.command or "old"

    try:
        if command == "table":
            inline_config = {
                "unique_key": args.unique_key,
                "duplicate_keep": args.duplicate_keep,
                "duplicate_order_by": args.duplicate_order_by,
            }
            inline_config = {k: v for k, v in inline_config.items() if v}
            result = clean_table_data(
                db_path=args.db,
                table_name=args.table,
                output_table=args.output_table,
                config=inline_config,
                config_path=args.config,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            clean_old_data(args.db, args.days)
    except Exception as e:
        logger.error("清理失败", error=str(e))
        raise
