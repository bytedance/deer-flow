"""Authentication and authorization related enumerations."""

from enum import Enum


class UserRole(str, Enum):
    """User roles for multi-tenant authentication."""

    USER = "user"
    ADMIN = "admin"

    def __str__(self) -> str:
        return self.value


class TrackingAction(str, Enum):
    """Resource tracking actions for quota management."""

    CREATE = "create"
    DELETE = "delete"

    def __str__(self) -> str:
        return self.value


class ResourceType(str, Enum):
    """Resource types for quota management."""

    THREADS = "threads"
    SANDBOXES = "sandboxes"
    STORAGE_MB = "storage_mb"

    def __str__(self) -> str:
        return self.value


class QuotaKey(str, Enum):
    """Quota limit keys."""

    MAX_THREADS = "max_threads"
    MAX_SANDBOXES = "max_sandboxes"
    MAX_STORAGE_MB = "max_storage_mb"

    def __str__(self) -> str:
        return self.value


class StateStoreType(str, Enum):
    """State store implementation types."""

    FILE = "file"
    REDIS = "redis"

    def __str__(self) -> str:
        return self.value


class JWTAlgorithm(str, Enum):
    """JWT algorithm types."""

    HS256 = "HS256"
    RS256 = "RS256"

    def __str__(self) -> str:
        return self.value
