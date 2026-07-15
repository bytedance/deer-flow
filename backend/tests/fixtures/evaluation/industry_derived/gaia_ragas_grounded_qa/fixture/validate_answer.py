from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = [
    "Short answer:",
    "2026-08-17 09:00 UTC",
    "Source: KB-2026-NEBULA",
]

FORBIDDEN = [
    "2024-09-30",
    "KB-2024-ARCHIVE",
]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: validate_answer.py answer.md", file=sys.stderr)
        return 2

    text = Path(args[0]).read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    forbidden = [needle for needle in FORBIDDEN if needle in text]
    if missing or forbidden:
        print(f"missing={missing} forbidden={forbidden}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
