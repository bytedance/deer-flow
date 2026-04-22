"""Stream bridge exceptions."""

from __future__ import annotations


class StreamBridgeError(Exception):
    """Base exception for stream bridge errors."""


class BridgeClosedError(StreamBridgeError):
    """Raised when operating on a closed bridge."""


class StreamCapacityExceededError(StreamBridgeError):
    """Raised when max_active_streams is reached and eviction is not possible."""


class StreamTerminatedError(StreamBridgeError):
    """Raised when publishing to a terminal stream."""


class StreamNotFoundError(StreamBridgeError):
    """Raised when referencing a non-existent stream."""
