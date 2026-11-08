from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, TicketSourceConfig
from cat_herder.domain.ticket import Ticket
from cat_herder.domain.time_entry import Hours
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository


@dataclass(frozen=True, kw_only=True)
class ProjectReport:
    """Points of the tickets done, and hours, which are None if the project has no time source."""

    points: float
    hours: Hours | None

    @property
    def ticket_speed(self) -> float | None:
        """Points per hour on tickets. None without a time source or hours on tickets."""
        return self.points / self.hours.tickets if self.hours and self.hours.tickets else None

    @property
    def total_speed(self) -> float | None:
        """Points per hour, counting hours on no ticket too. None without a time source or hours."""
        return self.points / self.hours.total if self.hours and self.hours.total else None


class ProjectReportService:
    def __init__(self, config: Config, session: Session) -> None:
        self._config = config
        self._ticket_repository = TicketRepository(session)
        self._time_entry_repository = TimeEntryRepository(session)

    def project_report(
        self, project_slug: str, start: datetime | None = None, end: datetime | None = None
    ) -> ProjectReport:
        """The project's tickets done and hours between start, included, and end, excluded, or for all time.

        Raises:
            KeyError: if no project has that slug.
        """
        project = self._config.project(project_slug)
        points = 0.0
        hours = None
        if project.tickets:
            source = self._config.ticket_source(project.tickets.source)
            tickets = self._ticket_repository.find([project.tickets])
            points = sum(_done_points(source, ticket, start, end) for ticket in tickets)
        if project.time:
            hours = Hours.of(self._time_entry_repository.find(project.time, start=start, end=end))
        return ProjectReport(points=points, hours=hours)


def _done_points(source: TicketSourceConfig, ticket: Ticket, start: datetime | None, end: datetime | None) -> float:
    done = source.done_date(ticket)
    if done and (not start or done >= start) and (not end or done < end) and ticket.points:
        return ticket.points
    return 0
