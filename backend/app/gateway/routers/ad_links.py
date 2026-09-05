"""Gateway proxy for Affiliates.One deep-link generation."""

import os
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api/ad-links", tags=["ad-links"])

AFFILIATES_ONE_DEEP_LINK_URL = "https://api.pub.affiliates.one/api/v2/affiliates/deep_links/generate.json"


class DeepLinkRequest(BaseModel):
    target_url: str = Field(..., min_length=1, max_length=4096)
    aff_uniq_id: str = Field(..., min_length=1, max_length=128)
    subid_1: str | None = Field(default=None, max_length=256)
    subid_2: str | None = Field(default=None, max_length=256)
    subid_3: str | None = Field(default=None, max_length=256)
    subid_4: str | None = Field(default=None, max_length=256)
    subid_5: str | None = Field(default=None, max_length=256)


class DeepLinkResponse(BaseModel):
    deeplink_url: str


def _validate_target_url(target_url: str) -> str:
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="target_url must be an absolute HTTP(S) URL")
    return target_url


def _request_data(body: DeepLinkRequest) -> dict[str, str]:
    data = body.model_dump(exclude_none=True)
    return data


def _extract_deep_link(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    value = first.get("deeplink_url")
    return value if isinstance(value, str) and value else None


@router.post("/deep-link", response_model=DeepLinkResponse)
@require_permission("runs", "create")
async def generate_deep_link(body: DeepLinkRequest, request: Request) -> DeepLinkResponse:
    api_key = os.environ.get("AFFILIATES_ONE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AFFILIATES_ONE_API_KEY is not configured")

    target_url = _validate_target_url(body.target_url)
    request_body = {
        "data": _request_data(body),
        "meta": {
            "locale": "zh-TW",
            "currency": "TWD",
            "time_zone": "0.0",
            "api_key": api_key,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(AFFILIATES_ONE_DEEP_LINK_URL, json=request_body)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Affiliates.One request failed") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Affiliates.One rejected the deep-link request")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Affiliates.One returned invalid JSON") from exc
    deeplink_url = _extract_deep_link(payload)
    if deeplink_url is None:
        raise HTTPException(status_code=502, detail="Affiliates.One returned no deep link")
    return DeepLinkResponse(deeplink_url=deeplink_url)
