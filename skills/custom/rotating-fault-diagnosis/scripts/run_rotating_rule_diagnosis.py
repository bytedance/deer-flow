#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _features_tool_root() -> Path:
    root = Path(os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool"))
    if not root.exists():
        raise FileNotFoundError(f"features-tool directory not found: {root}")
    return root


def _default_output() -> Path:
    output_dir = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "rotating_rule_result.json"


def _serialize_exception(exc: Exception) -> dict[str, object]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def _cache_dir() -> Path:
    return Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs")) / "rotating_rule_cache"


def _list_cache_files(cache_dir: Path) -> list[str]:
    if not cache_dir.exists():
        return []
    return sorted(str(path) for path in cache_dir.glob("*.json"))


def _runtime_info(features_tool_root: str | None = None) -> dict[str, object]:
    return {
        "features_tool_root": features_tool_root or os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool"),
        "python_version": platform.python_version(),
    }


async def _run(device_id: str, sub_device_id: str, diagnosis_time: str) -> dict[str, object]:
    root = _features_tool_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from diagnosis_rule import close_all_clients, run_diagnosis

    started_at = datetime.now(timezone.utc).isoformat()
    cache_dir = _cache_dir()
    warnings: list[str] = []
    try:
        result = await run_diagnosis(device_id=device_id, sub_device_id=sub_device_id, time=diagnosis_time)
        cache_files = _list_cache_files(cache_dir)
        if not cache_files:
            warnings.append("rotating_rule_cache 未生成任何缓存文件，报告阶段可能无法渲染完整图表")
        return {
            "ok": True,
            "device_id": device_id,
            "sub_device_id": sub_device_id,
            "diagnosis_time": diagnosis_time,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {
                "entrypoint": "diagnosis_rule.run_diagnosis",
                **_runtime_info(root_str),
            },
            "artifacts": {
                "cache_dir": str(cache_dir),
                "cache_files": cache_files,
            },
            "warnings": warnings,
            "result": result.model_dump(),
        }
    finally:
        await close_all_clients()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rotating diagnosis rule runtime")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--sub-device-id", required=True)
    parser.add_argument("--diagnosis-time", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--access-token", default=None)
    args = parser.parse_args()

    if args.access_token:
        os.environ["INS_ACCESS_TOKEN"] = args.access_token

    output_path = Path(args.output) if args.output else _default_output()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = asyncio.run(_run(args.device_id, args.sub_device_id, args.diagnosis_time))
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "device_id": args.device_id,
            "sub_device_id": args.sub_device_id,
            "diagnosis_time": args.diagnosis_time,
            "error": _serialize_exception(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime": _runtime_info(),
            "artifacts": {
                "cache_dir": str(_cache_dir()),
                "cache_files": _list_cache_files(_cache_dir()),
            },
            "warnings": [],
        }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "ok": payload.get("ok", False)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
