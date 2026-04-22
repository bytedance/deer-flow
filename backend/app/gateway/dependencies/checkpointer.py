from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from langgraph.types import Checkpointer


def get_checkpointer(request: Request) -> Checkpointer:
    """Get checkpointer from app.state.persistence."""
    persistence = getattr(request.app.state, "persistence", None)
    if persistence is None:
        raise HTTPException(status_code=503, detail="Persistence not available")
    checkpointer = getattr(persistence, "checkpointer", None)
    if checkpointer is None:
        raise HTTPException(status_code=503, detail="Checkpointer not available")
    return checkpointer


CurrentCheckpointer = Annotated[Checkpointer, Depends(get_checkpointer)]
