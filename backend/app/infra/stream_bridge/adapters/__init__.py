"""Concrete stream bridge adapters owned by the app layer."""

from .memory import MemoryStreamBridge
from .redis import RedisStreamBridge

__all__ = ["MemoryStreamBridge", "RedisStreamBridge"]
