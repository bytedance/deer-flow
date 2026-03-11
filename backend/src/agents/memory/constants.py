"""Constants and helpers for memory subsystem behavior."""

MEMORY_BACKEND_FILE = "file"
MEMORY_BACKEND_POSTGRES = "postgres"


def normalize_memory_backend(value: str | None) -> str:
    """Normalize backend values from config for safe comparisons."""
    if value is None:
        return MEMORY_BACKEND_FILE
    return value.strip().lower()


def is_postgres_backend(value: str | None) -> bool:
    """Return true if the configured memory backend is Postgres."""
    return normalize_memory_backend(value) == MEMORY_BACKEND_POSTGRES
