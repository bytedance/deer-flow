"""
Database Connection Manager.

Manages external database connection profiles at two levels:

- **global**: Stored in ``references/db_connections.txt`` (skill root).
  These connections are available to all projects.
- **project**: Stored in ``.echart-skill/db_connections.txt`` (project directory).
  These connections are only effective when the current working directory is
  inside the recorded project directory.

Project-level connections **override** global connections with the same name.

Usage:
    # Add a PostgreSQL connection (global)
    python scripts/db_manager.py add --name analytics --type postgresql \\
        --host localhost --database analytics --username reader

    # Add a project-level connection
    python scripts/db_manager.py add --name prod_db --type mysql \\
        --host db.internal --database production --level project

    # List effective connections for current directory
    python scripts/db_manager.py list

    # Test a connection
    python scripts/db_manager.py test analytics

    # Show effective config (merged global + project)
    python scripts/db_manager.py effective
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

# Ensure project root is on sys.path for imports
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
GLOBAL_DB_CONFIG_PATH = PROJECT_ROOT / "references" / "db_connections.txt"
PROJECT_INDEX_PATH = PROJECT_ROOT / "references" / "project_db_index.json"
PROJECT_DB_DIRNAME = ".echart-skill"
PROJECT_DB_FILENAME = "db_connections.txt"

# Supported database types
SUPPORTED_DB_TYPES = {"mysql", "postgresql", "mongodb"}

# Default ports per database type
DEFAULT_PORTS = {
    "mysql": 3306,
    "postgresql": 5432,
    "mongodb": 27017,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ConnectionInfo:
    """Lightweight connection metadata for display."""
    name: str
    type: str
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    level: str = "global"  # "global" or "project"
    project_dir: str = ""
    has_password: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _resolve_path(file_path: str | os.PathLike[str]) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _init_db_config_file(path: Path, project_dir: str = "") -> None:
    """Create an empty db_connections.txt if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    lines = [
        "# 数据库连接配置 (Database Connections)",
        "#",
        "# 支持数据库类型: mysql, postgresql, mongodb",
        "# 密码请使用 ${ENV_VAR} 占位符引用环境变量，切勿硬编码密码。",
        "# 每个连接使用 [connections.<name>] 区块定义。",
        "#",
        "# 示例:",
        "#   [connections.my_pg]",
        "#   type=postgresql",
        "#   host=localhost",
        "#   port=5432",
        "#   database=analytics",
        "#   username=reader",
        "#   password=${PG_PASSWORD}",
        "",
    ]
    if project_dir:
        lines.insert(0, f"# 项目目录: {project_dir}")
        lines.insert(1, "# 仅当当前执行目录位于该项目目录下时，本配置中的连接才生效。")
        lines.insert(2, "")
    path.write_text("\n".join(lines), encoding="utf-8")


def _load_project_index() -> list[dict]:
    """Load the project database config index (delegates to shared module)."""
    return load_index(PROJECT_INDEX_PATH)


def _save_project_index(items: list[dict]) -> None:
    """Save the project database config index (delegates to shared module)."""
    save_index(PROJECT_INDEX_PATH, items)


def _record_project(project_dir: Path, db_config_path: Path) -> None:
    """Record a project's database config in the index (delegates to shared module)."""
    record_project(PROJECT_INDEX_PATH, project_dir, db_config_path)


_is_relative_to = is_relative_to  # re-export from shared module


def _active_project_records(cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return project db config records whose directory contains cwd."""
    records = active_records(PROJECT_INDEX_PATH, cwd)
    # Remap shared "config_path" key to "db_config_path" for backward compat
    for r in records:
        if "config_path" in r and "db_config_path" not in r:
            r["db_config_path"] = r.pop("config_path")
    return records


def _parse_connection_config(path: Path) -> Dict[str, Any]:
    """Parse a db_connections.txt file and return the connections dict.

    Returns an empty dict if the file doesn't exist or has no connections.
    """
    if not path.exists():
        return {}
    try:
        data = parse_txt_config(path)
        return data.get("connections", {})
    except (ValueError, OSError) as e:
        logger.warning(f"Failed to parse {path}: {e}")
        return {}


def _format_connection_config(connections: Dict[str, Any]) -> str:
    """Format connections dict as db_connections.txt content."""
    if not connections:
        return ""
    # Build a nested dict in the expected format
    data = {"connections": connections}
    return dump_txt_config(data)


def _connection_to_info(
    name: str, profile: dict, level: str = "global", project_dir: str = ""
) -> ConnectionInfo:
    """Convert a raw connection profile dict to ConnectionInfo."""
    return ConnectionInfo(
        name=name,
        type=profile.get("type", "unknown"),
        host=profile.get("host", ""),
        port=profile.get("port", DEFAULT_PORTS.get(profile.get("type", ""), 0)),
        database=profile.get("database", ""),
        username=profile.get("username", ""),
        level=level,
        project_dir=project_dir,
        has_password=bool(profile.get("password") or profile.get("connection_string")),
    )


def _mask_sensitive(profile: dict) -> dict:
    """Return a copy with password masked for display."""
    result = dict(profile)
    if "password" in result:
        result["password"] = "***"
    if "connection_string" in result:
        result["connection_string"] = "***masked***"
    if "uri" in result:
        result["uri"] = "***masked***"
    return result


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------
def add_connection(
    name: str,
    db_type: str,
    host: str = "",
    port: int = 0,
    database: str = "",
    username: str = "",
    password: str = "",
    connection_string: str = "",
    level: str = "global",
    project_dir: str | None = None,
    **extra_opts,
) -> ConnectionInfo:
    """Add a new database connection profile.

    Args:
        name: Connection profile name (unique within its level).
        db_type: Database type (mysql, postgresql, mongodb).
        host: Database host.
        port: Database port (defaults to type-specific default if 0).
        database: Database name.
        username: Authentication username.
        password: Password or ${ENV_VAR} placeholder.
        connection_string: Full connection string (overrides individual fields).
        level: "global" or "project".
        project_dir: Project directory (required for level="project").
        **extra_opts: Additional options (db_schema, timeout, uri).

    Returns:
        ConnectionInfo for the added connection.

    Raises:
        ValueError: If db_type is unsupported or connection name already exists.
    """
    if db_type not in SUPPORTED_DB_TYPES:
        raise ValueError(
            f"Unsupported database type: {db_type}. "
            f"Supported types: {', '.join(sorted(SUPPORTED_DB_TYPES))}"
        )

    if level not in {"global", "project"}:
        raise ValueError("level must be 'global' or 'project'")

    # Determine target path
    if level == "global":
        target_path = GLOBAL_DB_CONFIG_PATH
        _init_db_config_file(target_path)
    else:
        proj = Path(project_dir or os.getcwd()).resolve()
        target_path = proj / PROJECT_DB_DIRNAME / PROJECT_DB_FILENAME
        _init_db_config_file(target_path, str(proj))

    # Load existing connections
    existing = _parse_connection_config(target_path)
    if name in existing:
        raise ValueError(
            f"Connection '{name}' already exists at {level} level. "
            f"Use 'remove' first or choose a different name."
        )

    # Build connection profile
    if not port:
        port = DEFAULT_PORTS.get(db_type, 0)

    profile: dict = {"type": db_type}
    if connection_string:
        profile["connection_string"] = connection_string
    else:
        if host:
            profile["host"] = host
        if port:
            profile["port"] = port
        if database:
            profile["database"] = database
        if username:
            profile["username"] = username
        if password:
            if not password.startswith("${") and not password.endswith("}"):
                logger.warning(
                    "Password for connection '%s' is plaintext. "
                    "Consider using ${ENV_VAR} placeholder instead.", name
                )
            profile["password"] = password

    # Add extra options
    for key, value in extra_opts.items():
        if value is not None and value != "" and key not in profile:
            profile[key] = value

    # Save
    existing[name] = profile
    target_path.write_text(_format_connection_config(existing), encoding="utf-8")

    # Record project if applicable
    if level == "project":
        _record_project(Path(project_dir or os.getcwd()), target_path)

    logger.info(f"Added {level} connection '{name}' ({db_type})")
    return _connection_to_info(name, profile, level, project_dir or "")


def remove_connection(
    name: str,
    level: str = "global",
    project_dir: str | None = None,
) -> bool:
    """Remove a database connection profile.

    Args:
        name: Connection profile name.
        level: "global" or "project".
        project_dir: Project directory (for project level).

    Returns:
        True if removed, False if not found.
    """
    if level not in {"global", "project"}:
        raise ValueError("level must be 'global' or 'project'")

    if level == "global":
        target_path = GLOBAL_DB_CONFIG_PATH
    else:
        proj = Path(project_dir or os.getcwd()).resolve()
        target_path = proj / PROJECT_DB_DIRNAME / PROJECT_DB_FILENAME

    if not target_path.exists():
        return False

    existing = _parse_connection_config(target_path)
    if name not in existing:
        return False

    del existing[name]
    target_path.write_text(_format_connection_config(existing), encoding="utf-8")
    logger.info(f"Removed {level} connection '{name}'")
    return True


def get_connection(name: str, cwd: str | None = None) -> Optional[dict]:
    """Get a single effective connection by name (project overrides global).

    Args:
        name: Connection profile name.
        cwd: Current working directory for project config resolution.

    Returns:
        Connection profile dict, or None if not found.
    """
    effective = get_effective_connections(cwd)
    return effective.get(name)


def get_effective_connections(cwd: str | None = None) -> Dict[str, dict]:
    """Get all effective connections (global merged with project, project wins).

    Args:
        cwd: Current working directory.

    Returns:
        Merged connections dict.
    """
    # Start with global connections
    merged = dict(_parse_connection_config(GLOBAL_DB_CONFIG_PATH))

    # Overlay project connections (least-specific first → most-specific wins)
    for record in reversed(_active_project_records(cwd)):
        config_path = Path(record["db_config_path"])
        project_connections = _parse_connection_config(config_path)
        merged.update(project_connections)  # Project overrides global

    return merged


def list_connections(
    level: str = "effective", cwd: str | None = None
) -> List[ConnectionInfo]:
    """List connection profiles.

    Args:
        level: "global", "project", or "effective".
        cwd: Current working directory.

    Returns:
        List of ConnectionInfo objects.
    """
    result: List[ConnectionInfo] = []

    if level in ("global", "effective"):
        global_conns = _parse_connection_config(GLOBAL_DB_CONFIG_PATH)
        for name, profile in global_conns.items():
            result.append(_connection_to_info(name, profile, "global"))

    if level in ("project", "effective"):
        # Iterate least-specific first so most-specific wins in effective mode
        for record in reversed(_active_project_records(cwd)):
            config_path = Path(record["db_config_path"])
            project_conns = _parse_connection_config(config_path)
            project_dir = record.get("project_dir", "")
            for name, profile in project_conns.items():
                if level == "effective":
                    # In effective mode, project overrides global — remove
                    # the global entry with the same name
                    result = [r for r in result if r.name != name]
                result.append(
                    _connection_to_info(name, profile, "project", project_dir)
                )

    return result


def show_connection(name: str, cwd: str | None = None) -> Optional[dict]:
    """Show detailed (masked) info for a connection.

    Args:
        name: Connection profile name.
        cwd: Current working directory.

    Returns:
        Masked connection profile dict, or None if not found.
    """
    # Check project connections first (they take precedence)
    for record in _active_project_records(cwd):
        config_path = Path(record["db_config_path"])
        project_conns = _parse_connection_config(config_path)
        if name in project_conns:
            return _mask_sensitive(project_conns[name])

    # Fall back to global
    global_conns = _parse_connection_config(GLOBAL_DB_CONFIG_PATH)
    if name in global_conns:
        return _mask_sensitive(global_conns[name])

    return None


def test_connection(name: str, cwd: str | None = None) -> Tuple[bool, str]:
    """Test if a database connection works.

    Args:
        name: Connection profile name.
        cwd: Current working directory.

    Returns:
        Tuple of (success: bool, message: str).
    """
    from scripts.db_config import ConnectionProfile
    from scripts.db_connector import create_connector

    profile_dict = get_connection(name, cwd)
    if profile_dict is None:
        return False, f"Connection '{name}' not found in effective config."

    try:
        profile = ConnectionProfile(**profile_dict)
        connector = create_connector(profile)
        try:
            connector.connect()
            connector.test_connection()
            connector.close()
            return True, f"Connection '{name}' ({profile.type}) test successful."
        finally:
            try:
                connector.close()
            except Exception:
                pass
    except ImportError as e:
        return False, f"Missing driver: {e}"
    except Exception as e:
        return False, f"Connection test failed: {e}"


def render_effective_config(cwd: str | None = None) -> str:
    """Render effective connections as a txt config string.

    Args:
        cwd: Current working directory.

    Returns:
        Formatted config text.
    """
    effective = get_effective_connections(cwd)
    if not effective:
        return "# 暂无有效的数据库连接配置。\n"
    return _format_connection_config(effective)


def _print_connections(level: str, cwd: str | None = None) -> None:
    """Print connection list to stdout."""
    connections = list_connections(level, cwd)
    if not connections:
        print("暂无数据库连接配置。")
        return

    # Calculate column widths
    name_width = max(max(len(c.name) for c in connections), 6)
    type_width = max(max(len(c.type) for c in connections), 4)
    host_width = max(max(len(c.host) for c in connections), 4)
    db_width = max(max(len(c.database) for c in connections), 8)

    header = (
        f"| {'Name':<{name_width}} | {'Type':<{type_width}} "
        f"| {'Host':<{host_width}} | {'Database':<{db_width}} "
        f"| {'Port':>5} | {'Level':<7} |"
    )
    sep = (
        f"|-{'-' * name_width}-|-{'-' * type_width}-"
        f"-|-{'-' * host_width}-|-{'-' * db_width}-"
        f"-|------:|---------|"
    )

    print(header)
    print(sep)
    for c in connections:
        print(
            f"| {c.name:<{name_width}} | {c.type:<{type_width}} "
            f"| {c.host:<{host_width}} | {c.database:<{db_width}} "
            f"| {c.port:>5} | {c.level:<7} |"
        )


def _print_connection_detail(name: str, cwd: str | None = None) -> None:
    """Print detailed connection info to stdout."""
    info = show_connection(name, cwd)
    if info is None:
        print(f"❌ 连接 '{name}' 不存在。")
        return

    print(f"\n📋 连接详情: {name}")
    print("-" * 40)
    for key, value in info.items():
        print(f"  {key}: {value}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for db_manager CLI."""
    parser = argparse.ArgumentParser(
        prog="db-manager",
        description="管理外部数据库连接配置（全局 / 项目级别）",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- add ---
    add_parser = subparsers.add_parser("add", help="添加数据库连接")
    add_parser.add_argument("--name", "-n", required=True, help="连接名称")
    add_parser.add_argument(
        "--type", "-t", required=True,
        choices=sorted(SUPPORTED_DB_TYPES), help="数据库类型"
    )
    add_parser.add_argument("--host", help="数据库主机地址")
    add_parser.add_argument("--port", type=int, default=0, help="端口号")
    add_parser.add_argument("--database", "--db", help="数据库名")
    add_parser.add_argument("--username", "-u", help="用户名")
    add_parser.add_argument("--password", "-p", help="密码或 ${ENV_VAR} 占位符")
    add_parser.add_argument("--connection-string", help="完整连接字符串")
    add_parser.add_argument(
        "--level", choices=["global", "project"], default="global",
        help="连接级别 (默认: global)"
    )
    add_parser.add_argument("--project-dir", help="项目目录 (level=project 时使用)")
    add_parser.add_argument("--schema", help="数据库 schema (PostgreSQL)")
    add_parser.add_argument("--timeout", type=float, default=30.0, help="连接超时秒数")
    add_parser.set_defaults(func=_cmd_add)

    # --- list ---
    list_parser = subparsers.add_parser("list", help="列出数据库连接")
    list_parser.add_argument(
        "--level", choices=["global", "project", "effective"],
        default="effective", help="连接级别"
    )
    list_parser.add_argument("--cwd", help="当前工作目录")
    list_parser.set_defaults(func=_cmd_list)

    # --- show ---
    show_parser = subparsers.add_parser("show", help="查看连接详情")
    show_parser.add_argument("name", help="连接名称")
    show_parser.add_argument("--cwd", help="当前工作目录")
    show_parser.set_defaults(func=_cmd_show)

    # --- remove ---
    remove_parser = subparsers.add_parser("remove", help="删除数据库连接")
    remove_parser.add_argument("name", help="连接名称")
    remove_parser.add_argument(
        "--level", choices=["global", "project"], default="global",
        help="连接级别"
    )
    remove_parser.add_argument("--project-dir", help="项目目录 (level=project 时使用)")
    remove_parser.set_defaults(func=_cmd_remove)

    # --- test ---
    test_parser = subparsers.add_parser("test", help="测试数据库连接")
    test_parser.add_argument("name", help="连接名称")
    test_parser.add_argument("--cwd", help="当前工作目录")
    test_parser.set_defaults(func=_cmd_test)

    # --- effective ---
    effective_parser = subparsers.add_parser("effective", help="输出当前生效的连接配置")
    effective_parser.add_argument("--cwd", help="当前工作目录")
    effective_parser.set_defaults(func=_cmd_effective)

    return parser


def _cmd_add(args: argparse.Namespace) -> None:
    """Handle 'add' command."""
    try:
        info = add_connection(
            name=args.name,
            db_type=args.type,
            host=args.host or "",
            port=args.port,
            database=args.database or "",
            username=args.username or "",
            password=args.password or "",
            connection_string=args.connection_string or "",
            level=args.level,
            project_dir=args.project_dir,
            db_schema=args.schema or "",
            timeout=args.timeout,
        )
        print(f"✅ 成功添加 {info.level} 连接: {info.name}")
        print(f"   类型: {info.type}")
        if info.host:
            print(f"   主机: {info.host}:{info.port}")
        if info.database:
            print(f"   数据库: {info.database}")
    except ValueError as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    """Handle 'list' command."""
    _print_connections(args.level, args.cwd)


def _cmd_show(args: argparse.Namespace) -> None:
    """Handle 'show' command."""
    _print_connection_detail(args.name, args.cwd)


def _cmd_remove(args: argparse.Namespace) -> None:
    """Handle 'remove' command."""
    try:
        ok = remove_connection(args.name, args.level, args.project_dir)
        if ok:
            print(f"✅ 成功删除 {args.level} 连接: {args.name}")
        else:
            print(f"❌ 连接 '{args.name}' 不存在于 {args.level} 级别。")
            sys.exit(1)
    except ValueError as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


def _cmd_test(args: argparse.Namespace) -> None:
    """Handle 'test' command."""
    print(f"🔍 正在测试连接 '{args.name}'...")
    success, message = test_connection(args.name, args.cwd)
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
        sys.exit(1)


def _cmd_effective(args: argparse.Namespace) -> None:
    """Handle 'effective' command."""
    print(render_effective_config(args.cwd))


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
