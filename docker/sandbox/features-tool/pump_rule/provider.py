from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class PumpDataProvider(ABC):
    @abstractmethod
    async def get_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_point_configs(self, machine_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_trend_data(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def get_waveforms(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class JsonFixturePumpDataProvider(PumpDataProvider):
    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        self.payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    async def get_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        _ = machine_id
        tree = self.payload.get("component_tree")
        if isinstance(tree, list):
            return tree
        legacy_tree = self.payload.get("device_tree") or {}
        legacy_roots = legacy_tree.get("child_device_list") or legacy_tree.get("components")
        return legacy_roots if isinstance(legacy_roots, list) else []

    async def get_point_configs(self, machine_id: str) -> dict[str, Any]:
        _ = machine_id
        return self.payload.get("point_configs") or {"vibPointConfig": [], "staPointConfig": []}

    async def get_trend_data(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        _ = (start, end)
        trends = self.payload.get("trends") or {}
        return {point_id: list(trends.get(point_id) or []) for point_id in point_ids}

    async def get_waveforms(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        _ = (start, end)
        waveforms = self.payload.get("waveforms") or {}
        return {point_id: list(waveforms.get(point_id) or []) for point_id in point_ids}


class InsPumpDataProvider(PumpDataProvider):
    def __init__(self) -> None:
        self._clients: list[Any] = []

    async def get_component_tree(self, machine_id: str) -> list[dict[str, Any]]:
        from ins.client import InsApiClient
        from ins.config import load_ins_settings

        client = InsApiClient(load_ins_settings())
        self._clients.append(client.close)
        return await client.get_components(machine_id)

    async def get_point_configs(self, machine_id: str) -> dict[str, Any]:
        from ins.client import InsApiClient
        from ins.config import load_ins_settings

        client = InsApiClient(load_ins_settings())
        self._clients.append(client.close)
        return await client.get_point_configs(machine_id, 4)

    async def get_trend_data(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        from tools.get_trend_data_2k_tool import close_clients, _get_trend_data_impl

        self._clients.append(close_clients)
        component_features = {point_id: ["v_rms", "a_peak", "rms", "peak", "value"] for point_id in point_ids}
        payload = await _get_trend_data_impl(component_features, start, end)
        grouped = payload.get("data") or {}
        return {point_id: list(grouped.get(point_id) or []) for point_id in point_ids}

    async def get_waveforms(self, point_ids: list[str], start: str, end: str) -> dict[str, list[dict[str, Any]]]:
        from tools.get_waveform_data_tool import close_clients, _get_waveform_data_impl

        self._clients.append(close_clients)
        # Reference implementation samples recent wave-capable values. The current
        # shared tool requires an exact time, so use the diagnosis end timestamp as
        # a deterministic first sample and let the runtime report partial failures.
        result: dict[str, list[dict[str, Any]]] = {}
        for point_id in point_ids:
            try:
                payload = await _get_waveform_data_impl(point_id, end)
            except Exception as exc:  # noqa: BLE001
                result[point_id] = [{"error": str(exc), "time": end}]
                continue
            data = payload.get("data") or {}
            result[point_id] = [
                {
                    "fs": data.get("sample_rate") or data.get("freq") or payload.get("sample_rate"),
                    "wave": data.get("wave_y") or [],
                    "v_rms": None,
                    "time": payload.get("time_ms") or end,
                    "raw": payload,
                }
            ]
        return result

    async def close(self) -> None:
        seen: set[Any] = set()
        for closer in self._clients:
            if closer in seen:
                continue
            seen.add(closer)
            await closer()
