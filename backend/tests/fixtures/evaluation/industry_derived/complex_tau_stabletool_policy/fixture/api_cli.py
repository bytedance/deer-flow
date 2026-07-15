from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DB_PATH = Path("db.json")
LOG_PATH = Path("action_log.json")
TOOL_VERSION = "local-tau-stabletool-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Local stateful retail tool API")
    sub = parser.add_subparsers(dest="command", required=True)

    get_order = sub.add_parser("get-order")
    get_order.add_argument("order_id")

    get_inventory = sub.add_parser("get-inventory")
    get_inventory.add_argument("sku")

    create_exchange = sub.add_parser("create-exchange")
    create_exchange.add_argument("order_id")
    create_exchange.add_argument("sku")

    add_note = sub.add_parser("add-note")
    add_note.add_argument("order_id")
    add_note.add_argument("note")

    issue_refund = sub.add_parser("issue-refund")
    issue_refund.add_argument("order_id")

    args = parser.parse_args()
    db = _read_json(DB_PATH)
    log = _read_json(LOG_PATH)

    if args.command == "get-order":
        order = db["orders"][args.order_id]
        customer = db["customers"][order["customer_id"]]
        payload = {"order": order, "customer": customer}
        _append(log, "get_order", {"order_id": args.order_id})
        _write_json(LOG_PATH, log)
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "get-inventory":
        inventory = db["inventory"][args.sku]
        _append(log, "get_inventory", {"sku": args.sku, "available": inventory["available"]})
        _write_json(LOG_PATH, log)
        print(json.dumps({"sku": args.sku, **inventory}, sort_keys=True))
        return 0

    if args.command == "create-exchange":
        order = db["orders"][args.order_id]
        inventory = db["inventory"][args.sku]
        if inventory["available"] <= 0:
            raise SystemExit("replacement inventory unavailable")
        inventory["available"] -= 1
        order["status"] = "exchange_pending"
        order["exchange_sku"] = args.sku
        _append(log, "create_exchange", {"order_id": args.order_id, "sku": args.sku})
        _write_json(DB_PATH, db)
        _write_json(LOG_PATH, log)
        print(json.dumps({"order_id": args.order_id, "status": order["status"], "exchange_sku": args.sku}, sort_keys=True))
        return 0

    if args.command == "add-note":
        order = db["orders"][args.order_id]
        order.setdefault("notes", []).append(args.note)
        _append(log, "add_note", {"order_id": args.order_id})
        _write_json(DB_PATH, db)
        _write_json(LOG_PATH, log)
        print(json.dumps({"order_id": args.order_id, "note_count": len(order["notes"])}, sort_keys=True))
        return 0

    if args.command == "issue-refund":
        order = db["orders"][args.order_id]
        order["status"] = "refunded"
        order["refund_id"] = f"rfnd-{args.order_id}"
        _append(log, "issue_refund", {"order_id": args.order_id, "refund_id": order["refund_id"]})
        _write_json(DB_PATH, db)
        _write_json(LOG_PATH, log)
        print(json.dumps({"order_id": args.order_id, "status": order["status"], "refund_id": order["refund_id"]}, sort_keys=True))
        return 0

    raise AssertionError(f"unknown command: {args.command}")


def _append(log: list[dict[str, Any]], action: str, payload: dict[str, Any]) -> None:
    log.append({"tool_version": TOOL_VERSION, "action": action, **payload})


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
