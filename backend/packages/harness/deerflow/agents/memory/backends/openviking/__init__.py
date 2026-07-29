"""OpenViking HTTP memory backend."""

from .openviking_manager import OpenVikingMemoryManager

MANAGER_CLASS = OpenVikingMemoryManager

__all__ = ["OpenVikingMemoryManager"]
