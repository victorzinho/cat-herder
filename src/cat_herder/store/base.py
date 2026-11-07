from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Dialect, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


class UtcDateTime(TypeDecorator[datetime]):
    """Aware datetimes in Python, naive UTC in SQLite, which keeps no time zone. Writing a naive one raises."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise TypeError(f'Naive datetime {value}: its time zone is unknown')
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value else None


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcDateTime, dict[str, Any]: JSON, list[str]: JSON}
