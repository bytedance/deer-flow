#!/usr/bin/env python3
"""threat-intel-collector CLI — acquisition layer.

Shells out to the underlying ``tg-crawler`` CLI to crawl Telegram groups,
search bots, Twitter, discover brand-new groups, and add group links. Each
acquisition automatically runs the keyword→LLM cleaning + SQLite/JSON/CSV
dual-write pipeline.

Usage:
  python collect.py --action crawl --days 3 --joined-only
  python collect.py --action crawl-bot --keywords "抖音 买号"
  python collect.py --action crawl-twitter --days 3
  python collect.py --action discover --keywords "某APP 账号"   # dry-run by default
  python collect.py --action add-group --link https://t.me/foo

Locate the underlying project via env TG_INTEL_CRAWLER_HOME, else a sibling
tg-intel-crawler/ near this script.
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
    here = Path(__file__).resolve()
    for parent in here.parents:
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
    ap = argparse.ArgumentParser(description="Threat-intel acquisition layer")
    ap.add_argument("--action", required=True,
                    choices=["crawl", "crawl-bot", "crawl-twitter", "discover", "add-group"])
    ap.add_argument("--mode", default="history", choices=["history", "realtime", "both"])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--joined-only", action="store_true")
    ap.add_argument("--include-joined", action="store_true")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--users", default="")
    ap.add_argument("--bot", default="")
    ap.add_argument("--max-queries", type=int, default=0)
    ap.add_argument("--no-fetch-detail", action="store_true")
    ap.add_argument("--link", default="")
    ap.add_argument("--join", action="store_true",
                    help="discover: actually join found groups (default is list-only).")
    a = ap.parse_args()

    if a.action == "crawl":
        args = ["crawl", "--mode", a.mode, "--days", str(a.days)]
        if a.joined_only:
            args.append("--joined-only")
        if a.include_joined:
            args.append("--include-joined")
        out = _run(args, "crawl")
    elif a.action == "crawl-bot":
        args = ["crawl-bot"]
        if a.keywords:
            args += ["--keywords", a.keywords]
        if a.bot:
            args += ["--bot", a.bot]
        if a.max_queries:
            args += ["--max-queries", str(a.max_queries)]
        args.append("--no-fetch-detail" if a.no_fetch_detail else "--fetch-detail")
        out = _run(args, "crawl-bot")
    elif a.action == "crawl-twitter":
        args = ["crawl-twitter", "--days", str(a.days)]
        if a.keywords:
            args += ["--keywords", a.keywords]
        if a.users:
            args += ["--users", a.users]
        out = _run(args, "crawl-twitter")
    elif a.action == "discover":
        if not a.keywords:
            out = {"ok": False, "action": "discover", "error": "--keywords required"}
        else:
            args = ["discover", "--keywords", a.keywords,
                    "--auto-join" if a.join else "--list-only"]
            out = _run(args, "discover")
    elif a.action == "add-group":
        if not a.link:
            out = {"ok": False, "action": "add-group", "error": "--link required"}
        else:
            out = _run(["groups", "add", a.link], "add-group")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
