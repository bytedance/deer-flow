"""Shared utility helpers for the Gateway layer."""


def sanitize_log_param(value: str) -> str:
    """Strip control characters to prevent log injection."""
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")
