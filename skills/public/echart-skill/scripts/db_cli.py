"""
Database CLI Module.

Provides command-line interface for database operations:
- query: Execute SQL/MongoDB queries
- list-tables: Discover tables/collections
- describe-table: Get table/collection schema
- import: Import query results to DuckDB
- Connection management: add, list, show, remove, test (delegates to db_manager)

Usage:
    # Query operations
    python scripts/db_cli.py query <profile> "SELECT * FROM users"
    python scripts/db_cli.py list-tables <profile>
    python scripts/db_cli.py describe-table <profile> <table>
    python scripts/db_cli.py import <profile> "SELECT * FROM orders" --table-name orders_import

    # Connection management
    python scripts/db_cli.py add --name my_pg --type postgresql --host localhost --database analytics
    python scripts/db_cli.py list-connections
    python scripts/db_cli.py test my_pg
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from scripts.db_config import load_config, load_effective_config, ConnectionProfile
from scripts.db_connector import create_connector, SQLConnector, MongoDBConnector
from scripts.db_schema import (
    discover_tables, describe_table, format_schema_table,
    list_mongo_databases, list_mongo_collections, infer_mongo_schema, format_mongo_schema
)

logger = get_logger(__name__)

# Default DuckDB path
DEFAULT_DUCKDB = "workspace.duckdb"


def format_table_output(data: List[Dict[str, Any]]) -> str:
    """Format data as markdown table.
    
    Args:
        data: List of row dictionaries
        
    Returns:
        Markdown table string
    """
    if not data:
        return "No results."
    
    df = pd.DataFrame(data)
    return df.to_markdown(index=False)


def format_json_output(data: List[Dict[str, Any]]) -> str:
    """Format data as JSON.
    
    Args:
        data: List of row dictionaries
        
    Returns:
        JSON string
    """
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def get_profile(config_path: Optional[str], profile_name: str) -> ConnectionProfile:
    """Load and validate connection profile using effective config.

    Uses effective config (global + local merged) when no config_path
    is specified. Falls back to auto-discovery for backward compatibility.

    Args:
        config_path: Optional config file path
        profile_name: Profile name to load

    Returns:
        ConnectionProfile instance

    Raises:
        KeyError: If profile not found
        SystemExit: On error (for CLI)
    """
    try:
        if config_path:
            config = load_config(config_path)
        else:
            # Use effective config (global + local merged)
            config = load_effective_config()

        if profile_name not in config.connections:
            available = list(config.connections.keys())
            print(f"Error: Profile '{profile_name}' not found.")
            if available:
                print(f"Available profiles: {', '.join(available)}")
            else:
                print("No connections configured. Use '/db add' or '--config' to specify a config file.")
                print("Or run: python scripts/db_manager.py add --name <name> --type <type> ...")
            sys.exit(1)
        return config.connections[profile_name]
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Create a db_connections.txt file or use '/db add' to configure connections.")
        sys.exit(1)


def cmd_query(args: argparse.Namespace) -> None:
    """Execute database query command (with audit + privacy pipeline)."""
    profile = get_profile(args.config, args.profile)
    connector = create_connector(profile)

    try:
        if args.file:
            query_text = Path(args.file).read_text()
        else:
            query_text = args.query

        if connector.config.type == "mongodb":
            if args.collection is None:
                print("Error: --collection required for MongoDB queries")
                sys.exit(1)
            results = connector.execute_query(query_text, collection=args.collection)
        else:
            # Use audited path with privacy masking
            results = _execute_with_audit(
                connector=connector,
                query=query_text,
                profile_name=args.profile,
            )

        if args.output == "json":
            print(format_json_output(results))
        else:
            print(format_table_output(results))

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        connector.close()


def _execute_with_audit(
    connector: "SQLConnector",
    query: str,
    profile_name: str,
) -> List[Dict[str, Any]]:
    """Execute query with privacy masking + audit logging, same as DuckDB pipeline."""
    from scripts.config_manager import get_config
    from scripts.privacy_guard import PrivacyGuard
    from scripts.audit_report import log_external_query

    results = connector.execute_query(query)
    if not results:
        return results

    cfg = get_config()
    guard = PrivacyGuard(
        enabled=cfg.privacy.enabled,
        read_only=cfg.privacy.read_only,
        audit_enabled=cfg.privacy.audit_enabled,
        mask_pii=cfg.privacy.mask_pii,
        audit_log_path=cfg.privacy.audit_log_path,
    )

    columns = list(results[0].keys())
    guard.enforce_read_only(query)

    classification = guard.classify_columns(profile_name, columns)
    masked = guard.mask_rows(results, classification)

    was_masked = cfg.privacy.mask_pii and any(
        classification.get(col, {}).get("classification", "public") != "public"
        for col in columns
    )
    level_order = {"public": 0, "internal": 1, "sensitive": 2, "restricted": 3}
    max_level = max(
        (classification.get(col, {}).get("classification", "public") for col in columns),
        key=lambda x: level_order.get(x, 0),
        default="public",
    )

    log_external_query(
        query=query,
        connection_name=profile_name,
        db_type=connector.config.type,
        table=profile_name,
        columns=columns,
        row_count=len(masked),
        masked=was_masked,
        classification=max_level,
        log_path=cfg.privacy.audit_log_path,
    )

    return masked


def cmd_list_tables(args: argparse.Namespace) -> None:
    """Execute list-tables command."""
    profile = get_profile(args.config, args.profile)
    connector = create_connector(profile)
    
    try:
        if connector.config.type == "mongodb":
            if args.show_databases:
                databases = list_mongo_databases(connector)
                data = [{"database": db} for db in databases]
            else:
                collections = list_mongo_collections(connector, args.database)
                data = [{"collection": c} for c in collections]
        else:
            tables = discover_tables(connector, args.schema)
            data = [{"table": t} for t in tables]
        
        if args.output == "json":
            print(format_json_output(data))
        else:
            print(format_table_output(data))
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        connector.close()


def cmd_describe_table(args: argparse.Namespace) -> None:
    """Execute describe-table command."""
    profile = get_profile(args.config, args.profile)
    connector = create_connector(profile)
    
    try:
        if connector.config.type == "mongodb":
            schema = infer_mongo_schema(connector, args.table, sample_size=args.sample_size)
            if args.output == "json":
                print(format_json_output([{"field": k, "type": v} for k, v in schema.items()]))
            else:
                print(format_mongo_schema(schema))
        else:
            columns = describe_table(connector, args.table, args.schema)
            if args.output == "json":
                print(format_json_output(columns))
            else:
                print(format_schema_table(columns))
                
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        connector.close()


def cmd_import(args: argparse.Namespace) -> None:
    """Execute import command to DuckDB."""
    profile = get_profile(args.config, args.profile)
    connector = create_connector(profile)
    
    try:
        if args.file:
            query_text = Path(args.file).read_text()
        else:
            query_text = args.query
        
        table_name = args.table_name or generate_table_name(query_text)
        db_path = args.duckdb or "workspace.duckdb"
        
        ensure_duckdb_meta_table(db_path)
        
        if connector.config.type == "mongodb":
            if args.collection is None:
                print("Error: --collection required for MongoDB import")
                sys.exit(1)
            row_count = connector.execute_query_to_duckdb(
                query_text,
                table_name=table_name,
                collection=args.collection,
                db_path=db_path
            )
        else:
            row_count = connector.execute_query_to_duckdb(
                query_text,
                table_name=table_name,
                db_path=db_path
            )
        
        print(f"Imported {row_count} rows to DuckDB table: {table_name}")
        print(f"Database: {db_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        connector.close()


def generate_table_name(query: str) -> str:
    """Generate default table name from query.
    
    Args:
        query: SQL query string
        
    Returns:
        Generated table name
    """
    import re
    
    match = re.search(r'FROM\s+(\w+)', query, re.IGNORECASE)
    if match:
        source_table = match.group(1)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{source_table}_{timestamp}"
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"query_result_{timestamp}"


def ensure_duckdb_meta_table(db_path: str) -> None:
    """Ensure _data_skill_meta table exists in DuckDB.
    
    Args:
        db_path: Path to DuckDB database
    """
    import duckdb
    from scripts.data_importer import init_meta_table
    
    conn = duckdb.connect(db_path)
    try:
        init_meta_table(conn)
    finally:
        conn.close()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="db-cli",
        description="Database connection and query CLI"
    )

    parser.add_argument(
        "--config",
        help="Path to db_connections.txt (uses effective config if not specified)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- Connection management subcommands ---
    _setup_connection_management_subcommands(subparsers)

    # Query command
    query_parser = subparsers.add_parser("query", help="Execute database query")
    query_parser.add_argument("profile", help="Connection profile name")
    query_parser.add_argument("query", nargs="?", help="SQL query string")
    query_parser.add_argument("--file", "-f", help="Query file path")
    query_parser.add_argument("--output", "-o", choices=["table", "json"], default="table",
                              help="Output format")
    query_parser.add_argument("--collection", "-c", help="MongoDB collection name")
    query_parser.set_defaults(func=cmd_query)

    # List tables command
    list_parser = subparsers.add_parser("list-tables", help="List tables/collections")
    list_parser.add_argument("profile", help="Connection profile name")
    list_parser.add_argument("--schema", "-s", help="Schema name (PostgreSQL)")
    list_parser.add_argument("--database", "-d", help="Database name (MongoDB)")
    list_parser.add_argument("--show-databases", action="store_true",
                             help="Show databases instead of collections (MongoDB)")
    list_parser.add_argument("--output", "-o", choices=["table", "json"], default="table",
                             help="Output format")
    list_parser.set_defaults(func=cmd_list_tables)

    # Describe table command
    describe_parser = subparsers.add_parser("describe-table", help="Describe table/collection")
    describe_parser.add_argument("profile", help="Connection profile name")
    describe_parser.add_argument("table", help="Table/collection name")
    describe_parser.add_argument("--schema", "-s", help="Schema name (PostgreSQL)")
    describe_parser.add_argument("--sample-size", type=int, default=100,
                                 help="Sample size for MongoDB schema inference")
    describe_parser.add_argument("--output", "-o", choices=["table", "json"], default="table",
                                 help="Output format")
    describe_parser.set_defaults(func=cmd_describe_table)

    # Import command
    import_parser = subparsers.add_parser("import", help="Import query results to DuckDB")
    import_parser.add_argument("profile", help="Connection profile name")
    import_parser.add_argument("query", nargs="?", help="SQL query string")
    import_parser.add_argument("--file", "-f", help="Query file path")
    import_parser.add_argument("--table-name", "-t", help="Target table name in DuckDB")
    import_parser.add_argument("--duckdb", help="DuckDB database path (default: workspace.duckdb)")
    import_parser.add_argument("--collection", "-c", help="MongoDB collection name")
    import_parser.set_defaults(func=cmd_import)

    return parser


def _setup_connection_management_subcommands(subparsers) -> None:
    """Add connection management subcommands (add, list-connections, remove, test)."""
    # add
    add_parser = subparsers.add_parser("add", help="Add a new database connection profile")
    add_parser.add_argument("--name", "-n", required=True, help="Connection profile name")
    add_parser.add_argument("--type", "-t", required=True,
                            choices=["mysql", "postgresql", "mongodb"],
                            help="Database type")
    add_parser.add_argument("--host", help="Database host")
    add_parser.add_argument("--port", type=int, default=0, help="Port number")
    add_parser.add_argument("--database", "--db", help="Database name")
    add_parser.add_argument("--username", "-u", help="Username")
    add_parser.add_argument("--password", "-p", help="Password or ${ENV_VAR}")
    add_parser.add_argument("--connection-string", help="Full connection string")
    add_parser.add_argument("--level", choices=["global", "project"], default="global",
                            help="Connection level")
    add_parser.add_argument("--project-dir", help="Project directory (for project level)")
    add_parser.add_argument("--schema", help="Database schema (PostgreSQL)")
    add_parser.add_argument("--timeout", type=float, default=30.0, help="Connection timeout in seconds")
    setattr(add_parser, "_subcommand_group", "connection-management")

    # list-connections
    list_conn_parser = subparsers.add_parser(
        "list-connections", aliases=["list-conn", "connections"],
        help="List configured database connections"
    )
    list_conn_parser.add_argument("--level", choices=["global", "project", "effective"],
                                  default="effective", help="Connection level")
    list_conn_parser.add_argument("--cwd", help="Current working directory")
    setattr(list_conn_parser, "_subcommand_group", "connection-management")

    # show
    show_parser = subparsers.add_parser("show-connection", help="Show connection details")
    show_parser.add_argument("name", help="Connection profile name")
    show_parser.add_argument("--cwd", help="Current working directory")
    setattr(show_parser, "_subcommand_group", "connection-management")

    # remove
    remove_parser = subparsers.add_parser("remove-connection", help="Remove a connection profile")
    remove_parser.add_argument("name", help="Connection profile name")
    remove_parser.add_argument("--level", choices=["global", "project"], default="global",
                               help="Connection level")
    remove_parser.add_argument("--project-dir", help="Project directory (for project level)")
    setattr(remove_parser, "_subcommand_group", "connection-management")

    # test
    test_parser = subparsers.add_parser("test-connection", help="Test database connection")
    test_parser.add_argument("name", help="Connection profile name")
    test_parser.add_argument("--cwd", help="Current working directory")
    setattr(test_parser, "_subcommand_group", "connection-management")


# ---------------------------------------------------------------------------
# Connection management command handlers
# ---------------------------------------------------------------------------

def cmd_add_connection(args: argparse.Namespace) -> None:
    """Handle add connection command (delegates to db_manager)."""
    from scripts.db_manager import add_connection as manager_add

    try:
        info = manager_add(
            name=args.name,
            db_type=args.type,
            host=args.host or "",
            port=args.port,
            database=args.database or "",
            username=args.username or "",
            password=args.password or "",
            connection_string=args.connection_string or "",
            level=getattr(args, 'level', 'global'),
            project_dir=getattr(args, 'project_dir', None),
            db_schema=getattr(args, 'schema', '') or '',
            timeout=getattr(args, 'timeout', 30.0),
        )
        print(f"✅ Added {info.level} connection: {info.name} ({info.type})")
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"❌ File error: {e}")
        sys.exit(1)


def cmd_list_connections(args: argparse.Namespace) -> None:
    """Handle list connections command (delegates to db_manager)."""
    from scripts.db_manager import list_connections, _print_connections
    _print_connections(args.level, args.cwd)


def cmd_show_connection(args: argparse.Namespace) -> None:
    """Handle show connection command (delegates to db_manager)."""
    from scripts.db_manager import _print_connection_detail
    _print_connection_detail(args.name, args.cwd)


def cmd_remove_connection(args: argparse.Namespace) -> None:
    """Handle remove connection command (delegates to db_manager)."""
    from scripts.db_manager import remove_connection as manager_remove

    try:
        ok = manager_remove(args.name, args.level, getattr(args, 'project_dir', None))
        if ok:
            print(f"✅ Removed {args.level} connection: {args.name}")
        else:
            print(f"❌ Connection '{args.name}' not found at {args.level} level.")
            sys.exit(1)
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"❌ File error: {e}")
        sys.exit(1)


def cmd_test_connection(args: argparse.Namespace) -> None:
    """Handle test connection command (delegates to db_manager)."""
    from scripts.db_manager import test_connection as manager_test

    print(f"🔍 Testing connection '{args.name}'...")
    success, message = manager_test(args.name, args.cwd)
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
        sys.exit(1)


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv)
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Route connection management commands
    if args.command == "add":
        cmd_add_connection(args)
    elif args.command in ("list-connections", "list-conn", "connections"):
        cmd_list_connections(args)
    elif args.command == "show-connection":
        cmd_show_connection(args)
    elif args.command == "remove-connection":
        cmd_remove_connection(args)
    elif args.command == "test-connection":
        cmd_test_connection(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
