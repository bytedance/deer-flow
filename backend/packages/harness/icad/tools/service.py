"""Service helpers for iCAD visualize tool orchestration."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from deerflow.config import get_app_config

JsonDict = dict[str, Any]


def _tool_settings() -> dict[str, Any]:
    try:
        config = get_app_config().get_tool_config("visualize_steel_structure")
    except Exception:
        return {}
    if config is None:
        return {}
    return dict(getattr(config, "model_extra", {}) or {})


def _worker_base_url() -> str:
    configured = _tool_settings().get("worker_base_url")
    if configured:
        return str(configured).rstrip("/")
    return os.getenv("ICAD_WORKER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _worker_timeout_seconds() -> float:
    configured = _tool_settings().get("timeout_seconds")
    if configured is not None:
        return float(configured)
    return 120.0


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-")
    return slug or "visualized-model"


def _artifact_basename(model_name: str | None, artifact_prefix: str | None) -> str:
    if artifact_prefix:
        return _slugify(artifact_prefix)
    if model_name:
        return _slugify(model_name)
    return "visualized-model"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _extract_error_message(payload: JsonDict) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        hint = error.get("hint")
        message = payload.get("message") or "Worker request failed"
        parts = [str(message)]
        if code:
            parts.append(f"code={code}")
        if hint:
            parts.append(f"hint={hint}")
        return "; ".join(parts)
    return str(payload.get("message") or "Worker request failed")


def visualize_origin_data(
    *,
    origin_data_json: str,
    model_name: str | None,
    output_dir: Path,
    artifact_prefix: str | None,
) -> JsonDict:
    output_dir.mkdir(parents=True, exist_ok=True)

    response = httpx.post(
        f"{_worker_base_url()}/api/visualize",
        json={
            "modelName": model_name,
            "originData": origin_data_json,
        },
        timeout=_worker_timeout_seconds(),
    )

    payload = response.json()
    if getattr(response, "is_error", False) or payload.get("success") is False:
        raise RuntimeError(_extract_error_message(payload))

    data = payload["data"]
    artifacts = data["artifacts"]
    basename = _artifact_basename(model_name, artifact_prefix)

    vsfx_path = output_dir / f"{basename}.vsfx"
    cda_json_path = output_dir / f"{basename}.cda.json"
    properties_json_path = output_dir / f"{basename}.properties.json"

    vsfx_path.write_bytes(base64.b64decode(artifacts["vsfx"]["base64"]))
    _write_json(cda_json_path, artifacts["cdaJson"]["content"])
    _write_json(properties_json_path, artifacts["propertiesJson"]["content"])

    return {
        "model_name": data.get("modelName") or model_name or basename,
        "apf_issues": data.get("apfIssues", []),
        "apf_issue_summary": data.get("apfIssueSummary", {}),
        "artifacts": {
            "vsfx_path": str(vsfx_path),
            "cda_json_path": str(cda_json_path),
            "properties_json_path": str(properties_json_path),
        },
    }
