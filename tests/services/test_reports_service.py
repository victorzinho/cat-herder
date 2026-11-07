from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Project, TicketOrigin, TimeOrigin
from cat_herder.domain.report import Hours, ProjectReport
from cat_herder.domain.ticket import Ticket
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.services.reports_service import ReportsService
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from tests.factories import new_change, new_jira_source_config, new_ticket, new_time_entry, new_toggl_source_config


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session]:
    with database_session(open_database(tmp_path)) as session:
        yield session


@pytest.mark.parametrize(('start', 'end', 'points'), [
    pytest.param(None, None, 8, id='everything'),
    pytest.param(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC), 5, id='range'),
])
def test_project_report_adds_up_the_points_of_the_tickets_done_in_the_range(
    session: Session, start: datetime | None, end: datetime | None, points: float
) -> None:
    # GIVEN SAT-1 done on the 10th, SAT-2 on the 20th, SAT-3 open, and WEB-1 done in another project
    tickets = TicketRepository(session)
    tickets.save(_done('SAT-1', 'SAT', _october(10), points=5), _october(30))
    tickets.save(_done('SAT-2', 'SAT', _october(20), points=3), _october(30))
    tickets.save(new_ticket(key='SAT-3', space='SAT', status='To do', points=13), _october(30))
    tickets.save(_done('WEB-1', 'WEB', _october(10), points=21), _october(30))
    cut = ReportsService(_config(), session)

    # WHEN
    report = cut.project_report('sat', start, end)

    # THEN
    assert report.points == points


def test_project_report_splits_the_hours_in_the_range_into_tickets_and_the_rest(session: Session) -> None:
    # GIVEN on the 5th 2 h on SAT-1, 1 h on no ticket and 0.5 h flagged, and on the 20th 3 h on SAT-1
    entries = [
        _entry('1', _october(5), 2, ticket_key='SAT-1'),
        _entry('2', _october(5), 1),
        _entry('3', _october(5), 0.5, flags=frozenset({TimeEntryFlag.TICKET_NOT_FOUND})),
        _entry('4', _october(20), 3, ticket_key='SAT-1'),
    ]
    TimeEntryRepository(session).replace(_sat_time(), _october(1), _october(31), entries)
    cut = ReportsService(_config(), session)

    # WHEN
    report = cut.project_report('sat', _october(1), _october(16))

    # THEN
    assert report.hours == Hours(tickets=2, others=1.5)


@pytest.mark.parametrize(('project', 'expected'), [
    pytest.param('web', ProjectReport(points=0, hours=None), id='no-time-source'),
    pytest.param('admin', ProjectReport(points=0, hours=Hours(tickets=0, others=0)), id='no-ticket-source'),
])
def test_project_report_has_no_hours_without_a_time_source_and_no_points_without_tickets(
    session: Session, project: str, expected: ProjectReport
) -> None:
    # GIVEN
    cut = ReportsService(_config(), session)

    # WHEN / THEN
    assert cut.project_report(project) == expected


def _config() -> Config:
    # sat with tickets and time, web with tickets only, and admin with time only.
    return Config(
        data_dir=Path(),
        sources=(new_jira_source_config(slug='jira', done_statuses=('Done',)), new_toggl_source_config(slug='toggl')),
        projects=(
            Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=_sat_time()),
            Project(slug='web', tickets=TicketOrigin(source='jira', space='WEB'), time=None),
            Project(slug='admin', tickets=None, time=TimeOrigin(source='toggl', spaces=('Admin',))),
        ),
    )


def _sat_time() -> TimeOrigin:
    return TimeOrigin(source='toggl', spaces=('SAT',))


def _done(key: str, space: str, day: datetime, points: float) -> Ticket:
    into_done = new_change(field='status', before='In progress', after='Done', date=day)
    return new_ticket(key=key, space=space, status='Done', points=points, changes=(into_done,))


def _entry(entry_id: str, start: datetime, hours: float, **overrides: Any) -> TimeEntry:
    return new_time_entry(id=entry_id, space='SAT', start=start, end=start + timedelta(hours=hours), **overrides)


def _october(day: int) -> datetime:
    return datetime(2026, 10, day, 9, tzinfo=UTC)
