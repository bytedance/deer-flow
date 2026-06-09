#!/usr/bin/env python3
"""Build handoff payload for fault-diagnosis agent from abnormal judgment data.

Usage:
    python build_handoff.py \
      --detail /mnt/user-data/outputs/abnormal_detail.json \
      --mac-id <id> --component-id <id> \
      --mac-name <name> --component-name <name> --mac-path <path> \
      --verdict real_fault --confidence 0.85 --fault-type unbalance_1x \
      --severity medium --health 84.0 --run-status normal \
      --evidence "证据1" --evidence "证据2" \
      --output /mnt/user-data/outputs/handoff_payload.json

Outputs a JSON file ready to be passed as handoff_data to render_ui(agent_handoff).
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main():
    p = argparse.ArgumentParser(description="Build handoff payload for fault-diagnosis")
    p.add_argument("--detail", required=True, help="Path to abnormal_detail.json")
    p.add_argument("--mac-id", required=True)
    p.add_argument("--component-id", required=True)
    p.add_argument("--mac-name", required=True)
    p.add_argument("--component-name", required=True)
    p.add_argument("--mac-path", required=True)
    p.add_argument("--verdict", required=True, help="real_fault | suspected | false_alarm")
    p.add_argument("--confidence", type=float, required=True)
    p.add_argument("--fault-type", default="", help="Suspected fault code, e.g. unbalance_1x")
    p.add_argument("--severity", default="medium", help="critical|high|medium|low")
    p.add_argument("--health", type=float, default=0.0)
    p.add_argument("--run-status", default="normal")
    p.add_argument("--evidence", action="append", default=[], help="Evidence strings (repeatable)")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    # Read detail and extract events + factory_id
    with open(args.detail, encoding="utf-8") as f:
        raw = json.load(f)
    detail = raw.get("data", raw) if isinstance(raw, dict) else raw
    events = detail.get("events", [])

    # Get factory_id from first event's jumpParams
    factory_id = ""
    for evt in events:
        jp = evt.get("jumpParams", {}) or {}
        fid = str(jp.get("factoryId", ""))
        if fid:
            factory_id = fid
            break

    handoff = {
        "source_agent": "abnormal-judgment--rotating",
        "abnormal_id": "",
        "equipment": {
            "mac_id": args.mac_id,
            "component_id": args.component_id,
            "factory_id": factory_id,
            "mac_name": args.mac_name,
            "mac_path": args.mac_path,
            "component_name": args.component_name,
            "mac_type": 1,
        },
        "events": events,
        "judgment": {
            "conclusion": f"{args.verdict} (confidence: {args.confidence})",
            "confidence": args.confidence,
            "suspected_fault_type": args.fault_type,
            "severity": args.severity,
            "evidence": args.evidence,
            "health_score": args.health,
            "run_status": args.run_status,
        },
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(handoff, f, ensure_ascii=False, indent=2)

    print(f"[build_handoff] written to {args.output} ({len(events)} events, factory_id={factory_id})", file=sys.stderr)
    print(json.dumps(handoff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
