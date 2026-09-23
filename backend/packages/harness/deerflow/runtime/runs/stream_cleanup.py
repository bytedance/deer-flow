from __future__ import annotations

import inspect
from typing import Any


async def close_agent_stream(stream: Any) -> None:
    """Close an agent stream when its runtime exposes asynchronous cleanup."""
    close = getattr(stream, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result
