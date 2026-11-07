from datetime import datetime

from sqlalchemy.orm import Mapped, Session, mapped_column

from cat_herder.store.base import Base


class TicketSpaceSyncRow(Base):
    __tablename__ = 'ticket_space_syncs'

    source: Mapped[str] = mapped_column(primary_key=True)
    space: Mapped[str] = mapped_column(primary_key=True)
    synced_at: Mapped[datetime]


class TicketSpaceSyncRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_last_sync(self, source: str, space: str) -> datetime | None:
        """When the space was last synced, or None if it never was."""
        row = self._session.get(TicketSpaceSyncRow, (source, space))
        return row.synced_at if row else None

    def save(self, source: str, space: str, synced_at: datetime) -> None:
        self._session.merge(TicketSpaceSyncRow(source=source, space=space, synced_at=synced_at))
