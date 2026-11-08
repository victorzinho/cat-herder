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

    def find(self, name: str, source: str | None = None) -> list[Sprint]:
        """The sprints with that name, ordered by source.

        Args:
            name: the sprint's name.
            source: the slug of the only source to look in. None looks in every source.
        """
        query = select(SprintRow).where(SprintRow.name == name)
        if source:
            query = query.where(SprintRow.source == source)
        return [sprint_to_domain(row) for row in self._session.scalars(query.order_by(SprintRow.source))]

    def find_ended(self, source: str) -> list[Sprint]:
        """The source's ended sprints, the last to end first."""
        query = select(SprintRow).where(SprintRow.source == source, SprintRow.state == SprintState.ENDED.value)
        return [sprint_to_domain(row) for row in self._session.scalars(query.order_by(SprintRow.actual_end.desc()))]

    def exists(self, name: str) -> bool:
        """Whether a sprint with that name is stored, in any source."""
        return self._session.scalars(select(SprintRow.id).where(SprintRow.name == name)).first() is not None


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
