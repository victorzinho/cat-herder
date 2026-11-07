from datetime import datetime

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, TicketSourceConfig
from cat_herder.domain.report import Hours, ProjectReport
from cat_herder.domain.ticket import Ticket
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository


class ReportsService:
    """Reports from the local copy, which the caller syncs first."""

    def __init__(self, config: Config, session: Session) -> None:
        self._config = config
        self._ticket_repository = TicketRepository(session)
        self._time_entry_repository = TimeEntryRepository(session)

    def project_report(
        self, project_slug: str, start: datetime | None = None, end: datetime | None = None
    ) -> ProjectReport:
        """The points of the tickets done from start until before end, and the hours of the entries starting then.

        Without start or end, the report covers everything before end or from start.
        """
        project = self._config.project(project_slug)
        points = 0.0
        hours = None

        if project.tickets:
            source = self._config.ticket_source(project.tickets.source)
            tickets = self._ticket_repository.find([project.tickets])
            points = sum(_get_done_ticket_points(source, ticket, start, end) for ticket in tickets)

        if project.time:
            time_entries = self._time_entry_repository.find(project.time, start=start, end=end)
            hours = Hours.of(time_entries)

        return ProjectReport(points=points, hours=hours)


def _get_done_ticket_points(
    source: TicketSourceConfig, ticket: Ticket, start: datetime | None, end: datetime | None
) -> float:
    done = source.done_date(ticket)
    if done and (not start or done >= start) and (not end or done < end) and ticket.points:
        return ticket.points
    return 0
