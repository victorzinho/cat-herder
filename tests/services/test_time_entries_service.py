from collections.abc import Collection, Generator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Project, TicketOrigin, TimeOrigin
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.services.time_entries_service import REFRESH_DAYS, TimeEntriesService
from cat_herder.sources.time_source import TimeSource
from cat_herder.sources.toggl.client import TogglClient
from cat_herder.sources.toggl.source import TogglSource
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.ticket_space_sync_repository import TicketSpaceSyncRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from cat_herder.store.time_source_sync_repository import TimeSourceSync, TimeSourceSyncRepository
from tests.factories import new_sprint, new_ticket, new_time_entry
from tests.jira_api import JIRA_CONFIG
from tests.toggl_api import ADMIN_PROJECT, SAT_PROJECT, TOGGL_CONFIG, TogglApi


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session]:
    with database_session(open_database(tmp_path)) as session:
        yield session


@pytest.fixture
def toggl_api() -> TogglApi:
    return TogglApi()


def test_spent_hours_sums_the_entries_on_the_ticket_after_syncing_from_history_from(
    session: Session, toggl_api: TogglApi
) -> None:
    # GIVEN
    cut = _service(session, toggl_api)

    # WHEN
    hours = cut.spent_hours(new_ticket(key='SAT-7', space='SAT'))

    # THEN 9001 and 9002 are on SAT-7, and 9004 names two tickets. The search starts a day before history_from's local
    # midnight in UTC, which is December 30 or 31 depending on the time zone.
    assert hours == 3.5
    assert toggl_api.searches()[0]['start_date'] in {'2025-12-30', '2025-12-31'}
    sync = TimeSourceSyncRepository(session).get_last_sync(_origin(SAT_PROJECT, ADMIN_PROJECT))
    assert sync and sync.resume_from == _refresh_from()


def test_spent_hours_is_none_without_a_time_source(session: Session, toggl_api: TogglApi) -> None:
    # GIVEN a project with no time source
    sat = Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=None)
    config = replace(_config(), projects=(sat,))
    cut = _service(session, toggl_api, config)

    # WHEN
    hours = cut.spent_hours(new_ticket(key='SAT-7', space='SAT'))

    # THEN
    assert hours is None
    assert toggl_api.requests == []


def test_spent_hours_is_none_with_a_warning_when_never_synced(
    session: Session, toggl_api: TogglApi, caplog: pytest.LogCaptureFixture
) -> None:
    # GIVEN
    toggl_api.reachable = False
    cut = _service(session, toggl_api)

    # WHEN
    hours = cut.spent_hours(new_ticket(key='SAT-7', space='SAT'))

    # THEN
    assert hours is None
    assert caplog.messages == ['toggl unreachable, its time entries were never synced']


@pytest.mark.parametrize(('force_fetch', 'kept'), [
    pytest.param(False, ['old'], id='after-window'),
    pytest.param(True, [], id='forced'),
])
def test_sync_replaces_the_last_30_days_or_everything_when_forced(
    session: Session, toggl_api: TogglApi, force_fetch: bool, kept: list[str]
) -> None:
    # GIVEN fetched before the window, with stored entries 40 and 5 days ago that are gone from Toggl
    toggl_api.rows = []
    stored = [
        new_time_entry(id='old', space=SAT_PROJECT, start=_days_ago(40)),
        new_time_entry(id='recent', space=SAT_PROJECT, start=_days_ago(5)),
    ]
    TimeEntryRepository(session).replace(_origin(SAT_PROJECT), _days_ago(400), _days_ago(0), stored)
    window = timedelta(seconds=TOGGL_CONFIG.fetch_window_seconds)
    synced_before = TimeSourceSync(resume_from=_refresh_from(), synced_at=datetime.now(UTC) - window * 2)
    TimeSourceSyncRepository(session).save(_origin(SAT_PROJECT, ADMIN_PROJECT), synced_before)
    cut = _service(session, toggl_api)

    # WHEN
    cut.sync(force_fetch=force_fetch)

    # THEN
    assert [entry.id for entry in TimeEntryRepository(session).find(_origin(SAT_PROJECT))] == kept


@pytest.mark.parametrize(('entry_id', 'ticket_key', 'flags'), [
    pytest.param('9001', 'SAT-7', set[TimeEntryFlag](), id='in-project'),
    pytest.param('9003', None, set[TimeEntryFlag](), id='no-key'),
    pytest.param('9004', None, {TimeEntryFlag.SEVERAL_TICKETS}, id='several-keys'),
    pytest.param('9005', None, {TimeEntryFlag.TICKET_IN_OTHER_PROJECT}, id='in-another-project'),
    pytest.param('9006', None, {TimeEntryFlag.TICKET_NOT_FOUND}, id='missing-ticket'),
])
def test_sync_validates_the_ticket_each_entry_refers_to(
    session: Session, toggl_api: TogglApi, entry_id: str, ticket_key: str | None, flags: set[TimeEntryFlag]
) -> None:
    # GIVEN the SAT space synced with only SAT-7
    TicketRepository(session).save(new_ticket(key='SAT-7', space='SAT'), datetime.now(UTC))
    TicketSpaceSyncRepository(session).save('jira', 'SAT', datetime.now(UTC))
    cut = _service(session, toggl_api)

    # WHEN
    cut.sync()

    # THEN
    entry = _stored(session, entry_id)
    assert (entry.ticket_key, entry.flags) == (ticket_key, flags)


def test_sync_keeps_an_unvalidated_key_until_its_space_is_synced(session: Session, toggl_api: TogglApi) -> None:
    # GIVEN
    cut = _service(session, toggl_api)

    # WHEN
    cut.sync()

    # THEN
    entry = _stored(session, '9006')
    assert (entry.ticket_key, entry.flags) == ('SAT-99', set())


def test_sync_drops_a_sprint_that_doesnt_exist_with_a_flag(session: Session) -> None:
    # GIVEN entries in a stored sprint and in a missing one
    sat_7 = new_ticket(key='SAT-7', space='SAT', sprints=(new_sprint(name='Sprint 1'),))
    TicketRepository(session).save(sat_7, datetime.now(UTC))
    start = _days_ago(1)
    source = _ReportedEntries([
        new_time_entry(id='1', space=ADMIN_PROJECT, start=start, end=start + timedelta(hours=1), sprint='Sprint 1'),
        new_time_entry(id='2', space=ADMIN_PROJECT, start=start, end=start + timedelta(hours=1), sprint='Sprint 9'),
    ])
    cut = TimeEntriesService(_config(), session, [source])

    # WHEN
    cut.sync()

    # THEN
    entries = TimeEntryRepository(session).find(_origin(ADMIN_PROJECT))
    assert [(entry.sprint, entry.flags) for entry in entries] == [
        ('Sprint 1', set()), (None, {TimeEntryFlag.SPRINT_NOT_FOUND})
    ]


@dataclass
class _ReportedEntries:
    """A time source reporting these entries, as sources other than Toggl can report sprints."""

    entries: list[TimeEntry]
    slug: str = 'toggl'
    max_fetch_days: int = 364

    def fetch_time_entries(self, spaces: Collection[str], start: datetime, end: datetime) -> list[TimeEntry]:
        return [entry for entry in self.entries if entry.space in spaces and start <= entry.start < end]


def _config(**toggl_overrides: Any) -> Config:
    # sat, with tickets in Jira's SAT and time in Toggl's SAT, and admin, with time in Toggl's Admin.
    return Config(
        data_dir=Path(),
        sources=(JIRA_CONFIG, replace(TOGGL_CONFIG, **toggl_overrides)),
        projects=(
            Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=_origin(SAT_PROJECT)),
            Project(slug='admin', tickets=None, time=_origin(ADMIN_PROJECT)),
        ),
    )


def _origin(*spaces: str) -> TimeOrigin:
    return TimeOrigin(source='toggl', spaces=spaces)


def _refresh_from() -> date:
    return date.today() - timedelta(days=REFRESH_DAYS)


def _service(session: Session, toggl_api: TogglApi, config: Config | None = None) -> TimeEntriesService:
    return TimeEntriesService(config or _config(), session, [_toggl(toggl_api)])


def _toggl(toggl_api: TogglApi) -> TimeSource:
    return TogglSource(TOGGL_CONFIG, TogglClient(lambda: 'token', transport=httpx.MockTransport(toggl_api)))


def _stored(session: Session, entry_id: str) -> TimeEntry:
    return next(entry for entry in TimeEntryRepository(session).find(_origin(SAT_PROJECT)) if entry.id == entry_id)


def _days_ago(days: int) -> datetime:
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days)
