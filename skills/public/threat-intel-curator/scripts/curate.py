#!/usr/bin/env python3
"""threat-intel-curator CLI — candidate-pool governance layer.

Shells out to ``tg-crawler`` to inspect the candidate pool, verify candidates'
real entity type (drop personal accounts / bots), and let the LLM pick + crawl
promising groups.

Usage:
  python curate.py --action stats
  python curate.py --action verify --max 80 --interval 3
  python curate.py --action llm-crawl --days 3 --min-confidence high --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _home() -> Path | None:
    env = os.environ.get("TG_INTEL_CRAWLER_HOME")
    if env and Path(env).exists():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "tg-intel-crawler"
        if cand.exists():
            return cand
    return None


def _cli() -> list[str]:
    return ["tg-crawler"] if shutil.which("tg-crawler") else ["python", "-m", "tg_intel_crawler.main"]


def _run(args: list[str], action: str) -> dict:
    home = _home()
    cmd = _cli() + args
    try:
        proc = subprocess.run(cmd, cwd=str(home) if home else None,
                              capture_output=True, text=True, timeout=3600)
    except FileNotFoundError:
        return {"ok": False, "action": action,
                "error": "tg-crawler not found; pip install -e tg-intel-crawler or set TG_INTEL_CRAWLER_HOME"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "action": action, "error": "timed out"}
    return {"ok": proc.returncode == 0, "action": action, "command": " ".join(cmd),
            "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> int:
    ap = argparse.ArgumentParser(description="Candidate-pool governance")
    ap.add_argument("--action", required=True, choices=["stats", "verify", "llm-crawl"])
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--max-candidates", type=int, default=50)
    ap.add_argument("--max-crawl", type=int, default=10)
    ap.add_argument("--min-confidence", default="medium", choices=["high", "medium", "low"])
    ap.add_argument("--stage2-concurrency", type=int, default=5)
    ap.add_argument("--no-join", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.action == "stats":
        out = _run(["candidates", "stats"], "stats")
    elif a.action == "verify":
        args = ["candidates", "verify", "--max", str(a.max), "--interval", str(a.interval)]
        if a.dry_run:
            args.append("--dry-run")
        out = _run(args, "verify")
    else:  # llm-crawl
        args = ["candidates", "llm-crawl", "--days", str(a.days),
                "--max-candidates", str(a.max_candidates), "--max-crawl", str(a.max_crawl),
                "--min-confidence", a.min_confidence,
                "--stage2-concurrency", str(a.stage2_concurrency)]
        if a.no_join:
            args.append("--no-join")
        if a.dry_run:
            args.append("--dry-run")
        out = _run(args, "llm-crawl")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
