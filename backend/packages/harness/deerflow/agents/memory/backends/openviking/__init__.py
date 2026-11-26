"""OpenViking memory backend using the official LangChain integration."""

from .credentials import OpenVikingCredential, OpenVikingCredentialProvider
from .openviking_manager import OpenVikingMemoryManager

MANAGER_CLASS = OpenVikingMemoryManager

__all__ = [
    "MANAGER_CLASS",
    "OpenVikingCredential",
    "OpenVikingCredentialProvider",
    "OpenVikingMemoryManager",
]
