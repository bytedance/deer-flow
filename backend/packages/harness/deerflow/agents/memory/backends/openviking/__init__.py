"""OpenViking memory backend using the official LangChain integration."""

from .openviking_manager import OpenVikingMemoryManager

MANAGER_CLASS = OpenVikingMemoryManager

__all__ = ["OpenVikingMemoryManager"]
