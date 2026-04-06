"""Railway runtime bootstrap helpers for the gateway service.

This module prepares the DeerFlow gateway runtime before uvicorn starts:

- render a tracked Railway config template to a concrete config.yaml
- seed a mutable extensions_config.json into DEER_FLOW_HOME only once
- decode Codex CLI auth into a runtime-only file when provided

The helpers are importable so backend tests can validate the bootstrap rules
without shelling out to Railway.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PRIMARY_MODEL_ALIASES = {
    "codex": "codex",
    "gpt-5.4": "codex",
    "openai": "openai",
    "gpt-5": "openai",
    "gemini": "gemini",
    "gemini-2.5-pro": "gemini",
}

MODEL_NAMES = {
    "codex": "gpt-5.4",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
}


def repo_root() -> Path:
    """Return the DeerFlow repository root."""
    return Path(__file__).resolve().parents[3]


def templates_dir() -> Path:
    """Return the Railway templates directory."""
    return repo_root() / "railway" / "templates"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML object at {path}, got {type(data).__name__}")
    return data


def _resolve_primary_model(raw: str | None) -> str:
    normalized = (raw or "codex").strip().lower()
    primary = PRIMARY_MODEL_ALIASES.get(normalized)
    if primary is None:
        supported = ", ".join(sorted(PRIMARY_MODEL_ALIASES))
        raise ValueError(f"Unsupported DEER_FLOW_PRIMARY_MODEL={raw!r}. Supported values: {supported}")
    return primary


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _decode_codex_auth(env: dict[str, str]) -> str | None:
    if raw := env.get("CODEX_AUTH_JSON"):
        json.loads(raw)
        return raw

    encoded = env.get("CODEX_AUTH_JSON_B64")
    if not encoded:
        return None

    decoded = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
    json.loads(decoded)
    return decoded


def _filter_and_reorder_models(template_models: list[dict[str, Any]], env: dict[str, str], primary: str) -> list[dict[str, Any]]:
    codex_auth = _decode_codex_auth(env)
    available: list[dict[str, Any]] = []
    for model in template_models:
        name = model.get("name")
        if name == MODEL_NAMES["codex"]:
            if codex_auth:
                available.append(copy.deepcopy(model))
            continue
        if name == MODEL_NAMES["openai"]:
            if env.get("OPENAI_API_KEY"):
                available.append(copy.deepcopy(model))
            continue
        if name == MODEL_NAMES["gemini"]:
            if env.get("GEMINI_API_KEY"):
                available.append(copy.deepcopy(model))
            continue
        available.append(copy.deepcopy(model))

    wanted_name = MODEL_NAMES[primary]
    if not any(model.get("name") == wanted_name for model in available):
        if primary == "codex":
            raise ValueError("Primary model 'codex' selected but CODEX_AUTH_JSON_B64/CODEX_AUTH_JSON is missing.")
        if primary == "openai":
            raise ValueError("Primary model 'openai' selected but OPENAI_API_KEY is missing.")
        raise ValueError("Primary model 'gemini' selected but GEMINI_API_KEY is missing.")

    primary_model = next(model for model in available if model.get("name") == wanted_name)
    fallbacks = [model for model in available if model.get("name") != wanted_name]
    return [primary_model, *fallbacks]


def prepare_gateway_runtime(
    *,
    deer_flow_home: Path,
    config_output_path: Path,
    extensions_output_path: Path,
    codex_auth_output_path: Path,
    config_template_path: Path | None = None,
    extensions_template_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Prepare the runtime files used by the Railway gateway service."""
    resolved_env = dict(os.environ if env is None else env)
    primary = _resolve_primary_model(resolved_env.get("DEER_FLOW_PRIMARY_MODEL"))

    config_template = config_template_path or (templates_dir() / "config.railway.template.yaml")
    extensions_template = extensions_template_path or (templates_dir() / "extensions_config.railway.template.json")

    config_output_path.parent.mkdir(parents=True, exist_ok=True)
    extensions_output_path.parent.mkdir(parents=True, exist_ok=True)
    codex_auth_output_path.parent.mkdir(parents=True, exist_ok=True)
    deer_flow_home.mkdir(parents=True, exist_ok=True)

    config_data = _load_yaml(config_template)
    template_models = config_data.get("models", [])
    if not isinstance(template_models, list):
        raise ValueError(f"Expected 'models' list in {config_template}")

    config_data["models"] = _filter_and_reorder_models(template_models, resolved_env, primary)
    config_data.setdefault("sandbox", {})["allow_host_bash"] = _parse_bool(
        resolved_env.get("DEER_FLOW_ALLOW_HOST_BASH"),
        default=True,
    )

    config_output_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False),
        encoding="utf-8",
    )

    if not extensions_output_path.exists():
        extensions_output_path.write_text(extensions_template.read_text(encoding="utf-8"), encoding="utf-8")

    codex_auth = _decode_codex_auth(resolved_env)
    if codex_auth is not None:
        codex_auth_output_path.write_text(codex_auth, encoding="utf-8")
        codex_auth_output_path.chmod(0o600)
    elif codex_auth_output_path.exists():
        codex_auth_output_path.unlink()

    logger.info(
        "Prepared Railway runtime: config=%s extensions=%s primary_model=%s codex_auth=%s",
        config_output_path,
        extensions_output_path,
        MODEL_NAMES[primary],
        "present" if codex_auth is not None else "absent",
    )

    return {
        "primary_model": MODEL_NAMES[primary],
        "config_path": str(config_output_path),
        "extensions_path": str(extensions_output_path),
        "codex_auth_path": str(codex_auth_output_path),
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    deer_flow_home = Path(os.environ.get("DEER_FLOW_HOME") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "/data/deerflow")
    runtime_dir = Path(os.environ.get("DEER_FLOW_RUNTIME_DIR", "/tmp/deerflow-runtime"))
    config_path = Path(os.environ.get("DEER_FLOW_CONFIG_PATH", str(runtime_dir / "config.yaml")))
    extensions_path = Path(os.environ.get("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(deer_flow_home / "extensions_config.json")))
    codex_auth_path = Path(os.environ.get("CODEX_AUTH_PATH", str(runtime_dir / "codex-auth.json")))

    result = prepare_gateway_runtime(
        deer_flow_home=deer_flow_home,
        config_output_path=config_path,
        extensions_output_path=extensions_path,
        codex_auth_output_path=codex_auth_path,
    )
    logger.info("Railway gateway runtime ready with primary model %s", result["primary_model"])


if __name__ == "__main__":
    main()
