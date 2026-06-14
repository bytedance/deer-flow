"""Stream bridge — decouples agent workers from SSE endpoints.

A ``StreamBridge`` sits between the background task that runs an agent
(producer) and the HTTP endpoint that pushes Server-Sent Events to
the client (consumer).  This package provides an abstract protocol
(:class:`StreamBridge`) plus a default in-memory implementation backed
by :mod:`asyncio.Queue`.
"""

from .async_provider import make_stream_bridge
from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent
from .memory import MemoryStreamBridge

# NOTE: ``RedisStreamBridge`` is intentionally NOT imported here. ``redis`` is an
# optional extra, and this package is pulled in transitively by ``deerflow.runtime``
# at process startup everywhere. Importing ``.redis`` eagerly would import
# ``redis.asyncio`` in every process (even memory-only/single-process ones) and
# couple every install to the redis package. It is imported lazily inside
# ``make_stream_bridge`` only when ``stream_bridge.type == "redis"``. Import it
# directly from ``deerflow.runtime.stream_bridge.redis`` if you need the class.

__all__ = [
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "MemoryStreamBridge",
    "StreamBridge",
    "StreamEvent",
    "make_stream_bridge",
]
