"""Only run-live may contact the disposable Gateway and incur provider cost."""

import argparse
import asyncio
import json
from pathlib import Path

from .protocol import load_pilot_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Offline validation and non-secret configuration provenance")
    live = sub.add_parser("run-live", help="Explicit paid pilot against a disposable real Gateway")
    recheck = sub.add_parser("recheck-budget", help="Read-only recheck of an existing budget run; no model or Gateway launch")
    for command in (plan, live, recheck):
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--model", required=True)
    live.add_argument("--base-url", required=True)
    live.add_argument("--phase", choices=("lifecycle", "paired", "budget"), required=True)
    live.add_argument("--output", required=True, type=Path)
    live.add_argument("--max-cost", type=float, default=1.0)
    live.add_argument("--reserve-per-run", type=float, default=0.08)
    live.add_argument("--timeout", type=float, default=120)
    live.add_argument("--interval", type=int, default=20)
    recheck.add_argument("--run-output", required=True, type=Path)
    recheck.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        print(json.dumps(load_pilot_config(args.config, args.model), indent=2))
    elif args.command == "recheck-budget":
        from .budget_evidence import recheck_budget

        print(json.dumps(asyncio.run(recheck_budget(args)), indent=2))
    else:
        from .runner import run_live

        print("Pilot spend guard uses estimated token cost and reserves; it is not a hard provider billing limit.")
        asyncio.run(run_live(args))


if __name__ == "__main__":
    main()
