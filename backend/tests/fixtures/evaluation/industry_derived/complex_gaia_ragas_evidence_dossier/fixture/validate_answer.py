from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = [
    "SRE Aurora",
    "2026-07-18 15:00 UTC",
    "P1 data freshness degradation",
    "freeze the `atlas_writer` feature flag",
    "KB-IR-2026-0711",
    "KB-RUNBOOK-ATLAS-FAILOVER",
    "Answer",
    "Evidence",
    "Sources",
]

FORBIDDEN = [
    "2025-12-01",
    "Data Platform Delta",
    "Analytics Echo",
    "KB-ARCHIVE-2025-ATLAS",
    "KB-RUMOR-UNVERIFIED",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_answer.py answer.md", file=sys.stderr)
        return 2

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    forbidden = [needle for needle in FORBIDDEN if needle in text]
    if missing or forbidden:
        print({"missing": missing, "forbidden": forbidden}, file=sys.stderr)
        return 1

    evidence_lines = [line for line in text.splitlines() if "KB-" in line]
    if len(evidence_lines) < 2:
        print("expected at least two source-bearing evidence lines", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
