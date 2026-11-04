"""Bounded, read-only provider catalog retrieval. Never follow credentialed redirects."""

import asyncio
import json

import httpx

from deerflow.config.managed_model_providers import get_managed_model_provider
from deerflow.config.managed_models import ManagedModel

MAX_MODELS = 2000
MAX_BYTES = 2 * 1024 * 1024


class DiscoveryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def fetch_model_catalog(profile: ManagedModel) -> tuple[list[str], bool]:
    provider = get_managed_model_provider(profile.provider)
    endpoint = provider.endpoint or profile.base_url
    key = profile.api_key.get_secret_value() if profile.api_key else None
    native = provider.protocol == "anthropic-messages"
    url = endpoint.rstrip("/") + ("/v1/models" if native else "/models")
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if native:
        headers.update({"x-api-key": key or "", "anthropic-version": "2023-06-01"})
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    # HTTPX constructs TLS trust synchronously; keep that work off the event loop.
    client = await asyncio.to_thread(httpx.AsyncClient, timeout=15, follow_redirects=False)
    names: set[str] = set()
    cursor = None
    size = 0
    try:
        async with asyncio.timeout(20), client:
            for _ in range(20):
                params = {"limit": 100, **({"after_id": cursor} if cursor else {})} if native else None
                async with client.stream("GET", url, headers=headers, params=params) as response:
                    if response.status_code in (401, 403):
                        raise DiscoveryError("authentication_failed")
                    if response.status_code in (404, 405):
                        raise DiscoveryError("discovery_unsupported")
                    if response.status_code != 200:
                        raise DiscoveryError("discovery_failed")
                    # Reject compression before HTTPX can allocate a decoded
                    # chunk larger than our response budget.
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise DiscoveryError("discovery_failed")
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise DiscoveryError("response_limit")
                        chunks.append(chunk)
                    data = json.loads(b"".join(chunks))
                if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                    raise DiscoveryError("discovery_failed")
                for item in data["data"]:
                    name = item.get("id") if isinstance(item, dict) else None
                    if not isinstance(name, str) or not name or len(name) > 200 or name != name.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
                        continue
                    names.add(name)
                    if len(names) >= MAX_MODELS:
                        return sorted(names), True
                if not native or not data.get("has_more"):
                    return sorted(names), bool(data.get("has_more"))
                next_cursor = data.get("last_id")
                if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor or len(next_cursor) > 200:
                    raise DiscoveryError("discovery_failed")
                cursor = next_cursor
            return sorted(names), True
    except DiscoveryError:
        raise
    except Exception:
        raise DiscoveryError("discovery_failed") from None
