from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Person, Project, TicketOrigin, TimeOrigin
from cat_herder.domain.ticket import Change, Sprint, SprintState
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from tests.dates import november, october, september
from tests.factories import (
    new_change,
    new_jira_source_config,
    new_link,
    new_sprint,
    new_ticket,
    new_ticket_summary,
    new_time_entry,
    new_time_origin,
    new_toggl_source_config,
)


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session]:
    with database_session(open_database(tmp_path)) as session:
        yield session


@pytest.fixture
def config() -> Config:
    """sat with tickets and time, web with tickets only, and admin with time only. Ana works on sat, and Bob on web."""
    return Config(
        data_dir=Path(),
        sources=(
            new_jira_source_config(
                slug='jira', done_statuses=('Done',), discarded_statuses=('Cancelled',), blocking_relation='blocks'
            ),
            new_toggl_source_config(slug='toggl'),
        ),
        projects=(
            Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=new_time_origin()),
            Project(slug='web', tickets=TicketOrigin(source='jira', space='WEB'), time=None),
            Project(slug='admin', tickets=None, time=TimeOrigin(source='toggl', spaces=('Admin',))),
        ),
        people=(
            Person(
                slug='ana',
                identity_by_source={'jira': 'account-ana', 'toggl': 456},
                weekly_hours=20,
                hours_by_project={'sat': 10},
            ),
            Person(
                slug='bob',
                identity_by_source={'jira': 'account-bob', 'toggl': 789},
                weekly_hours=10,
                hours_by_project={'web': 5},
            ),
        ),
    )


@pytest.fixture
def save_sprint_1(session: Session) -> Callable[..., Sprint]:
    """Saves Sprint 1, ended, from October 1st to 15th, with any overrides to the sprint. It held:

    - SAT-1, Ana's, from its first day, done on the 10th.
    - SAT-2, added on the 5th.
    - SAT-3 from its first day, removed on the 8th.
    - SAT-4, carried over with 4 h logged before, and cancelled on the 12th.
    - SAT-5, done before the sprint.
    - WEB-1, done on the 3rd.
    """

    def save(**overrides: Any) -> Sprint:
        fields = {'state': SprintState.ENDED, 'actual_end': october(15)} | overrides
        sprint = new_sprint(name='Sprint 1', start=october(1), planned_end=october(15), **fields)
        tickets = TicketRepository(session)
        for ticket in (
            new_ticket(key='SAT-1', status='Done', assignee='account-ana', points=5, estimated_hours=8, changes=(
                _into_sprint_1(october(1) - timedelta(hours=1)), _status('In progress', 'Done', october(10)),
            )),
            new_ticket(key='SAT-2', status='In progress', points=3, estimated_hours=4, changes=(
                _into_sprint_1(october(5)),
            )),
            new_ticket(key='SAT-3', status='To do', points=2, estimated_hours=2, changes=(
                _into_sprint_1(october(1) - timedelta(hours=1)),
                new_change(field='sprints', before='Sprint 1', after=None, date=october(8)),
            )),
            new_ticket(key='SAT-4', status='Cancelled', points=1, estimated_hours=10, changes=(
                _into_sprint_1(september(28)), _status('To do', 'Cancelled', october(12)),
            )),
            new_ticket(key='SAT-5', status='Done', points=1, changes=(
                _into_sprint_1(september(28)), _status('In progress', 'Done', september(29)),
            )),
            new_ticket(key='WEB-1', space='WEB', status='Done', points=8, estimated_hours=5, changes=(
                _into_sprint_1(september(28)), _status('In progress', 'Done', october(3)),
            )),
        ):
            removed = ticket.key == 'SAT-3'
            tickets.save(replace(ticket, sprints=() if removed else (sprint,)), october(30))
        TimeEntryRepository(session).replace(new_time_origin(), september(1), october(31), [
            new_time_entry(id='1', start=october(5), hours=6, ticket_key='SAT-1'),
            new_time_entry(id='2', start=september(20), hours=4, ticket_key='SAT-4'),
            new_time_entry(id='3', start=october(6), hours=1),
            new_time_entry(id='4', start=october(7), hours=2, ticket_key='SAT-2', person='999'),
            new_time_entry(id='5', start=october(20), hours=3, ticket_key='SAT-1'),
        ])
        admin = TimeOrigin(source='toggl', spaces=('Admin',))
        TimeEntryRepository(session).replace(admin, september(1), october(31), [
            new_time_entry(id='6', start=october(6), hours=1, space='Admin'),
        ])
        return sprint

    return save


@pytest.fixture
def save_sprint_2(session: Session) -> Callable[..., Sprint]:
    """Saves Sprint 2, not started, for the two weeks from November 2nd, with any overrides to the sprint. It holds:

    - SAT-1, Ana's, estimated at 10 h, with 4 h logged.
    - SAT-2, unassigned.
    - SAT-3, Ana's, without an estimate.
    - SAT-4, done.
    - WEB-1, Bob's, blocked by SAT-1, WEB-2 and WEB-3, which is done. It blocks WEB-9.
    """

    def save(**overrides: Any) -> Sprint:
        fields = {'start': november(2), 'planned_end': november(16)} | overrides
        sprint = new_sprint(id='2', name='Sprint 2', state=SprintState.NOT_STARTED, **fields)
        blocks = [
            new_link(from_key=blocker, relation='blocks', to_key='WEB-1') for blocker in ('SAT-1', 'WEB-2', 'WEB-3')
        ]
        tickets = TicketRepository(session)
        for ticket in (
            new_ticket(key='SAT-1', assignee='account-ana', points=5, estimated_hours=10),
            new_ticket(key='SAT-2', points=3, estimated_hours=4),
            new_ticket(key='SAT-3', assignee='account-ana', points=2),
            new_ticket(key='SAT-4', status='Done', assignee='account-ana', points=1, estimated_hours=1),
            new_ticket(
                key='WEB-1',
                space='WEB',
                assignee='account-bob',
                points=8,
                estimated_hours=15,
                links=(*blocks, new_link(from_key='WEB-1', relation='blocks', to_key='WEB-9')),
                related_summaries=(
                    new_ticket_summary(key='SAT-1', status='To do'),
                    new_ticket_summary(key='WEB-2', status='To do'),
                    new_ticket_summary(key='WEB-3', status='Done'),
                    new_ticket_summary(key='WEB-9', status='To do'),
                ),
            ),
        ):
            tickets.save(replace(ticket, sprints=(sprint,)), november(1))
        TimeEntryRepository(session).replace(new_time_origin(), october(1), november(1), [
            new_time_entry(id='1', start=october(20), hours=4, ticket_key='SAT-1'),
        ])
        return sprint

    return save


def _into_sprint_1(day: datetime) -> Change:
    return new_change(field='sprints', before=None, after='Sprint 1', date=day)


def _status(before: str, after: str, day: datetime) -> Change:
    return new_change(field='status', before=before, after=after, date=day)
