"""Point API router — proxies point queries to ins-bus-rpc."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from deerflow.rpc.point_service import PointServiceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/point", tags=["point"])

_client: PointServiceClient | None = None


def _get_client() -> PointServiceClient:
    global _client
    if _client is None:
        _client = PointServiceClient()
    return _client


@router.get("/list")
async def get_point_list(
    machine_ids: str = Query(..., alias="machineIds", description="设备ID，多个以逗号分隔"),
) -> list:
    """通过设备ID查询测点列表。

    Proxies to ins-bus-rpc /pointModel/getPointListByMachineIds.
    """
    try:
        ids = [int(i.strip()) for i in machine_ids.split(",") if i.strip()]
        if not ids:
            return []
        client = _get_client()
        return await client.get_point_list_by_machine_ids(ids)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid machineIds format")
    except Exception as e:
        logger.exception("Failed to fetch point list")
        raise HTTPException(status_code=502, detail=f"Point service unavailable: {e}")
