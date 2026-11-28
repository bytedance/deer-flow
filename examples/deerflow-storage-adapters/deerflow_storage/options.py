"""Validated connection budgets; no environment or application configuration."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EngineOptions:
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: float = 30
    pool_recycle: int = 1800
    connect_timeout: int = 10
    read_timeout: float = 30
    write_timeout: float = 30
    sqlite_busy_timeout: float = 30
    sqlite_wal: bool = True
    sqlite_foreign_keys: bool = True

    def __post_init__(self) -> None:
        for name in ("pool_size", "pool_recycle", "connect_timeout"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.max_overflow) is not int or self.max_overflow < 0:
            raise ValueError("max_overflow must be a nonnegative integer")
        for name in ("pool_timeout", "read_timeout", "write_timeout", "sqlite_busy_timeout"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("sqlite_wal", "sqlite_foreign_keys"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
