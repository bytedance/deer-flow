"""Stream bridge public surface.

The harness package owns the stream abstraction and event semantics.
Concrete backends are intentionally not part of the public API here so
applications can inject infra-specific implementations.
"""

from .contract import (
    CANCELLED_SENTINEL,
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    JSONScalar,
    JSONValue,
    TERMINAL_STATES,
    ResumeResult,
    StreamBridge,
    StreamEvent,
    StreamStatus,
)
from .exceptions import (
    BridgeClosedError,
    StreamBridgeError,
    StreamCapacityExceededError,
    StreamNotFoundError,
    StreamTerminatedError,
)

__all__ = [
    # Sentinels
    "CANCELLED_SENTINEL",
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    # Types
    "JSONScalar",
    "JSONValue",
    "ResumeResult",
    "StreamBridge",
    "StreamEvent",
    "StreamStatus",
    "TERMINAL_STATES",
    # Exceptions
    "BridgeClosedError",
    "StreamBridgeError",
    "StreamCapacityExceededError",
    "StreamNotFoundError",
    "StreamTerminatedError",
]
