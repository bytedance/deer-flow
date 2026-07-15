from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED = {
    "ok": True,
    "tool_name": "reserve_inventory",
    "sku": "widget-a",
    "reserved_quantity": 2,
    "reservation_id": "resv-widget-a-2",
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: validate.py result.json", file=sys.stderr)
        return 2

    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    missing = {key: value for key, value in EXPECTED.items() if payload.get(key) != value}
    if missing:
        print(f"unexpected result fields: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
