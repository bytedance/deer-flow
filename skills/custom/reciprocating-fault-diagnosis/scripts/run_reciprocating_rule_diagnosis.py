#!/usr/bin/env python3
"""CLI entry point for the managed reciprocating diagnosis rule runtime.

Usage:
  python run_reciprocating_rule_diagnosis.py \
      --machine-id 241021041535608 \
      --diagnosis-time 1779676800096 \
      [--component-id 684234906171080704] \
      [--output /mnt/user-data/outputs/reciprocating_rule_result.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _features_tool_root() -> Path:
    root = Path(os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool"))
    if not root.exists():
        repo_root = Path(__file__).resolve().parents[4]
        local = repo_root / "docker" / "sandbox" / "features-tool"
        if local.exists():
            return local
        raise FileNotFoundError(f"features-tool directory not found: {root}")
    return root


def _output_dir() -> Path:
    path = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_output() -> Path:
    return _output_dir() / "reciprocating_rule_result.json"


def _runtime_info(features_tool_root: str | None = None) -> dict[str, object]:
    return {
        "entrypoint": "reciprocating_rule.run_diagnosis",
        "features_tool_root": features_tool_root or str(_features_tool_root()),
        "python_version": platform.python_version(),
    }


def _serialize_exception(exc: Exception) -> dict[str, object]:
    return {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}


def _validate_id(value: str, name: str) -> None:
    if not re.match(r"^[A-Za-z0-9_-]+$", value or ""):
        raise ValueError(f"{name} 无效: {value!r}")


def _parse_timestamp(value: str) -> int:
    """Parse a diagnosis time to milliseconds.

    Accepts:
      - Pure integer (ms epoch)
      - ISO datetime string (e.g., "2026-05-25T08:00:00")
    """
    if value.isdigit():
        return int(value)
    # Try ISO format
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        raise ValueError(f"无法解析诊断时间: {value!r}")


def _cache_dir() -> Path:
    return _output_dir() / "reciprocating_rule_cache"


def _list_cache_files() -> list[str]:
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return []
    return sorted(str(path) for path in cache_dir.glob("*.json"))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    _validate_id(args.machine_id, "machineId")
    timestamp_ms = _parse_timestamp(args.diagnosis_time)

    root = _features_tool_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from reciprocating_rule import close_all_clients, run_diagnosis, self_check

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await run_diagnosis(
            machine_id=args.machine_id,
            timestamp_ms=timestamp_ms,
            component_id=args.component_id,
        )
        return {
            "ok": True,
            "machine_id": args.machine_id,
            "component_id": args.component_id,
            "diagnosis_time": args.diagnosis_time,
            "timestamp_ms": timestamp_ms,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {**_runtime_info(root_str), "self_check": self_check()},
            "artifacts": {"cache_dir": str(_cache_dir()), "cache_files": _list_cache_files()},
            **result.to_dict(),
        }
    finally:
        await close_all_clients()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run managed reciprocating diagnosis rule runtime")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--component-id", default=None)
    parser.add_argument("--diagnosis-time", required=True)
    parser.add_argument("--fixture", default=None, help="Local JSON fixture for tests/dev")
    parser.add_argument("--output", default=None)
    parser.add_argument("--access-token", default=None)
    args = parser.parse_args()

    if args.access_token:
        os.environ["INS_ACCESS_TOKEN"] = args.access_token
    if args.fixture:
        os.environ["RECIPROCATING_RULE_FIXTURE"] = args.fixture

    output_path = Path(args.output) if args.output else _default_output()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = asyncio.run(_run(args))
    except Exception as exc:
        payload = {
            "ok": False,
            "machine_id": args.machine_id,
            "component_id": args.component_id,
            "diagnosis_time": args.diagnosis_time,
            "error": _serialize_exception(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime": _runtime_info(),
            "artifacts": {"cache_dir": str(_cache_dir()), "cache_files": _list_cache_files()},
            "warnings": [],
        }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "ok": payload.get("ok", False)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
