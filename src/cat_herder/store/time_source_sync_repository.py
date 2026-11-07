from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Mapped, Session, mapped_column

from cat_herder.domain.config import TimeOrigin
from cat_herder.store.base import Base


@dataclass(frozen=True, kw_only=True)
class TimeSourceSync:
    """The next sync starts from resume_from, a local date. The last one was at synced_at."""

    resume_from: date
    synced_at: datetime


class TimeSourceSyncRow(Base):
    __tablename__ = 'time_source_syncs'

    source: Mapped[str] = mapped_column(primary_key=True)
    spaces: Mapped[list[str]]
    resume_from: Mapped[date]
    synced_at: Mapped[datetime]


class TimeSourceSyncRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_last_sync(self, origin: TimeOrigin) -> TimeSourceSync | None:
        """The source's last sync, or None if it never synced exactly the origin's spaces."""
        row = self._session.get(TimeSourceSyncRow, origin.source)
        if not row or tuple(row.spaces) != origin.spaces:
            return None
        return TimeSourceSync(resume_from=row.resume_from, synced_at=row.synced_at)

    def save(self, origin: TimeOrigin, sync: TimeSourceSync) -> None:
        self._session.merge(TimeSourceSyncRow(
            source=origin.source, spaces=list(origin.spaces), resume_from=sync.resume_from, synced_at=sync.synced_at
        ))
