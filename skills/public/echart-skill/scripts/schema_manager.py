"""
Table Schema Definition Manager.

Manages table structure definitions (column names, types, descriptions) at two levels:

- **global**: Stored in ``references/table_schemas.txt`` (skill root).
  Available to all projects.
- **project**: Stored in ``.echart-skill/table_schemas.txt`` (project directory).
  Only effective when working inside the recorded project directory.

Project-level definitions **override** global definitions for the same table name.

Format (txt, compatible with parse_txt_config)::

    [schemas.orders]
    description=订单表，记录所有交易

    [schemas.orders.column.order_id]
    type=VARCHAR
    nullable=false
    description=订单唯一标识
    primary_key=true

    [schemas.orders.column.amount]
    type=DECIMAL(18,2)
    nullable=false
    description=订单金额

Usage:
    # Add a table schema (global)
    python scripts/schema_manager.py add --name orders --desc "订单表" \\
        --columns "order_id:VARCHAR:订单ID:pk,amount:DECIMAL(18,2):金额,status:VARCHAR:状态"

    # Add project-level schema
    python scripts/schema_manager.py add --name orders --desc "项目订单表" \\
        --columns "..." --level project

    # List effective schemas
    python scripts/schema_manager.py list

    # Show a table schema
    python scripts/schema_manager.py show orders
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logging_config import get_logger
from scripts.text_config import parse_txt_config, dump_txt_config
from scripts._project_index import (
    is_relative_to,
    load_index,
    save_index,
    record_project,
    active_records,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_SCHEMA_PATH = PROJECT_ROOT / "references" / "table_schemas.txt"
SCHEMA_INDEX_PATH = PROJECT_ROOT / "references" / "project_schema_index.json"
PROJECT_DIRNAME = ".echart-skill"
PROJECT_SCHEMA_FILENAME = "table_schemas.txt"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ColumnDef:
    """Single column definition."""
    name: str
    type: str = ""
    nullable: bool = True
    description: str = ""
    primary_key: bool = False


@dataclass
class TableSchema:
    """Complete table schema definition."""
    name: str
    description: str = ""
    columns: List[ColumnDef] = field(default_factory=list)
    level: str = "global"
    project_dir: str = ""

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def pk_columns(self) -> List[ColumnDef]:
        return [c for c in self.columns if c.primary_key]


# ---------------------------------------------------------------------------
# Column shorthand parser
# ---------------------------------------------------------------------------
def parse_column_shorthand(spec: str) -> ColumnDef:
    """Parse a column shorthand string into a ColumnDef.

    Format: ``name:type:description:flags``

    Examples:
        order_id:VARCHAR:订单ID:pk
        amount:DECIMAL(18,2):订单金额
        status:VARCHAR:订单状态:nullable

    Flags:
        pk / primary_key — mark as primary key
        required / notnull — mark as NOT NULL
        nullable — explicitly mark as nullable (default)
    """
    parts = spec.split(":")
    name = parts[0].strip()
    col_type = parts[1].strip() if len(parts) > 1 else ""
    description = parts[2].strip() if len(parts) > 2 else ""
    flags = [f.strip().lower() for f in parts[3:]] if len(parts) > 3 else []

    col = ColumnDef(name=name, type=col_type, description=description)

    # Process nullable first (weakest), then pk/required (strongest)
    for flag in flags:
        if flag == "nullable":
            col.nullable = True
    for flag in flags:
        if flag in ("pk", "primary_key"):
            col.primary_key = True
            col.nullable = False
        elif flag in ("required", "notnull", "not_null"):
            col.nullable = False

    return col


def parse_columns_shorthand(columns_spec: str) -> List[ColumnDef]:
    """Parse comma-separated column specs (commas inside parentheses are ignored).

    Example: ``"order_id:INT:ID:pk, amount:DECIMAL(18,2):金额, status:VARCHAR:状态"``
    """
    columns = []
    # Split by commas not inside parentheses
    parts = _split_outside_parens(columns_spec, ",")
    for part in parts:
        part = part.strip()
        if part:
            columns.append(parse_column_shorthand(part))
    return columns


def _split_outside_parens(text: str, sep: str = ",") -> List[str]:
    """Split text by separator, ignoring separators inside parentheses."""
    result: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            result.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        result.append("".join(current))
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _init_schema_file(path: Path, project_dir: str = "") -> None:
    """Create an empty table_schemas.txt if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    lines = [
        "# 表结构定义 (Table Schema Definitions)",
        "#",
        "# 格式: [schemas.<表名>] 区块定义表，[schemas.<表名>.column.<列名>] 定义列。",
        "#",
        "# 示例:",
        "#   [schemas.orders]",
        "#   description=订单表",
        "#   [schemas.orders.column.order_id]",
        "#   type=VARCHAR",
        "#   nullable=false",
        "#   description=订单ID",
        "#   primary_key=true",
        "",
    ]
    if project_dir:
        lines.insert(0, f"# 项目目录: {project_dir}")
        lines.insert(1, "# 仅当当前执行目录位于该项目目录下时，本文件中定义才生效。")
        lines.insert(2, "")
    path.write_text("\n".join(lines), encoding="utf-8")


def _parse_schema_config(path: Path) -> Dict[str, Any]:
    """Parse a table_schemas.txt file and return the schemas dict."""
    if not path.exists():
        return {}
    try:
        data = parse_txt_config(path)
        return data.get("schemas", {})
    except (ValueError, OSError) as e:
        logger.warning(f"Failed to parse {path}: {e}")
        return {}


def _format_schema_config(schemas: Dict[str, Any]) -> str:
    """Format schemas dict as table_schemas.txt content."""
    if not schemas:
        return ""
    return dump_txt_config({"schemas": schemas})


def _raw_to_table_schema(name: str, raw: dict, level: str = "global", project_dir: str = "") -> TableSchema:
    """Convert raw config dict to TableSchema object."""
    description = raw.get("description", "")
    columns_raw = raw.get("column", {})
    columns = []
    for col_name, col_data in columns_raw.items():
        if isinstance(col_data, dict):
            columns.append(ColumnDef(
                name=col_name,
                type=col_data.get("type", ""),
                nullable=col_data.get("nullable", True) if isinstance(col_data.get("nullable"), bool) else True,
                description=col_data.get("description", ""),
                primary_key=col_data.get("primary_key", False) if isinstance(col_data.get("primary_key"), bool) else False,
            ))
    return TableSchema(
        name=name,
        description=description,
        columns=columns,
        level=level,
        project_dir=project_dir,
    )


def _table_schema_to_raw(schema: TableSchema) -> dict:
    """Convert TableSchema to raw config dict."""
    raw: dict = {}
    if schema.description:
        raw["description"] = schema.description
    columns_raw: dict = {}
    for col in schema.columns:
        col_data: dict = {"type": col.type}
        if not col.nullable:
            col_data["nullable"] = False
        if col.description:
            col_data["description"] = col.description
        if col.primary_key:
            col_data["primary_key"] = True
        columns_raw[col.name] = col_data
    if columns_raw:
        raw["column"] = columns_raw
    return raw


# ---------------------------------------------------------------------------
# Project index (tracks which projects have schema configs)
# ---------------------------------------------------------------------------
def _load_schema_index() -> list[dict]:
    return load_index(SCHEMA_INDEX_PATH)


def _save_schema_index(items: list[dict]) -> None:
    save_index(SCHEMA_INDEX_PATH, items)


def _record_project(project_dir: Path, schema_path: Path) -> None:
    record_project(SCHEMA_INDEX_PATH, project_dir, schema_path)


_is_relative_to = is_relative_to


def _active_schema_records(cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    records = active_records(SCHEMA_INDEX_PATH, cwd)
    # Remap shared "config_path" key to "schema_path" for backward compat
    for r in records:
        if "config_path" in r and "schema_path" not in r:
            r["schema_path"] = r.pop("config_path")
    return records


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------
def add_table_schema(
    name: str,
    description: str = "",
    columns: Optional[List[ColumnDef]] = None,
    columns_spec: str = "",
    level: str = "global",
    project_dir: str | None = None,
) -> TableSchema:
    """Add or update a table schema definition.

    Args:
        name: Table name.
        description: Table description.
        columns: List of ColumnDef objects.
        columns_spec: Shorthand column spec string (e.g. "id:INT:主键:pk,name:VARCHAR:名称").
        level: "global" or "project".
        project_dir: Project directory (for project level).

    Returns:
        TableSchema object.
    """
    if level not in {"global", "project"}:
        raise ValueError("level must be 'global' or 'project'")

    # Determine target path
    if level == "global":
        target_path = GLOBAL_SCHEMA_PATH
    else:
        proj = Path(project_dir or os.getcwd()).resolve()
        target_path = proj / PROJECT_DIRNAME / PROJECT_SCHEMA_FILENAME

    _init_schema_file(target_path, project_dir if level == "project" else "")

    # Parse columns from spec if provided
    if columns_spec and not columns:
        columns = parse_columns_shorthand(columns_spec)
    columns = columns or []

    # Load existing schemas
    existing = _parse_schema_config(target_path)

    # Build new schema
    schema = TableSchema(
        name=name,
        description=description,
        columns=columns,
        level=level,
        project_dir=project_dir or "",
    )

    existing[name] = _table_schema_to_raw(schema)

    # Save
    target_path.write_text(_format_schema_config(existing), encoding="utf-8")

    # Record project if applicable
    if level == "project":
        _record_project(Path(project_dir or os.getcwd()), target_path)

    logger.info(f"Added {level} table schema '{name}' ({len(columns)} columns)")
    return schema


def remove_table_schema(
    name: str,
    level: str = "global",
    project_dir: str | None = None,
) -> bool:
    """Remove a table schema definition.

    Args:
        name: Table name.
        level: "global" or "project".
        project_dir: Project directory (for project level).

    Returns:
        True if removed, False if not found.
    """
    if level not in {"global", "project"}:
        raise ValueError("level must be 'global' or 'project'")

    if level == "global":
        target_path = GLOBAL_SCHEMA_PATH
    else:
        proj = Path(project_dir or os.getcwd()).resolve()
        target_path = proj / PROJECT_DIRNAME / PROJECT_SCHEMA_FILENAME

    if not target_path.exists():
        return False

    existing = _parse_schema_config(target_path)
    if name not in existing:
        return False

    del existing[name]
    target_path.write_text(_format_schema_config(existing), encoding="utf-8")

    # Clean up project index if all schemas removed from this project
    if level == "project" and not existing:
        items = _load_schema_index()
        proj = str(Path(project_dir or os.getcwd()).resolve())
        _save_schema_index([it for it in items if it.get("project_dir") != proj])

    logger.info(f"Removed {level} table schema '{name}'")
    return True


def get_effective_schemas(cwd: str | None = None) -> Dict[str, TableSchema]:
    """Get all effective table schemas (global + project merged, project wins).

    Args:
        cwd: Current working directory.

    Returns:
        Dict of table_name -> TableSchema.
    """
    result: Dict[str, TableSchema] = {}

    # Load global first
    global_raw = _parse_schema_config(GLOBAL_SCHEMA_PATH)
    for name, raw in global_raw.items():
        if isinstance(raw, dict):
            result[name] = _raw_to_table_schema(name, raw, "global")

    # Overlay project schemas
    # Iterate least-specific first so most-specific wins (reversed)
    for record in reversed(_active_schema_records(cwd)):
        proj_raw = _parse_schema_config(Path(record["schema_path"]))
        project_dir = record.get("project_dir", "")
        for name, raw in proj_raw.items():
            if isinstance(raw, dict):
                result[name] = _raw_to_table_schema(name, raw, "project", project_dir)

    return result


def get_table_schema(name: str, cwd: str | None = None) -> Optional[TableSchema]:
    """Get effective schema for a single table.

    Args:
        name: Table name.
        cwd: Current working directory.

    Returns:
        TableSchema or None if not found.
    """
    return get_effective_schemas(cwd).get(name)


def list_table_schemas(
    level: str = "effective",
    cwd: str | None = None,
) -> List[TableSchema]:
    """List table schema definitions.

    Args:
        level: "global", "project", or "effective".
        cwd: Current working directory.

    Returns:
        List of TableSchema objects.
    """
    result: List[TableSchema] = []

    if level in ("global", "effective"):
        global_raw = _parse_schema_config(GLOBAL_SCHEMA_PATH)
        for name, raw in global_raw.items():
            if isinstance(raw, dict):
                result.append(_raw_to_table_schema(name, raw, "global"))

    if level in ("project", "effective"):
        # Iterate least-specific first so most-specific wins in effective mode
        for record in reversed(_active_schema_records(cwd)):
            proj_raw = _parse_schema_config(Path(record["schema_path"]))
            project_dir = record.get("project_dir", "")
            for name, raw in proj_raw.items():
                if isinstance(raw, dict):
                    if level == "effective":
                        result = [r for r in result if r.name != name]
                    result.append(_raw_to_table_schema(name, raw, "project", project_dir))

    return result


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def _format_schema_markdown(schema: TableSchema) -> str:
    """Format a single table schema as markdown."""
    lines = [
        f"## {schema.name}",
        "",
    ]
    if schema.description:
        lines.append(f"**描述**: {schema.description}")
        lines.append("")
    lines.append(f"**级别**: {schema.level}")
    if schema.project_dir:
        lines.append(f"**项目目录**: `{schema.project_dir}`")
    lines.append(f"**列数**: {schema.column_count}")
    lines.append("")

    if schema.columns:
        lines.append("| 列名 | 类型 | 可空 | 主键 | 描述 |")
        lines.append("|------|------|------|------|------|")
        for col in schema.columns:
            nullable = "YES" if col.nullable else "NO"
            pk = "✓" if col.primary_key else ""
            lines.append(
                f"| {col.name} | {col.type} | {nullable} | {pk} | {col.description} |"
            )
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


def _print_schema_list(schemas: List[TableSchema]) -> None:
    """Print table schema list to stdout."""
    if not schemas:
        print("暂无表结构定义。")
        return

    name_w = max((len(s.name) for s in schemas), default=4)
    cols_w = max((len(str(s.column_count)) for s in schemas), default=4)
    level_w = max((len(s.level) for s in schemas), default=7)

    header = f"| {'表名':<{name_w}} | {'列数':>{cols_w}} | {'级别':<{level_w}} | 描述 |"
    sep = f"|-{'-' * name_w}-|-{'-' * cols_w}-|-{'-' * level_w}-|------|"

    print(header)
    print(sep)
    for s in schemas:
        desc = s.description[:40] + "..." if len(s.description) > 40 else s.description
        print(f"| {s.name:<{name_w}} | {s.column_count:>{cols_w}} | {s.level:<{level_w}} | {desc} |")


def _print_schema_detail(schema: TableSchema) -> None:
    """Print a single schema in detail."""
    print(_format_schema_markdown(schema))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schema-manager",
        description="管理表结构定义（全局 / 项目级别）",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- add ---
    add_parser = subparsers.add_parser("add", help="添加/更新表结构定义")
    add_parser.add_argument("--name", "-n", required=True, help="表名")
    add_parser.add_argument("--desc", "-d", default="", help="表描述")
    add_parser.add_argument(
        "--columns", "-c", default="",
        help='列定义，逗号分隔。格式: "列名:类型:描述:flags" (flags: pk/required/nullable)'
    )
    add_parser.add_argument(
        "--level", choices=["global", "project"], default="global",
        help="定义级别 (默认: global)"
    )
    add_parser.add_argument("--project-dir", help="项目目录 (level=project 时使用)")
    add_parser.set_defaults(func=_cmd_add)

    # --- list ---
    list_parser = subparsers.add_parser("list", help="列出表结构定义")
    list_parser.add_argument(
        "--level", choices=["global", "project", "effective"],
        default="effective", help="级别"
    )
    list_parser.add_argument("--cwd", help="当前工作目录")
    list_parser.set_defaults(func=_cmd_list)

    # --- show ---
    show_parser = subparsers.add_parser("show", help="查看表结构详情")
    show_parser.add_argument("name", help="表名")
    show_parser.add_argument("--cwd", help="当前工作目录")
    show_parser.set_defaults(func=_cmd_show)

    # --- remove ---
    remove_parser = subparsers.add_parser("remove", help="删除表结构定义")
    remove_parser.add_argument("name", help="表名")
    remove_parser.add_argument(
        "--level", choices=["global", "project"], default="global",
        help="级别"
    )
    remove_parser.add_argument("--project-dir", help="项目目录 (level=project 时使用)")
    remove_parser.set_defaults(func=_cmd_remove)

    # --- effective ---
    eff_parser = subparsers.add_parser("effective", help="输出生效的表结构定义")
    eff_parser.add_argument("--cwd", help="当前工作目录")
    eff_parser.set_defaults(func=_cmd_effective)

    return parser


def _cmd_add(args: argparse.Namespace) -> None:
    try:
        schema = add_table_schema(
            name=args.name,
            description=args.desc,
            columns_spec=args.columns,
            level=args.level,
            project_dir=args.project_dir,
        )
        print(f"✅ 已添加 {schema.level} 表结构: {schema.name} ({schema.column_count} 列)")
    except ValueError as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    schemas = list_table_schemas(args.level, args.cwd)
    _print_schema_list(schemas)


def _cmd_show(args: argparse.Namespace) -> None:
    schema = get_table_schema(args.name, args.cwd)
    if schema is None:
        print(f"❌ 表结构 '{args.name}' 不存在。")
        sys.exit(1)
    _print_schema_detail(schema)


def _cmd_remove(args: argparse.Namespace) -> None:
    ok = remove_table_schema(args.name, args.level, args.project_dir)
    if ok:
        print(f"✅ 已删除 {args.level} 表结构: {args.name}")
    else:
        print(f"❌ 表结构 '{args.name}' 不存在于 {args.level} 级别。")
        sys.exit(1)


def _cmd_effective(args: argparse.Namespace) -> None:
    schemas = get_effective_schemas(args.cwd)
    if not schemas:
        print("# 暂无生效的表结构定义。")
        return
    for name, schema in schemas.items():
        print(_format_schema_markdown(schema))


def main(argv: Optional[List[str]] = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
