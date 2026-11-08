from collections.abc import Generator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Person, Project, TicketOrigin, TimeOrigin
from cat_herder.domain.ticket import Change, Sprint, SprintState, Ticket
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.services.reports_service import ReportsService
from cat_herder.services.reports_types import (
    Hours,
    ProjectReport,
    SprintFigures,
    SprintOutcome,
    SprintPerson,
    SprintTicket,
    TicketCount,
)
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from tests.dates import parse
from tests.factories import (
    new_change,
    new_jira_source_config,
    new_sprint,
    new_ticket,
    new_time_entry,
    new_toggl_source_config,
)


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session]:
    with database_session(open_database(tmp_path)) as session:
        yield session


@pytest.mark.parametrize(('start', 'end', 'points'), [
    pytest.param(None, None, 8, id='everything'),
    pytest.param(parse('2026-10-01T00:00:00Z'), parse('2026-10-16T00:00:00Z'), 5, id='range'),
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


def test_ended_sprint_report_lists_the_tickets_it_held_at_any_point(session: Session) -> None:
    # GIVEN
    cut = ReportsService(_config(), session)

    # WHEN
    report = cut.ended_sprint_report(_save_sprint_1(session))

    # THEN SAT-2 was added later, SAT-3 removed, and SAT-4 had 4 h logged before. SAT-5 has no estimate.
    [sat, web] = report.projects
    assert sat.tickets == (
        SprintTicket(key='SAT-1', status='Done', points=5, estimate=8, hours=6, reestimated_by=0),
        SprintTicket(key='SAT-2', status='In progress', points=3, estimate=4, hours=2, reestimated_by=4),
        SprintTicket(key='SAT-3', status='To do', points=2, estimate=0, hours=0, reestimated_by=-2),
        SprintTicket(key='SAT-4', status='Cancelled', points=1, estimate=6, hours=0, reestimated_by=0),
        SprintTicket(key='SAT-5', status='Done', points=1, estimate=None, hours=0, reestimated_by=0),
    )
    assert web.tickets == (
        SprintTicket(key='WEB-1', status='Done', points=8, estimate=5, hours=None, reestimated_by=0),
    )


def test_ended_sprint_report_gives_each_projects_plan_hours_and_outcome(session: Session) -> None:
    # GIVEN
    cut = ReportsService(_config(), session)

    # WHEN
    report = cut.ended_sprint_report(_save_sprint_1(session))

    # THEN SAT-5 was done before the sprint and SAT-3 removed, so they count in no outcome. admin has no tickets in it.
    [sat, web] = report.projects
    assert (sat.project, sat.capacity, sat.estimate, sat.reestimated_by) == ('sat', 20, 18, 2)
    assert sat.hours == Hours(tickets=8, others=1)
    assert sat.outcome == SprintOutcome(
        done=TicketCount(tickets=1, points=5),
        discarded=TicketCount(tickets=1, points=1),
        open=TicketCount(tickets=1, points=3),
    )
    assert sat.people == (
        SprintPerson(person='ana', capacity=20, hours=7),
        SprintPerson(person='unknown (999)', capacity=0, hours=2),
    )
    assert (web.project, web.capacity, web.hours) == ('web', 10, None)
    assert web.people == (SprintPerson(person='bob', capacity=10, hours=None),)


def test_ended_sprint_report_adds_up_a_total_with_each_persons_own_capacity(session: Session) -> None:
    # GIVEN
    cut = ReportsService(_config(), session)

    # WHEN
    report = cut.ended_sprint_report(_save_sprint_1(session))

    # THEN web has no time source, so the hours are sat's
    assert report.total == SprintFigures(
        capacity=60,
        estimate=23,
        reestimated_by=2,
        hours=Hours(tickets=8, others=1),
        outcome=SprintOutcome(
            done=TicketCount(tickets=2, points=13),
            discarded=TicketCount(tickets=1, points=1),
            open=TicketCount(tickets=1, points=3),
        ),
        people=(
            SprintPerson(person='ana', capacity=40, hours=7),
            SprintPerson(person='bob', capacity=20, hours=0),
            SprintPerson(person='unknown (999)', capacity=0, hours=2),
        ),
    )


def _config() -> Config:
    # sat with tickets and time, web with tickets only, and admin with time only. Ana works on sat, and Bob on web.
    return Config(
        data_dir=Path(),
        sources=(
            new_jira_source_config(slug='jira', done_statuses=('Done',), discarded_statuses=('Cancelled',)),
            new_toggl_source_config(slug='toggl'),
        ),
        projects=(
            Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=_sat_time()),
            Project(slug='web', tickets=TicketOrigin(source='jira', space='WEB'), time=None),
            Project(slug='admin', tickets=None, time=TimeOrigin(source='toggl', spaces=('Admin',))),
        ),
        people=(
            Person(slug='ana', identity_by_source={'toggl': 456}, weekly_hours=20, hours_by_project={'sat': 10}),
            Person(slug='bob', identity_by_source={'toggl': 789}, weekly_hours=10, hours_by_project={'web': 5}),
        ),
    )


def _sat_time() -> TimeOrigin:
    return TimeOrigin(source='toggl', spaces=('SAT',))


def _done(key: str, space: str, day: datetime, points: float) -> Ticket:
    into_done = new_change(field='status', before='In progress', after='Done', date=day)
    return new_ticket(key=key, space=space, status='Done', points=points, changes=(into_done,))


def _entry(entry_id: str, start: datetime, hours: float, **overrides: Any) -> TimeEntry:
    fields = {'space': 'SAT', 'person': '456'} | overrides
    return new_time_entry(id=entry_id, start=start, end=start + timedelta(hours=hours), **fields)


def _october(day: int) -> datetime:
    return parse(f'2026-10-{day:02}T09:00:00Z')


def _save_sprint_1(session: Session) -> Sprint:
    # Sprint 1, from October 1st to 15th, which held:
    # - SAT-1 from its first day, done on the 10th.
    # - SAT-2, added on the 5th.
    # - SAT-3 from its first day, removed on the 8th.
    # - SAT-4, carried over with 4 h logged before, and cancelled on the 12th.
    # - SAT-5, done before the sprint.
    # - WEB-1, done on the 3rd.
    sprint = new_sprint(name='Sprint 1', state=SprintState.ENDED, start=_october(1), actual_end=_october(15))
    tickets = TicketRepository(session)
    for ticket in (
        new_ticket(key='SAT-1', status='Done', points=5, estimated_hours=8, changes=(
            _into_sprint(_october(1) - timedelta(hours=1)), _status('In progress', 'Done', _october(10)),
        )),
        new_ticket(key='SAT-2', status='In progress', points=3, estimated_hours=4, changes=(
            _into_sprint(_october(5)),
        )),
        new_ticket(key='SAT-3', status='To do', points=2, estimated_hours=2, changes=(
            _into_sprint(_october(1) - timedelta(hours=1)),
            new_change(field='sprints', before='Sprint 1', after=None, date=_october(8)),
        )),
        new_ticket(key='SAT-4', status='Cancelled', points=1, estimated_hours=10, changes=(
            _into_sprint(_september(28)), _status('To do', 'Cancelled', _october(12)),
        )),
        new_ticket(key='SAT-5', status='Done', points=1, changes=(
            _into_sprint(_september(28)), _status('In progress', 'Done', _september(29)),
        )),
        new_ticket(key='WEB-1', space='WEB', status='Done', points=8, estimated_hours=5, changes=(
            _into_sprint(_september(28)), _status('In progress', 'Done', _october(3)),
        )),
    ):
        removed = ticket.key == 'SAT-3'
        tickets.save(replace(ticket, sprints=() if removed else (sprint,)), _october(30))
    entries = [
        _entry('1', _october(5), 6, ticket_key='SAT-1'),
        _entry('2', _september(20), 4, ticket_key='SAT-4'),
        _entry('3', _october(6), 1),
        _entry('4', _october(7), 2, ticket_key='SAT-2', person='999'),
        _entry('5', _october(20), 3, ticket_key='SAT-1'),
    ]
    TimeEntryRepository(session).replace(_sat_time(), _september(1), _october(31), entries)
    admin = TimeOrigin(source='toggl', spaces=('Admin',))
    TimeEntryRepository(session).replace(admin, _september(1), _october(31), [
        _entry('6', _october(6), 1, space='Admin'),
    ])
    return sprint


def _into_sprint(day: datetime) -> Change:
    return new_change(field='sprints', before=None, after='Sprint 1', date=day)


def _status(before: str, after: str, day: datetime) -> Change:
    return new_change(field='status', before=before, after=after, date=day)


def _september(day: int) -> datetime:
    return parse(f'2026-09-{day:02}T12:00:00Z')
