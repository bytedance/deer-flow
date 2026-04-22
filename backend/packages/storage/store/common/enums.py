from enum import Enum
from enum import IntEnum as SourceIntEnum
from typing import Any, TypeVar

T = TypeVar('T', bound=Enum)


class _EnumBase:
    """Base enum class with common utility methods."""

    @classmethod
    def get_member_keys(cls) -> list[str]:
        """Return a list of enum member names."""
        return list(cls.__members__.keys())

    @classmethod
    def get_member_values(cls) -> list:
        """Return a list of enum member values."""
        return [item.value for item in cls.__members__.values()]

    @classmethod
    def get_member_dict(cls) -> dict[str, Any]:
        """Return a dict mapping member names to values."""
        return {name: item.value for name, item in cls.__members__.items()}


class IntEnum(_EnumBase, SourceIntEnum):
    """Integer enum base class."""


class StrEnum(_EnumBase, str, Enum):
    """String enum base class."""


class DataBaseType(StrEnum):
    """Database type."""

    sqlite = 'sqlite'
    mysql = 'mysql'
    postgresql = 'postgresql'
