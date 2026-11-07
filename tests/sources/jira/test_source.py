from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from cat_herder.domain.config import JiraSourceConfig
from cat_herder.domain.ticket import (
    Attachment,
    Comment,
    Link,
    Sprint,
    SprintState,
    Ticket,
    TicketSummary,
)
from cat_herder.sources.errors import SourceError, SourceUnreachable, TicketNotFound
from cat_herder.sources.jira.client import JiraClient
from cat_herder.sources.jira.source import JiraSource
from cat_herder.sources.ticket_source import TicketSource
from tests.factories import new_change
from tests.jira_api import JIRA_CONFIG, jira_api_with_sat_7

ANA_EDIT = datetime(2026, 10, 21, 8, tzinfo=UTC)
VICTOR_EDIT = datetime(2026, 10, 22, 7, 30, tzinfo=UTC)
AUTOMATION_EDIT = datetime(2026, 10, 23, 6, tzinfo=UTC)


def test_fetch_ticket_maps_the_issue_with_every_page_of_what_it_mentions() -> None:
    # GIVEN Jira answers with SAT-7, its comments and children in two pages each, and its changelog
    source = _source(jira_api_with_sat_7)

    # WHEN
    ticket = source.fetch_ticket('SAT-7')

    # THEN
    assert ticket == Ticket(
        source='jira',
        key='SAT-7',
        space='SAT',
        title='Retry failed meteo imports',
        type='Task',
        status='In progress',
        created=datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
        updated=datetime(2026, 10, 28, 16, 5, tzinfo=UTC),
        description='The import fails **silently** when the provider times out.',
        labels=('backend',),
        components=('import',),
        assignee='account-ana',
        points=5,
        estimated_hours=5,
        sprints=(
            Sprint(
                source='jira',
                id='42',
                name='All Sprint 1',
                state=SprintState.ENDED,
                start=datetime(2026, 10, 20, 8, tzinfo=UTC),
                planned_end=datetime(2026, 11, 3, 12, tzinfo=UTC),
                actual_end=datetime(2026, 11, 3, 15, tzinfo=UTC),
            ),
            Sprint(
                source='jira',
                id='43',
                name='All Sprint 2',
                state=SprintState.IN_PROGRESS,
                start=datetime(2026, 11, 3, 16, tzinfo=UTC),
                planned_end=datetime(2026, 11, 17, 12, tzinfo=UTC),
            ),
        ),
        custom_fields={'size': '🔥', 'team': 'meteo-team'},
        comments=(
            Comment(
                author='account-ana',
                created=datetime(2026, 10, 20, 11, tzinfo=UTC),
                body='Reproduced it with a 30 s timeout.',
            ),
            Comment(
                author=None,
                created=datetime(2026, 10, 21, 7, 15, tzinfo=UTC),
                body='Retries scheduled by automation.',
            ),
        ),
        attachments=(
            Attachment(
                id='501', filename='trace.log', size=48213, created=datetime(2026, 10, 20, 11, 2, tzinfo=UTC)
            ),
        ),
        parent=TicketSummary(source='jira', key='SAT-2', title='Meteo pipeline', status='In progress', type='Epic'),
        children=(
            TicketSummary(source='jira', key='SAT-8', title='Add import metrics', status='To do', type='Task'),
            TicketSummary(source='jira', key='SAT-10', title='Alert on failed imports', status='Done', type='Sub-task'),
        ),
        links=(
            Link(from_key='SAT-7', relation='blocks', to_key='SAT-9'),
            Link(from_key='SAT-4', relation='blocks', to_key='SAT-7'),
        ),
        linked=(
            TicketSummary(source='jira', key='SAT-9', title='Publish meteo layer', status='To do', type='Task'),
            TicketSummary(source='jira', key='SAT-4', title='Rotate API keys', status='Resolved', type='Task'),
        ),
        changes=(
            new_change(field='status', author='account-ana', before='To do', after='In progress', date=ANA_EDIT),
            new_change(field='assignee', author='account-ana', before=None, after='account-ana', date=ANA_EDIT),
            new_change(field='estimated_hours', author='account-victor', before='10', after='5', date=VICTOR_EDIT),
            new_change(field='points', author='account-victor', before='10', after='5', date=VICTOR_EDIT),
            new_change(field='sprints', author='account-victor', before=None, after='All Sprint 1', date=VICTOR_EDIT),
            new_change(field='custom_fields.size', author='account-victor', before='🌋', after='🔥', date=VICTOR_EDIT),
            new_change(field='parent', author='account-victor', before=None, after='SAT-2', date=VICTOR_EDIT),
            new_change(
                field='links',
                author='account-victor',
                before=None,
                after='This work item blocks SAT-9',
                date=VICTOR_EDIT,
            ),
            new_change(
                field='title',
                author=None,
                before='Retry meteo imports',
                after='Retry failed meteo imports',
                date=AUTOMATION_EDIT,
            ),
        ),
    )


def _jira_api_answering(status: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={'errorMessages': ['Rejected by Jira'], 'errors': {}})

    return handler


def _jira_api_raising(error: type[httpx.TransportError]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error('Failed', request=request)

    return handler


@pytest.mark.parametrize(
    ('jira_api', 'expected_error'),
    [
        pytest.param(_jira_api_answering(404), TicketNotFound, id='not-found'),
        pytest.param(_jira_api_answering(401), SourceError, id='http-error'),
        pytest.param(_jira_api_raising(httpx.ConnectError), SourceUnreachable, id='connect-error'),
        pytest.param(_jira_api_raising(httpx.ConnectTimeout), SourceUnreachable, id='connect-timeout'),
        pytest.param(_jira_api_raising(httpx.ReadTimeout), SourceError, id='read-timeout'),
    ],
)
def test_fetch_ticket_raises_source_exceptions(
    jira_api: Callable[[httpx.Request], httpx.Response], expected_error: type[Exception]
) -> None:
    # GIVEN
    source = _source(jira_api)

    # WHEN
    with pytest.raises(Exception) as raised:
        source.fetch_ticket('SAT-7')

    # THEN
    assert raised.type is expected_error


def test_fetch_ticket_raises_for_a_custom_field_with_several_values() -> None:
    # GIVEN a custom field configured on Jira's multi-select customfield_10050
    source = _source(jira_api_with_sat_7, replace(JIRA_CONFIG, custom_fields={'channels': 'customfield_10050'}))

    # WHEN / THEN
    with pytest.raises(SourceError, match='Custom field channels holds'):
        source.fetch_ticket('SAT-7')


def _source(
    jira_api: Callable[[httpx.Request], httpx.Response], config: JiraSourceConfig = JIRA_CONFIG
) -> TicketSource:
    client = JiraClient(config.url, lambda: ('ana@example.com', 'token'), transport=httpx.MockTransport(jira_api))
    return JiraSource(config, client)

