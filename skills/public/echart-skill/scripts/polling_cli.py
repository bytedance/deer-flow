"""
Polling CLI Module.

Provides command-line interface for polling management:
- list: List all polling jobs
- add: Add a new polling job
- remove: Remove a polling job
- refresh: Trigger manual refresh
- status: Show polling status

Usage:
    python scripts/polling_cli.py list
    python scripts/polling_cli.py refresh <job_id>
    python scripts/polling_cli.py status
"""

import argparse
import json
import sys
from typing import List, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from scripts.polling_manager import PollingManager, PollingConfig, load_polling_config

logger = get_logger(__name__)

_manager: Optional[PollingManager] = None


def get_manager() -> PollingManager:
    global _manager
    if _manager is None:
        _manager = PollingManager()
        _manager.start()
        
        configs = load_polling_config()
        for config in configs:
            _manager.add_job(config)
    
    return _manager


def cmd_list(args: argparse.Namespace) -> None:
    manager = get_manager()
    jobs = manager.list_jobs()
    
    if not jobs:
        print("No polling jobs configured.")
        return
    
    print(f"{'Job ID':<10} {'Source':<20} {'Type':<10} {'Interval':<10} {'Status':<10} {'Last Run'}")
    print("-" * 80)
    
    for job in jobs:
        last_run = job.get("last_run", "Never")
        if last_run and last_run != "Never":
            last_run = last_run[:19]
        
        print(
            f"{job['job_id']:<10} "
            f"{job['source_name']:<20} "
            f"{job['source_type']:<10} "
            f"{job['interval_seconds']}s      "
            f"{job['last_status']:<10} "
            f"{last_run}"
        )


def cmd_refresh(args: argparse.Namespace) -> None:
    manager = get_manager()
    
    if args.job_id:
        job = manager.get_job(args.job_id)
        if job is None:
            print(f"Error: Job '{args.job_id}' not found.")
            sys.exit(1)
        
        print(f"Refreshing job '{args.job_id}' ({job.config.source_name})...")
        success = manager.refresh_now(args.job_id)
        
        if success:
            job = manager.get_job(args.job_id)
            print(f"Refresh complete: {job.last_row_count} rows, status: {job.last_status}")
        else:
            print("Refresh failed.")
    else:
        print("Refreshing all jobs...")
        for job_id in [j["job_id"] for j in manager.list_jobs()]:
            print(f"  Refreshing {job_id}...")
            manager.refresh_now(job_id)
        print("All jobs refreshed.")


def cmd_status(args: argparse.Namespace) -> None:
    manager = get_manager()
    jobs = manager.list_jobs()
    
    print(f"Polling Manager Status: {'Running' if manager._running else 'Stopped'}")
    print(f"Total Jobs: {len(jobs)}")
    print()
    
    if args.job_id:
        job_data = next((j for j in jobs if j["job_id"] == args.job_id), None)
        if job_data is None:
            print(f"Error: Job '{args.job_id}' not found.")
            sys.exit(1)
        jobs = [job_data]
    
    for job in jobs:
        print(f"Job: {job['job_id']} - {job['source_name']}")
        print(f"  Type: {job['source_type']}")
        print(f"  Interval: {job['interval_seconds']} seconds")
        print(f"  Enabled: {job['enabled']}")
        print(f"  Last Run: {job['last_run'] or 'Never'}")
        print(f"  Last Status: {job['last_status']}")
        print(f"  Last Row Count: {job['last_row_count']}")
        print(f"  Error Count: {job['error_count']}")
        print()


def cmd_add(args: argparse.Namespace) -> None:
    config = PollingConfig(
        source_type=args.type,
        source_name=args.name,
        interval_seconds=args.interval,
        table_name=args.table,
        duckdb_path=args.duckdb or "workspace.duckdb",
        db_profile=args.db_profile,
        query=args.query,
        http_config=json.loads(args.http_config) if args.http_config else None
    )
    
    manager = get_manager()
    job_id = manager.add_job(config)
    
    print(f"Added polling job: {job_id}")
    print(f"  Source: {args.name}")
    print(f"  Type: {args.type}")
    print(f"  Interval: {args.interval}s")
    print(f"  Table: {args.table}")


def cmd_remove(args: argparse.Namespace) -> None:
    manager = get_manager()
    
    if manager.remove_job(args.job_id):
        print(f"Removed polling job: {args.job_id}")
    else:
        print(f"Error: Job '{args.job_id}' not found.")
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polling-cli",
        description="Polling management CLI"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    list_parser = subparsers.add_parser("list", help="List polling jobs")
    list_parser.set_defaults(func=cmd_list)
    
    refresh_parser = subparsers.add_parser("refresh", help="Trigger manual refresh")
    refresh_parser.add_argument("job_id", nargs="?", help="Job ID to refresh (all if not specified)")
    refresh_parser.set_defaults(func=cmd_refresh)
    
    status_parser = subparsers.add_parser("status", help="Show polling status")
    status_parser.add_argument("job_id", nargs="?", help="Job ID to show")
    status_parser.set_defaults(func=cmd_status)
    
    add_parser = subparsers.add_parser("add", help="Add polling job")
    add_parser.add_argument("--type", "-t", required=True, choices=["http", "database"], help="Source type")
    add_parser.add_argument("--name", "-n", required=True, help="Source name")
    add_parser.add_argument("--interval", "-i", type=int, default=300, help="Interval in seconds")
    add_parser.add_argument("--table", required=True, help="Target table name in DuckDB")
    add_parser.add_argument("--duckdb", help="DuckDB path")
    add_parser.add_argument("--db-profile", help="Database profile name (for database type)")
    add_parser.add_argument("--query", help="Query string")
    add_parser.add_argument("--http-config", help="HTTP config as JSON string")
    add_parser.set_defaults(func=cmd_add)
    
    remove_parser = subparsers.add_parser("remove", help="Remove polling job")
    remove_parser.add_argument("job_id", help="Job ID to remove")
    remove_parser.set_defaults(func=cmd_remove)
    
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    
    args.func(args)


if __name__ == "__main__":
    main()