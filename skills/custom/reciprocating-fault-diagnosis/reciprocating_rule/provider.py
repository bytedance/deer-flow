"""Data provider abstraction for reciprocating machine diagnosis.

Mirrors the pump_rule provider pattern:
  - InsReciprocatingDataProvider: real InS API calls
  - JsonFixtureReciprocatingDataProvider: local JSON fixture for dev/test
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ReciprocatingDataProvider(ABC):
    @abstractmethod
    async def fetch_config(self, machine_id: str, *, device_id: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_trend_data(
        self, gpids: list[str], timestamp_ms: int
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def fetch_sampler_id(self, machine_id: str) -> str:
        """Fetch samplerId from component tree. Override in subclasses."""
        return ""

    async def close(self) -> None:
        return None


class JsonFixtureReciprocatingDataProvider(ReciprocatingDataProvider):
    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        self.payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    async def fetch_config(self, machine_id: str, *, device_id: str = "") -> dict[str, Any]:
        _ = (machine_id, device_id)
        return self.payload.get("config") or self.payload.get("d901_config") or {}

    async def fetch_trend_data(
        self, gpids: list[str], timestamp_ms: int
    ) -> list[dict[str, Any]]:
        _ = (gpids, timestamp_ms)
        return self.payload.get("trend_data") or self.payload.get("data") or []

    async def fetch_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        _ = machine_id
        return self.payload.get("component_tree") or []


class InsReciprocatingDataProvider(ReciprocatingDataProvider):
    def __init__(self) -> None:
        self._client: Any = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            from .client import ReciprocatingInsClient
            self._client = ReciprocatingInsClient()
        return self._client

    async def fetch_config(self, machine_id: str, *, device_id: str = "") -> dict[str, Any]:
        client = await self._ensure_client()
        return await client.fetch_config(machine_id, device_id=device_id)

    async def fetch_sampler_id(self, machine_id: str) -> str:
        client = await self._ensure_client()
        return await client.fetch_sampler_id(machine_id)

    async def fetch_trend_data(
        self, gpids: list[str], timestamp_ms: int
    ) -> list[dict[str, Any]]:
        client = await self._ensure_client()
        return await client.fetch_trend_data(gpids, timestamp_ms)

    async def fetch_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        from ins.client import InsApiClient
        from ins.config import load_ins_settings

        client = InsApiClient(load_ins_settings())
        try:
            return await client.get_components(machine_id)
        finally:
            await client.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
