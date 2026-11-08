from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Ticket
from cat_herder.domain.time_entry import Hours, TimeEntryFlag
from cat_herder.services.project_report_service import ProjectReport, ProjectReportService
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from tests.dates import october, parse
from tests.factories import new_change, new_ticket, new_time_entry, new_time_origin


@pytest.mark.parametrize(('start', 'end', 'points'), [
    pytest.param(None, None, 8, id='everything'),
    pytest.param(parse('2026-10-01T00:00:00Z'), parse('2026-10-16T00:00:00Z'), 5, id='range'),
])
def test_project_report_adds_up_the_points_of_the_tickets_done_in_the_range(
    session: Session, start: datetime | None, end: datetime | None, points: float, config: Config
) -> None:
    # GIVEN
    fetched_at = october(30)
    tickets = TicketRepository(session)
    tickets.save(_done('SAT-1', 'SAT', october(10), points=5), fetched_at)
    tickets.save(_done('SAT-2', 'SAT', october(20), points=3), fetched_at)
    tickets.save(new_ticket(key='SAT-3', space='SAT', status='To do', points=13), fetched_at)
    tickets.save(_done('WEB-1', 'WEB', october(10), points=21), fetched_at)
    cut = ProjectReportService(config, session)

    # WHEN
    report = cut.project_report('sat', start, end)

    # THEN
    assert report.points == points


def test_project_report_splits_the_hours_in_the_range_into_tickets_and_the_rest(
    session: Session, config: Config
) -> None:
    # GIVEN
    entries = [
        new_time_entry(id='1', start=october(5), hours=2, ticket_key='SAT-1'),
        new_time_entry(id='2', start=october(5), hours=1),
        new_time_entry(id='3', start=october(5), hours=0.5, flags=frozenset({TimeEntryFlag.TICKET_NOT_FOUND})),
        new_time_entry(id='4', start=october(20), hours=3, ticket_key='SAT-1'),
    ]
    TimeEntryRepository(session).replace(new_time_origin(), october(1), october(31), entries)
    cut = ProjectReportService(config, session)

    # WHEN
    report = cut.project_report('sat', october(1), october(16))

    # THEN
    assert report.hours == Hours(tickets=2, others=1.5)


@pytest.mark.parametrize(('project', 'expected'), [
    pytest.param('web', ProjectReport(points=0, hours=None), id='no-time-source'),
    pytest.param('admin', ProjectReport(points=0, hours=Hours(tickets=0, others=0)), id='no-ticket-source'),
])
def test_project_report_has_no_hours_without_a_time_source_and_no_points_without_tickets(
    session: Session, project: str, expected: ProjectReport, config: Config
) -> None:
    # GIVEN
    cut = ProjectReportService(config, session)

    # WHEN / THEN
    assert cut.project_report(project) == expected


def _done(key: str, space: str, day: datetime, points: float) -> Ticket:
    into_done = new_change(field='status', before='In progress', after='Done', date=day)
    return new_ticket(key=key, space=space, status='Done', points=points, changes=(into_done,))
