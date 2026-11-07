from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from cat_herder.domain.config import TimeOrigin
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.store.base import Base


class TimeEntryRow(Base):
    __tablename__ = 'time_entries'

    source: Mapped[str] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(primary_key=True)
    space: Mapped[str]
    person: Mapped[str]
    description: Mapped[str]
    start: Mapped[datetime]
    end: Mapped[datetime]
    ticket_key: Mapped[str | None]
    sprint: Mapped[str | None]
    flags: Mapped[list[str]]


class TimeEntryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(self, origin: TimeOrigin, start: datetime, end: datetime, entries: Iterable[TimeEntry]) -> None:
        """Replace the stored entries in those spaces starting from start until before end with these."""
        self._session.execute(
            delete(TimeEntryRow).where(
                TimeEntryRow.source == origin.source,
                TimeEntryRow.space.in_(origin.spaces),
                TimeEntryRow.start >= start,
                TimeEntryRow.start < end,
            )
        )
        for entry in entries:
            self._session.merge(_row(entry))
        self._session.flush()

    def find(
        self,
        origin: TimeOrigin,
        ticket_key: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[TimeEntry]:
        """The entries stored in those spaces, oldest first, that match every criterion given.

        start and end bound the entry's start, start included and end not.
        """
        query = select(TimeEntryRow).where(TimeEntryRow.source == origin.source, TimeEntryRow.space.in_(origin.spaces))
        if ticket_key:
            query = query.where(TimeEntryRow.ticket_key == ticket_key)
        if start:
            query = query.where(TimeEntryRow.start >= start)
        if end:
            query = query.where(TimeEntryRow.start < end)
        return [_entry(row) for row in self._session.scalars(query.order_by(TimeEntryRow.start))]


def _row(entry: TimeEntry) -> TimeEntryRow:
    return TimeEntryRow(
        source=entry.source,
        source_id=entry.id,
        space=entry.space,
        person=entry.person,
        description=entry.description,
        start=entry.start,
        end=entry.end,
        ticket_key=entry.ticket_key,
        sprint=entry.sprint,
        flags=sorted(entry.flags),
    )


def _entry(row: TimeEntryRow) -> TimeEntry:
    return TimeEntry(
        source=row.source,
        id=row.source_id,
        space=row.space,
        person=row.person,
        description=row.description,
        start=row.start,
        end=row.end,
        ticket_key=row.ticket_key,
        sprint=row.sprint,
        flags=frozenset(TimeEntryFlag(flag) for flag in row.flags),
    )
