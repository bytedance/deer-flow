from __future__ import annotations

import argparse
import json
import sys

INVENTORY = {
    "widget-a": {"available": 5},
    "widget-b": {"available": 1},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    lookup = subcommands.add_parser("lookup_inventory")
    lookup.add_argument("--sku", required=True)

    reserve = subcommands.add_parser("reserve_inventory")
    reserve.add_argument("--sku", required=True)
    reserve.add_argument("--quantity", required=True, type=int)

    args = parser.parse_args(argv)
    stock = INVENTORY.get(args.sku)
    if stock is None:
        print(json.dumps({"ok": False, "error": "unknown sku"}))
        return 2

    if args.command == "lookup_inventory":
        print(json.dumps({"ok": True, "sku": args.sku, "available": stock["available"]}, sort_keys=True))
        return 0

    if args.quantity > stock["available"]:
        print(json.dumps({"ok": False, "error": "insufficient stock"}))
        return 3

    print(
        json.dumps(
            {
                "ok": True,
                "tool_name": "reserve_inventory",
                "sku": args.sku,
                "reserved_quantity": args.quantity,
                "reservation_id": f"resv-{args.sku}-{args.quantity}",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
