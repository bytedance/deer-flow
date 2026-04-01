"""LM Studio integration: discover OpenAI-compat models and load them via REST."""

from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

LM_STUDIO_MODEL_NAME_PREFIX = "lmstudio-"

_last_loaded_key: str | None = None


def encode_lm_studio_model_name(model_id: str) -> str:
    """Stable DeerFlow model `name` for an LM Studio model id (may contain '/')."""
    b64 = base64.urlsafe_b64encode(model_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{LM_STUDIO_MODEL_NAME_PREFIX}{b64}"


def decode_lm_studio_model_name(deerflow_name: str) -> str | None:
    """Return LM Studio model id if `deerflow_name` is an encoded LM Studio entry."""
    if not deerflow_name.startswith(LM_STUDIO_MODEL_NAME_PREFIX):
        return None
    b64 = deerflow_name[len(LM_STUDIO_MODEL_NAME_PREFIX) :]
    pad = "=" * ((4 - len(b64) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def openai_base_url_to_rest_base(openai_base_url: str) -> str:
    """LM Studio OpenAI base is .../v1; developer load API lives on .../api/v1/..."""
    u = openai_base_url.rstrip("/")
    if u.endswith("/v1"):
        return u[:-3]
    return u


def _auth_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def fetch_lm_studio_model_ids_async(openai_base_url: str, api_key: str | None) -> list[str]:
    """List model ids exposed by LM Studio's OpenAI-compatible server."""
    url = f"{openai_base_url.rstrip('/')}/models"
    headers = _auth_headers(api_key)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    out: list[str] = []
    for item in payload.get("data") or []:
        mid = item.get("id")
        if isinstance(mid, str) and mid:
            out.append(mid)
    return out


def ensure_lm_studio_model_loaded(
    *,
    rest_base_url: str,
    model_id: str,
    api_key: str | None,
) -> None:
    """Ask LM Studio to load `model_id` (idempotent if already loaded)."""
    global _last_loaded_key
    key = f"{rest_base_url.rstrip('/')}\0{model_id}"
    if _last_loaded_key == key:
        return
    url = f"{rest_base_url.rstrip('/')}/api/v1/models/load"
    headers = {**_auth_headers(api_key), "Content-Type": "application/json"}
    # Model weights can take many minutes to load on first select.
    with httpx.Client(timeout=600.0) as client:
        response = client.post(url, json={"model": model_id}, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("LM Studio load HTTP error for %s: %s", model_id, exc)
            raise
    _last_loaded_key = key
    logger.info("LM Studio model load requested: %s", model_id)


def clone_lm_studio_model_config(template: ModelConfig, deerflow_name: str, lm_model_id: str) -> ModelConfig:
    """Build a concrete ModelConfig row for one discovered LM Studio model."""
    from deerflow.config.model_config import ModelConfig as MC

    data = template.model_dump()
    data["name"] = deerflow_name
    data["model"] = lm_model_id
    data["display_name"] = f"LM Studio · {lm_model_id}"
    data.pop("lm_studio_discovery", None)
    return MC.model_validate(data)
