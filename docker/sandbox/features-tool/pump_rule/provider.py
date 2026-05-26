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
        from ins.client import InsApiClient, datetime_input_to_ms
        from ins.config import load_ins_settings

        client = InsApiClient(load_ins_settings())
        self._clients.append(client.close)

        start_ms = datetime_input_to_ms(start)
        end_ms = datetime_input_to_ms(end)

        # Step 1: get trend records with wave-capable timestamps (same as verification get_value_with_wave)
        data_list = await client.get_value_with_wave(point_ids, start_ms, end_ms)

        waves: dict[str, list[dict[str, Any]]] = {}
        for data in data_list:
            point_id = str(data.get("gpid") or "")
            values = data.get("values") or []
            if not point_id or not values:
                continue

            # Step 2: pick up to 5 most recent records (same as verification MalFunctionCheck.get_wave_list)
            wave_length = min(5, len(values))
            sorted_data = sorted(values, key=lambda x: str(x.get("datatime") or ""), reverse=True)[:wave_length]

            point_waves: list[dict[str, Any]] = []
            for value in sorted_data:
                datatime = str(value.get("datatime") or "")
                if not datatime:
                    continue
                try:
                    wave_items = await client.get_wave_mp(point_id, datatime)
                except Exception as exc:  # noqa: BLE001
                    point_waves.append({"error": str(exc), "time": datatime})
                    continue
                if not wave_items:
                    point_waves.append({"error": "波形解析为空", "time": datatime})
                    continue
                decoded = wave_items[0]
                fs = float(decoded.get("freq") or 0.0)
                # Extract wave: use extract_time_domain_wave (handles SHIFT/SPECTRUM/COMPLEX)
                # then fallback to raw waveDataSpeed/waveDataAcc (2k pump data)
                try:
                    from ins.spectrum_to_wave import extract_time_domain_wave
                    wave_arr = extract_time_domain_wave(decoded)
                    wave = [float(v) for v in wave_arr] if wave_arr is not None else []
                except Exception:
                    wave = []
                if not wave:
                    wave_raw = decoded.get("waveDataSpeed") or decoded.get("waveDataAcc") or {}
                    raw = wave_raw.get("wave") if isinstance(wave_raw, dict) else []
                    wave = [float(v) for v in raw] if raw else []
                point_waves.append(
                    {
                        "fs": fs,
                        "wave": wave,
                        "v_rms": value.get("v_rms"),
                        "time": datatime,
                    }
                )
            if point_waves:
                waves[point_id] = point_waves

        # Fill missing points with error entries
        for point_id in point_ids:
            if point_id not in waves:
                waves[point_id] = [{"error": "该时间窗口内无波形数据", "time": end}]

        return waves

    async def close(self) -> None:
        seen: set[Any] = set()
        for closer in self._clients:
            if closer in seen:
                continue
            seen.add(closer)
            await closer()
