"""Manual CLI: imports the live runtime only for the explicit run-live command."""

import argparse
import asyncio
import json
from pathlib import Path

from .cases import CASES
from .report import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    live = commands.add_parser("run-live", help="Call an explicitly configured external model; never run by pytest")
    live.add_argument("--output-dir", type=Path, required=True, help="New directory for local artifacts and metadata")
    live.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    live.add_argument("--case", choices=[case.name for case in CASES], action="append", dest="cases")
    live.add_argument("--repetitions", type=int, default=1)
    report = commands.add_parser("summarize", help="Recompute statistics offline from metadata-only rows")
    report.add_argument("rows", type=Path)
    args = parser.parse_args()
    if args.command == "summarize":
        rows = [json.loads(line) for line in args.rows.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(json.dumps(summarize(rows), indent=2))
        return
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    from .runner import run_live

    asyncio.run(run_live(args))


if __name__ == "__main__":
    main()
