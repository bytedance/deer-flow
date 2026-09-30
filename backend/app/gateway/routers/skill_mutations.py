"""Host-admin inspection and reconciliation, with no force-overwrite endpoint."""

from dataclasses import asdict
from typing import Annotated

from deerflow_extension_api import HostCapabilityError
from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.gateway.deps import require_admin_user

router = APIRouter(prefix="/api/skill-mutations", tags=["skill-mutations"])
OperationId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
OwnerId = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


async def _invoke(request, method, *args, **kwargs):
    await require_admin_user(request, detail="Admin privileges required to inspect or recover skill publications.")
    host = getattr(request.app.state, "skill_mutation_host", None)
    if host is None or host.recovery is None:
        raise HTTPException(status_code=503, detail="UNAVAILABLE")
    try:
        return await host.workers.run(lambda _check: getattr(host.recovery, method)(*args, **kwargs))
    except HostCapabilityError as exc:
        status = {"NOT_FOUND_OR_FORBIDDEN": 404, "NOT_FOUND": 404, "NEEDS_REPAIR": 409, "REVISION_CONFLICT": 409}.get(exc.code, 503)
        raise HTTPException(status_code=status, detail=exc.code) from None
    except Exception:
        # SQL parameters may contain package bytes. No raw exception response.
        raise HTTPException(status_code=503, detail="UNAVAILABLE") from None


@router.get("/operations")
async def list_operations(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50, after_id: Annotated[str | None, Query(pattern=r"^[a-f0-9]{32}$")] = None):
    rows = await _invoke(request, "list_operations", limit=limit + 1, after_id=after_id)
    items = rows[:limit]
    return {"items": [asdict(row) for row in items], "has_more": len(rows) > limit, "next_cursor": items[-1].operation_id if items else after_id}


@router.get("/operations/{operation_id}")
async def get_operation(request: Request, operation_id: OperationId):
    return asdict(await _invoke(request, "get_operation", operation_id))


@router.post("/operations/{operation_id}/recover")
async def recover_operation(request: Request, operation_id: OperationId):
    return asdict(await _invoke(request, "recover_operation", operation_id))


@router.post("/owners/{owner_id}/recover")
async def recover_owner(request: Request, owner_id: OwnerId):
    await _invoke(request, "recover_owner", owner_id)
    return {"owner_id": owner_id, "reconciled": True}
