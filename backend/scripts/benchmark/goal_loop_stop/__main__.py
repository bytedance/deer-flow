"""Run from backend: python -m scripts.benchmark.goal_loop_stop --output result.json."""

import argparse
import asyncio
import json
from pathlib import Path

from . import run_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce Goal continuation after a native loop hard stop, without provider calls.")
    parser.add_argument("--output", type=Path, help="Write the synthetic result JSON here; otherwise print it.")
    args = parser.parse_args()
    result = asyncio.run(run_case())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
