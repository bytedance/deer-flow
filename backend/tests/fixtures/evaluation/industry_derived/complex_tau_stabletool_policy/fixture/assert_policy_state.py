from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_REASON = "policy_requires_exchange_without_defect_evidence"
EXPECTED_TOOL_VERSION = "local-tau-stabletool-v1"
EXPECTED_ACTIONS = ["get_order", "get_inventory", "create_exchange", "add_note"]


def main() -> int:
    db = _read_json(Path("db.json"))
    action_log = _read_json(Path("action_log.json"))
    resolution = _read_json(Path("resolution.json"))

    order = db["orders"]["ret-9001"]
    failures: list[str] = []

    if order.get("status") != "exchange_pending":
        failures.append("order status must be exchange_pending")
    if order.get("exchange_sku") != "jacket-blue-m":
        failures.append("exchange_sku must be jacket-blue-m")
    if "refund_id" in order:
        failures.append("refund_id must not be present")
    if db["inventory"]["jacket-blue-m"]["available"] != 2:
        failures.append("replacement inventory must be decremented once")
    if not order.get("notes"):
        failures.append("order must contain an audit note")

    actions = [entry.get("action") for entry in action_log]
    if actions != EXPECTED_ACTIONS:
        failures.append(f"action order mismatch: {actions}")
    for entry in action_log:
        if entry.get("tool_version") != EXPECTED_TOOL_VERSION:
            failures.append("every action must be produced by the local tool API")
            break

    if resolution.get("decision") != "exchange_pending":
        failures.append("resolution decision must be exchange_pending")
    if resolution.get("refund_denied_reason") != EXPECTED_REASON:
        failures.append("resolution must explain the refund denial policy reason")
    if resolution.get("order_id") != "ret-9001":
        failures.append("resolution must identify order ret-9001")

    if failures:
        print(json.dumps({"failures": failures}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    return 0


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
