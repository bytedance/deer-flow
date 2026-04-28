"""Global variables module."""

from .storage import (
    SYSTEM_VARIABLES,
    GlobalVariablesStorage,
    get_storage,
    get_system_variables,
)

__all__ = [
    "SYSTEM_VARIABLES",
    "GlobalVariablesStorage",
    "get_storage",
    "get_system_variables",
]
