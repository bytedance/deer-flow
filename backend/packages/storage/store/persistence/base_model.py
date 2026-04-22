from datetime import datetime
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Integer, Text, TypeDecorator
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, declared_attr, mapped_column

from store.common import DataBaseType
from store.config.app_config import get_app_config
from store.utils import get_timezone

timezone = get_timezone()
app_config = get_app_config()

# SQLite autoincrement only works with INTEGER PRIMARY KEY (not BIGINT)
_id_type = Integer if app_config.storage.driver == DataBaseType.sqlite else BigInteger

id_key = Annotated[
    int,
    mapped_column(
        _id_type,
        primary_key=True,
        unique=True,
        index=True,
        autoincrement=True,
        sort_order=-999,
        comment="Primary key ID",
    )
]


class UniversalText(TypeDecorator[str]):
    """Cross-dialect long text type (LONGTEXT on MySQL, Text on PostgreSQL)."""

    impl = LONGTEXT if DataBaseType.mysql == app_config.storage.driver else Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        return value

    def process_result_value(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        return value


class TimeZone(TypeDecorator[datetime]):
    """Timezone-aware datetime type compatible with PostgreSQL and MySQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime]:
        return datetime

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is not None and value.utcoffset() != timezone.now().utcoffset():
            value = timezone.from_datetime(value)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.tz_info)
        return value


class DateTimeMixin(MappedAsDataclass):
    """Mixin that adds created_time / updated_time columns."""

    created_time: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=timezone.now,
        sort_order=999,
        comment="Created at",
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        TimeZone,
        init=False,
        onupdate=timezone.now,
        sort_order=999,
        comment="Updated at",
    )


class MappedBase(AsyncAttrs, DeclarativeBase):
    """Async-capable declarative base for all ORM models."""

    @declared_attr.directive
    def __tablename__(self) -> str:
        return self.__name__.lower()

    @declared_attr.directive
    def __table_args__(self) -> dict:
        return {"comment": self.__doc__ or ""}


class DataClassBase(MappedAsDataclass, MappedBase):
    """Declarative base with native dataclass integration."""

    __abstract__ = True


class Base(DataClassBase, DateTimeMixin):
    """Declarative dataclass base with created_time / updated_time columns."""

    __abstract__ = True
