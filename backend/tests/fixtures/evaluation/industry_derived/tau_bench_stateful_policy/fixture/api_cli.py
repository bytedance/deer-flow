from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DB_PATH = Path("db.json")


def _load_db() -> dict:
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def _save_db(db: dict) -> None:
    DB_PATH.write_text(json.dumps(db, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    verify = subcommands.add_parser("verify_user")
    verify.add_argument("--user-id", required=True)
    verify.add_argument("--order-id", required=True)

    refund = subcommands.add_parser("issue_refund")
    refund.add_argument("--user-id", required=True)
    refund.add_argument("--order-id", required=True)

    args = parser.parse_args(argv)
    db = _load_db()
    order = db["orders"].get(args.order_id)
    user = db["users"].get(args.user_id)
    if order is None or user is None or order["user_id"] != args.user_id:
        print(json.dumps({"ok": False, "error": "identity mismatch"}))
        return 1

    if args.command == "verify_user":
        print(json.dumps({"ok": bool(user["verified"]), "action": "verify_user", "user_id": args.user_id}, sort_keys=True))
        return 0 if user["verified"] else 2

    if order["status"] != "delivered":
        print(json.dumps({"ok": False, "error": "order is not refundable"}))
        return 3

    order["status"] = "refunded"
    order["refund_id"] = f"rfnd-{args.order_id}"
    _save_db(db)
    print(json.dumps({"ok": True, "action": "issue_refund", "refund_id": order["refund_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
