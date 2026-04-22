from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from deerflow.runtime import StreamBridge


def get_stream_bridge(request: Request) -> StreamBridge:
    """Get stream bridge from app.state."""
    bridge = getattr(request.app.state, "stream_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Stream bridge not available")
    return bridge


CurrentStreamBridge = Annotated[StreamBridge, Depends(get_stream_bridge)]
