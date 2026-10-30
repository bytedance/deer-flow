"""Operator tracing maintenance without a Gateway or model invocation."""

import argparse
import json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="deerflow tracing")
    commands = parser.add_subparsers(dest="command", required=True)
    cleanup = commands.add_parser(
        "cleanup",
        help="preview or remove unreachable tracing history",
        description="Run manually in an idle maintenance window: reference checks can scan the full history while holding admission locks. Profile versions are retained by reachability, not age.",
    )
    mode = cleanup.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    mode.add_argument("--apply", action="store_true", help="delete eligible records")
    cleanup.add_argument("--older-than-days", type=int, default=7, help="minimum snapshot age; does not apply to profile versions (default: 7)")
    cleanup.add_argument("--limit", type=int, default=100, help="maximum total records removed; does not bound scan time (default: 100)")
    cleanup.add_argument("--config", help="application configuration path")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000 or not 1 <= args.older_than_days <= 36500:
        parser.error("--limit must be 1..1000 and --older-than-days must be 1..36500")
    from deerflow.config.app_config import get_app_config, reload_app_config
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    try:
        config = reload_app_config(args.config) if args.config else get_app_config()
        result = cleanup_tracing_records(config, older_than_days=args.older_than_days, limit=args.limit, apply=args.apply)
    except Exception:
        print(json.dumps({"error": "tracing_cleanup_unavailable"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 2 if result["snapshot_skip_reason"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
