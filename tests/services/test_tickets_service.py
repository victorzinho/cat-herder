import json
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Person, Project, TicketOrigin
from cat_herder.domain.ticket import Ticket
from cat_herder.services.tickets_service import CURRENT_SPRINT, KeyNotResolved, TicketsService
from cat_herder.sources.errors import SourceUnreachable
from cat_herder.sources.jira.client import JiraClient
from cat_herder.sources.jira.source import JiraSource
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.ticket_space_sync_repository import TicketSpaceSyncRepository
from tests.factories import new_ticket, new_toggl_source_config
from tests.jira_api import JIRA_CONFIG, JiraApi

WINDOW = timedelta(seconds=JIRA_CONFIG.fetch_window_seconds)
STORED_SAT_7 = new_ticket(key='SAT-7', title='As stored')
SAT = Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=None, repositories=('sat',))
TOGGL_CONFIG = new_toggl_source_config()
CONFIG = Config(
    data_dir=Path(),
    sources=(JIRA_CONFIG, TOGGL_CONFIG),
    projects=(SAT,),
    people=(
        Person(slug='ana', identity_by_source={'jira': 'account-ana'}),
        Person(slug='bob', identity_by_source={'toggl': 7}),
    ),
)
# SAT is a space in both jira and other.
TWO_JIRAS = replace(
    CONFIG,
    sources=(JIRA_CONFIG, replace(JIRA_CONFIG, slug='other'), TOGGL_CONFIG),
    projects=(
        SAT,
        Project(slug='web', tickets=TicketOrigin(source='jira', space='WEB'), time=None),
        Project(
            slug='sat-meteo', tickets=TicketOrigin(source='other', space='SAT'), time=None, repositories=('sat-meteo',)
        ),
    ),
)


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session]:
    with database_session(open_database(tmp_path)) as session:
        yield session


@pytest.fixture
def jira_api() -> JiraApi:
    return JiraApi()


def test_show_fetches_and_stores_a_ticket_not_stored(session: Session, jira_api: JiraApi) -> None:
    # GIVEN
    cut = _service(session, jira_api)

    # WHEN
    ticket = cut.show('SAT-7')

    # THEN
    assert ticket
    assert ticket.title == 'Retry failed meteo imports'
    stored = TicketRepository(session).get('jira', 'SAT-7')
    assert stored
    assert stored.ticket == ticket
    assert abs(stored.fetched_at - datetime.now(UTC)) < timedelta(seconds=1)


@pytest.mark.parametrize(('fetched_ago', 'force_fetch', 'fetches'), [
    pytest.param(WINDOW / 2, False, False, id='within-window'),
    pytest.param(WINDOW * 2, False, True, id='after-window'),
    pytest.param(WINDOW / 2, True, True, id='forced-within-window'),
])
def test_show_fetches_a_stored_ticket_only_after_the_window_or_when_forced(
    session: Session, jira_api: JiraApi, fetched_ago: timedelta, force_fetch: bool, fetches: bool
) -> None:
    # GIVEN SAT-7 stored fetched_ago
    _save_in_local_copy(session, STORED_SAT_7, datetime.now(UTC) - fetched_ago)
    cut = _service(session, jira_api)

    # WHEN
    ticket = cut.show('SAT-7', force_fetch=force_fetch)

    # THEN
    assert ticket
    assert (ticket != STORED_SAT_7) is fetches
    assert bool(jira_api.requests) is fetches


def test_show_fetches_a_ticket_known_only_through_another(session: Session, jira_api: JiraApi) -> None:
    # GIVEN SAT-7 just fetched, which mentions its parent SAT-2
    cut = _service(session, jira_api)
    cut.show('SAT-7')
    jira_api.requests.clear()

    # WHEN
    cut.show('SAT-2')

    # THEN
    assert [request.url.path for request in jira_api.requests] == ['/rest/api/3/issue/SAT-2']


def test_show_answers_from_the_local_copy_with_a_warning_when_unreachable(
    session: Session, jira_api: JiraApi, caplog: pytest.LogCaptureFixture
) -> None:
    # GIVEN SAT-7 stored on 2026-10-30, and Jira unreachable
    _save_in_local_copy(session, STORED_SAT_7, datetime(2026, 10, 30, 9, tzinfo=UTC))
    jira_api.reachable = False
    cut = _service(session, jira_api)

    # WHEN
    ticket = cut.show('SAT-7')

    # THEN
    assert ticket
    assert ticket == STORED_SAT_7
    assert caplog.messages == ['jira unreachable, SAT-7 is a local copy from 2026-10-30']


def test_show_raises_when_unreachable_and_not_stored(session: Session, jira_api: JiraApi) -> None:
    # GIVEN
    jira_api.reachable = False
    cut = _service(session, jira_api)

    # WHEN / THEN
    with pytest.raises(SourceUnreachable, match='jira unreachable, and SAT-7 has no local copy'):
        cut.show('SAT-7')


def test_show_deletes_the_local_copy_of_a_ticket_gone_from_the_source(session: Session, jira_api: JiraApi) -> None:
    # GIVEN SAT-9 stored long ago, and gone from Jira since
    _save_in_local_copy(session, new_ticket(key='SAT-9'), datetime.now(UTC) - WINDOW * 2)
    cut = _service(session, jira_api)

    # WHEN
    ticket = cut.show('SAT-9')

    # THEN
    assert ticket is None
    assert TicketRepository(session).get('jira', 'SAT-9') is None


@pytest.mark.parametrize(('key', 'git_repository', 'source'), [
    pytest.param('other:SAT-7', None, 'other', id='qualified'),
    pytest.param('WEB-7', None, 'jira', id='prefix-in-one-source'),
    pytest.param('SAT-7', 'sat-meteo', 'other', id='tie-broken-by-git-repository'),
    pytest.param('SAT-7', 'sat', 'jira', id='tie-broken-by-another-git-repository'),
])
def test_show_resolves_the_key_to_its_source(
    session: Session, key: str, git_repository: str | None, source: str
) -> None:
    # GIVEN every source stored with a ticket of every space, so nothing is fetched
    for slug in ('jira', 'other'):
        for ticket_key in ('SAT-7', 'WEB-7'):
            stored = new_ticket(source=slug, key=ticket_key, space=ticket_key[:3])
            _save_in_local_copy(session, stored, datetime.now(UTC))
    cut = TicketsService(TWO_JIRAS, session, (), git_repository)

    # WHEN
    ticket = cut.show(key)

    # THEN
    assert ticket
    assert ticket.source == source


@pytest.mark.parametrize(('key', 'message'), [
    pytest.param('SAT-7', 'SAT-7 is in several sources, use one of: jira:SAT-7, other:SAT-7', id='ambiguous'),
    pytest.param('OPS-1', 'OPS-1 is in several sources, use one of: jira:OPS-1, other:OPS-1', id='prefix-no-project'),
    pytest.param('SAT', 'SAT is not a ticket key, such as SAT-7', id='not-a-key'),
])
def test_show_raises_for_a_key_that_doesnt_resolve(session: Session, key: str, message: str) -> None:
    # GIVEN no current git repository to break ties
    cut = TicketsService(TWO_JIRAS, session, (), None)

    # WHEN / THEN
    with pytest.raises(KeyNotResolved, match=f'^{message}$'):
        cut.show(key)


def test_show_gives_a_prefix_in_no_project_to_the_only_ticket_source(session: Session) -> None:
    # GIVEN jira as the only ticket source, with OPS-1 stored
    _save_in_local_copy(session, new_ticket(key='OPS-1', space='OPS'), datetime.now(UTC))
    cut = TicketsService(CONFIG, session, (), None)

    # WHEN
    ticket = cut.show('OPS-1')

    # THEN
    assert ticket == new_ticket(key='OPS-1', space='OPS')


def test_sync_stores_the_tickets_of_the_projects_spaces(session: Session, jira_api: JiraApi) -> None:
    # GIVEN the sat project, on the SAT space
    cut = _service(session, jira_api)

    # WHEN
    cut.sync()

    # THEN
    sat_7 = TicketRepository(session).get('jira', 'SAT-7')
    sat_8 = TicketRepository(session).get('jira', 'SAT-8')
    assert sat_7 and sat_8
    assert [child.key for child in sat_7.ticket.children] == ['SAT-8', 'SAT-10']
    assert abs(sat_8.fetched_at - datetime.now(UTC)) < timedelta(seconds=1)


@pytest.mark.parametrize(('synced_ago', 'force_fetch', 'fetches'), [
    pytest.param(WINDOW / 2, False, False, id='within-window'),
    pytest.param(WINDOW * 2, False, True, id='after-window'),
    pytest.param(WINDOW / 2, True, True, id='forced-within-window'),
])
def test_sync_fetches_a_space_only_after_the_window_or_when_forced(
    session: Session, jira_api: JiraApi, synced_ago: timedelta, force_fetch: bool, fetches: bool
) -> None:
    # GIVEN SAT synced synced_ago
    TicketSpaceSyncRepository(session).save('jira', 'SAT', datetime.now(UTC) - synced_ago)
    cut = _service(session, jira_api)

    # WHEN
    cut.sync(force_fetch=force_fetch)

    # THEN
    assert bool(jira_api.requests) is fetches


@pytest.mark.parametrize(('force_fetch', 'asks_since_last_sync', 'sat_99_kept'), [
    pytest.param(False, True, True, id='changes-since-last-sync'),
    pytest.param(True, False, False, id='forced-rereads-everything'),
])
def test_sync_after_a_first_sync_fetches_what_changed_unless_forced(
    session: Session, jira_api: JiraApi, force_fetch: bool, asks_since_last_sync: bool, sat_99_kept: bool
) -> None:
    # GIVEN SAT synced long ago, with SAT-99 stored, which Jira no longer has
    long_ago = datetime.now(UTC) - WINDOW * 2
    TicketSpaceSyncRepository(session).save('jira', 'SAT', long_ago)
    _save_in_local_copy(session, new_ticket(key='SAT-99', space='SAT'), long_ago)
    cut = _service(session, jira_api)

    # WHEN
    cut.sync(force_fetch=force_fetch)

    # THEN
    assert ('updated >=' in json.loads(jira_api.requests[0].content)['jql']) is asks_since_last_sync
    assert bool(TicketRepository(session).get('jira', 'SAT-99')) is sat_99_kept


def test_sync_warns_when_a_source_is_unreachable(session: Session, jira_api: JiraApi, caplog: pytest.LogCaptureFixture):
    # GIVEN
    jira_api.reachable = False
    cut = _service(session, jira_api)

    # WHEN
    cut.sync()

    # THEN
    assert caplog.messages == ['jira unreachable, SAT was never synced']


@pytest.mark.parametrize(('filters', 'keys'), [
    pytest.param({'project_slugs': ['sat']}, ['SAT-7', 'SAT-8', 'SAT-10'], id='project'),
    pytest.param({'statuses': ['To do', 'Done']}, ['SAT-8', 'SAT-10'], id='any-of-several-statuses'),
    pytest.param({'sprint_name': 'All Sprint 1'}, ['SAT-7'], id='sprint-by-name'),
    pytest.param({'sprint_name': CURRENT_SPRINT}, ['SAT-7'], id='current-sprint'),
    pytest.param({'assignee_slug': 'ana'}, ['SAT-7'], id='assignee'),
    pytest.param({'assignee_slug': 'bob'}, [], id='assignee-with-no-identity-in-the-source'),
    pytest.param({'updated_since': datetime(2026, 10, 29, tzinfo=UTC)}, ['SAT-8', 'SAT-10'], id='updated-since'),
    pytest.param({'statuses': ['Done'], 'assignee_slug': 'ana'}, [], id='every-filter-must-match'),
])
def test_list_tickets_syncs_and_lists_the_full_tickets_matching_every_filter(
    session: Session, jira_api: JiraApi, filters: dict[str, Any], keys: list[str]
) -> None:
    # GIVEN the SAT space, where SAT-7 is Ana's, and SAT-2 only known as its parent
    cut = _service(session, jira_api)

    # WHEN
    tickets = cut.list_tickets(**filters)

    # THEN
    assert [ticket.key for ticket in tickets] == keys


def test_list_tickets_answers_from_the_local_copy_when_unreachable(
    session: Session, jira_api: JiraApi, caplog: pytest.LogCaptureFixture
) -> None:
    # GIVEN SAT listed once, and Jira unreachable since
    cut = _service(session, jira_api)
    cut.list_tickets(project_slugs=['sat'])
    jira_api.reachable = False

    # WHEN
    tickets = cut.list_tickets(project_slugs=['sat'], force_fetch=True)

    # THEN
    assert [ticket.key for ticket in tickets] == ['SAT-7', 'SAT-8', 'SAT-10']
    assert caplog.messages == [f'jira unreachable, SAT is a local copy from {datetime.now(UTC):%Y-%m-%d}']


def _service(session: Session, jira_api: JiraApi) -> TicketsService:
    client = JiraClient(JIRA_CONFIG.url, lambda: ('ana@example.com', 'token'), transport=httpx.MockTransport(jira_api))
    return TicketsService(CONFIG, session, (JiraSource(JIRA_CONFIG, client),), None)


def _save_in_local_copy(session: Session, ticket: Ticket, fetched_at: datetime) -> None:
    TicketRepository(session).save(ticket, fetched_at)
