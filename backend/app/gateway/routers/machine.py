"""Machine API router — proxies machine queries to ins-bus-rpc."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from deerflow.rpc.machine_service import MachineServiceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/machine", tags=["machine"])

_client: MachineServiceClient | None = None


def _get_client() -> MachineServiceClient:
    global _client
    if _client is None:
        _client = MachineServiceClient()
    return _client


@router.get("/component-info")
async def get_component_info(
    machine_id: int = Query(..., alias="machineId", description="设备id"),
    hidden_if_valid: bool | None = Query(None, alias="hiddenIfValid", description="隐藏设置是否有效"),
) -> list:
    """通过设备id获取部件信息。

    Proxies to ins-bus-rpc /getComponentInfoByMachineId.
    """
    try:
        client = _get_client()
        return await client.get_component_info_by_machine_id(
            machine_id=machine_id,
            hidden_if_valid=bool(hidden_if_valid),
        )
    except Exception as e:
        logger.exception("Failed to fetch component info")
        raise HTTPException(status_code=502, detail=f"Machine service unavailable: {e}")
