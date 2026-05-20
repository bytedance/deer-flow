from __future__ import annotations

import json
import os
from typing import Any
from pathlib import Path

from diagnosis.device_context_artifact import build_device_context_artifact, normalize_device_analysis_result
from diagnosis.models import DeviceContext
from ins import InsApiClient, load_dotenv_file, load_ins_settings
from tools.device_analysis import analyze_device

from .config import load_config

load_dotenv_file()
_ins_client = InsApiClient(load_ins_settings())
async def build_rule_device_context(device_id: str, sub_device_id: str | None = None) -> DeviceContext:
    config = load_config()
    analysis_dict = await analyze_device(device_id)
    output_dir = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "device_context.json"
    artifact = build_device_context_artifact(analysis_dict, config, sub_device_id=sub_device_id)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    _, context = normalize_device_analysis_result(analysis_dict, config)
    return context


async def close_clients() -> None:
    await _ins_client.close()
    from tools.device_analysis import close_clients as close_device_analysis_clients
    await close_device_analysis_clients()
