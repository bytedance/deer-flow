"""InS API client wrappers for reciprocating machine diagnosis.

Wraps three APIs:
  - GET /ins-os-manage/organize/getComponentByMachineIds  (component tree → samplerId)
  - GET /ins-os-manage/configInfo/queryD901Config          (static config, needs deviceId=samplerId)
  - GET /ins-os-view/sg9kData/getTrendDataHis              (trend data, 9k series)
"""

from __future__ import annotations

from typing import Any

from ins.client import InsApiClient
from ins.config import InsSettings, load_dotenv_file, load_ins_settings

from .config import ALL_TYPE_LIST, DATA_DENSITY, DATA_INCLUDE_FILTER, DATA_WINDOW_MS


load_dotenv_file()


class ReciprocatingInsClient:
    """Thin wrapper around InsApiClient for the two sg9k APIs."""

    def __init__(self, settings: InsSettings | None = None) -> None:
        self._settings = settings or load_ins_settings()
        self._client = InsApiClient(self._settings)

    async def close(self) -> None:
        await self._client.close()

    async def fetch_sampler_id(self, machine_id: str) -> str:
        """Fetch samplerId from the component tree.

        Calls getComponentByMachineIds and extracts
        data[0].configInfo.samplerId from the root machine node.
        Returns empty string if not found.
        """
        components = await self._client.get_components(machine_id)
        for root in components:
            if str(root.get("id") or "") == str(machine_id):
                config_info = root.get("configInfo") or {}
                sampler_id = str(config_info.get("samplerId") or "")
                if sampler_id:
                    return sampler_id
        # Fallback: take first root node's samplerId
        if components:
            config_info = components[0].get("configInfo") or {}
            return str(config_info.get("samplerId") or "")
        return ""

    async def fetch_config(self, machine_id: str, *, device_id: str = "") -> dict[str, Any]:
        """Fetch full D901 config for a machine.

        Parameters
        ----------
        machine_id : str
            Machine / equipment ID.
        device_id : str, optional
            samplerId from getComponentByMachineIds. Passed as ``deviceId``
            to queryD901Config. Without it, the API returns an incomplete
            response (empty devicePoints, missing deviceInfo).

        Returns the raw ``data`` object from the API response.
        """
        params: dict[str, str] = {"machineId": machine_id}
        if device_id:
            params["deviceId"] = device_id
        body = await self._client._get_json(
            "ins-os-manage/configInfo/queryD901Config",
            params,
        )
        return body.get("data") or {}

    async def fetch_trend_data(
        self,
        gpids: list[str],
        timestamp_ms: int,
        *,
        type_list: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch trend data for the given measurement points.

        Uses a lookback window (default 24h) ending at the diagnosis timestamp,
        high density, and the full 160-feature typeList.
        Returns the raw ``data`` array from the API response.
        """
        if not gpids:
            return []

        features = type_list or ALL_TYPE_LIST
        start_ms = str(timestamp_ms - DATA_WINDOW_MS)
        end_ms = str(timestamp_ms)

        body = await self._client._get_json(
            "ins-os-view/sg9kData/getTrendDataHis",
            {
                "gpids": ",".join(gpids),
                "startTime": start_ms,
                "endTime": end_ms,
                "density": DATA_DENSITY,
                "includeFilter": DATA_INCLUDE_FILTER,
                "typeList": ",".join(features),
            },
        )
        return body.get("data") or []


async def create_client() -> ReciprocatingInsClient:
    """Factory: create and return a configured client."""
    return ReciprocatingInsClient()
