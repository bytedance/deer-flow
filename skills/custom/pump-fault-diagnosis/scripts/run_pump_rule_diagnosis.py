#!/usr/bin/env python3
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


def _skill_root() -> Path:
    """Return the skill root directory where pump_rule is located."""
    # scripts/ is at /mnt/skills/custom/pump-fault-diagnosis/scripts/
    return Path(__file__).resolve().parent.parent


def _features_tool_root() -> Path:
    root = Path(os.environ.get("FEATURES_TOOL_ROOT", "/mnt/skills/custom/features-tool"))
    if not root.exists():
        raise FileNotFoundError(f"features-tool directory not found: {root}")
    return root


def _output_dir() -> Path:
    path = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_output() -> Path:
    return _output_dir() / "pump_rule_result.json"


def _runtime_info(features_tool_root: str | None = None) -> dict[str, object]:
    return {
        "entrypoint": "pump_rule.run_diagnosis",
        "features_tool_root": features_tool_root or str(_features_tool_root()),
        "python_version": platform.python_version(),
    }


def _serialize_exception(exc: Exception) -> dict[str, object]:
    return {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}


def _validate_id(value: str, name: str) -> None:
    if not re.match(r"^[A-Za-z0-9_-]+$", value or ""):
        raise ValueError(f"{name} 无效")


def _cache_dir() -> Path:
    return _output_dir() / "pump_rule_cache"


def _list_cache_files() -> list[str]:
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return []
    return sorted(str(path) for path in cache_dir.glob("*.json"))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    _validate_id(args.machine_id, "machineId")
    _validate_id(args.component_id, "componentId")

    # Add skill root to sys.path for pump_rule import
    skill_root = _skill_root()
    skill_root_str = str(skill_root)
    if skill_root_str not in sys.path:
        sys.path.insert(0, skill_root_str)

    # Add features-tool root for ins/agents imports
    features_root = _features_tool_root()
    features_root_str = str(features_root)
    if features_root_str not in sys.path:
        sys.path.insert(0, features_root_str)

    from pump_rule import close_all_clients, run_diagnosis, self_check

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await run_diagnosis(
            machine_id=args.machine_id,
            component_id=args.component_id,
            diagnosis_time=args.diagnosis_time,
            component_name=args.component_name,
            base_freq=args.base_freq,
        )
        return {
            "ok": True,
            "machine_id": args.machine_id,
            "component_id": args.component_id,
            "diagnosis_time": args.diagnosis_time,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {**_runtime_info(features_root_str), "self_check": self_check()},
            "artifacts": {"cache_dir": str(_cache_dir()), "cache_files": _list_cache_files()},
            **result.model_dump(),
        }
    finally:
        await close_all_clients()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run managed pump diagnosis rule runtime")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--component-id", required=True)
    parser.add_argument("--component-name", default=None)
    parser.add_argument("--diagnosis-time", required=True)
    parser.add_argument("--start-time", default=None)
    parser.add_argument("--end-time", default=None)
    parser.add_argument("--base-freq", type=float, default=None)
    parser.add_argument("--fixture", default=None, help="Local JSON fixture for tests/dev")
    parser.add_argument("--output", default=None)
    parser.add_argument("--access-token", default=None)
    args = parser.parse_args()

    if args.access_token:
        os.environ["INS_ACCESS_TOKEN"] = args.access_token
    if args.fixture:
        os.environ["PUMP_RULE_FIXTURE"] = args.fixture

    output_path = Path(args.output) if args.output else _default_output()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001
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
