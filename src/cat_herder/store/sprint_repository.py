from datetime import datetime

from sqlalchemy import UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from cat_herder.domain.ticket import Sprint, SprintState
from cat_herder.store.base import Base


class SprintRow(Base):
    __tablename__ = 'sprints'
    __table_args__ = (UniqueConstraint('source', 'source_id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    source_id: Mapped[str]
    name: Mapped[str]
    state: Mapped[str]
    start: Mapped[datetime | None]
    planned_end: Mapped[datetime | None]
    actual_end: Mapped[datetime | None]


class SprintRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, sprint: Sprint) -> SprintRow:
        """Insert or update the sprint, returning its row so a ticket row can refer to it."""
        row = self._session.scalars(
            select(SprintRow).where(SprintRow.source == sprint.source, SprintRow.source_id == sprint.id)
        ).first()
        if not row:
            row = SprintRow(source=sprint.source, source_id=sprint.id)
            self._session.add(row)
        _update_sprint_row(row, sprint)
        return row


def sprint_to_domain(row: SprintRow) -> Sprint:
    return Sprint(
        source=row.source,
        id=row.source_id,
        name=row.name,
        state=SprintState(row.state),
        start=row.start,
        planned_end=row.planned_end,
        actual_end=row.actual_end,
    )


def _update_sprint_row(row: SprintRow, sprint: Sprint) -> None:
    row.name = sprint.name
    row.state = sprint.state.value
    row.start = sprint.start
    row.planned_end = sprint.planned_end
    row.actual_end = sprint.actual_end
