"""Honcho memory backend package. See ``honcho_manager.py``."""


def __getattr__(name: str):
    if name == "MANAGER_CLASS":
        from .honcho_manager import HonchoMemoryManager
        return HonchoMemoryManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
