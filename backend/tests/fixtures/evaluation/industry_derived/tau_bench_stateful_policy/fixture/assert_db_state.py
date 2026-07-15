from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    db = json.loads(Path("db.json").read_text(encoding="utf-8"))
    action_log = json.loads(Path("action_log.json").read_text(encoding="utf-8"))

    order = db["orders"]["ord-1001"]
    if order["user_id"] != "user-007":
        print("order user mismatch", file=sys.stderr)
        return 1
    if order["status"] != "refunded":
        print("order was not refunded", file=sys.stderr)
        return 1
    if order["refund_id"] != "rfnd-ord-1001":
        print("refund id mismatch", file=sys.stderr)
        return 1

    actions = [entry.get("action") for entry in action_log]
    if actions != ["verify_user", "issue_refund"]:
        print(f"unexpected actions: {actions}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
