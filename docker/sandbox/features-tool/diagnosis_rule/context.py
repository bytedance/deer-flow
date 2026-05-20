from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from diagnosis.device_context_artifact import normalize_device_analysis_result
from diagnosis.models import DeviceContext
from ins import InsApiClient, load_dotenv_file, load_ins_settings

from .config import load_config

load_dotenv_file()
_ins_client = InsApiClient(load_ins_settings())


def _device_context_artifact_path() -> Path:
    output_dir = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "device_context.json"


def _load_existing_artifact(device_id: str) -> dict[str, Any] | None:
    artifact_path = _device_context_artifact_path()
    if not artifact_path.exists():
        return None
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(payload.get("device_id") or "") != str(device_id):
        return None
    if not isinstance(payload.get("child_device_list"), list):
        return None
    return payload


async def build_rule_device_context(device_id: str, sub_device_id: str | None = None) -> DeviceContext:
    config = load_config()
    analysis_dict = _load_existing_artifact(device_id)
    if analysis_dict is None:
        artifact_path = _device_context_artifact_path()
        raise FileNotFoundError(
            f"device_context.json not found for device_id={device_id}. "
            f"The rotating agent must generate {artifact_path} from the raw device tree before running rule diagnosis."
        )
    if sub_device_id:
        target_info = analysis_dict.get("target_info") or {}
        if str(target_info.get("target_kind") or "").strip().lower() == "unknown":
            raise ValueError(
                f"device_context.json exists for device_id={device_id}, but target_info.target_kind is unknown for sub_device_id={sub_device_id}. "
                "The rotating agent should regenerate device_context.json after validating the selected sub-device."
            )
    _, context = normalize_device_analysis_result(analysis_dict, config)
    return context


async def close_clients() -> None:
    await _ins_client.close()
    from tools.device_analysis import close_clients as close_device_analysis_clients
    await close_device_analysis_clients()
