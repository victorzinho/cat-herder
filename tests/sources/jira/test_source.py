import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

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
from cat_herder.sources.errors import SourceError, SourceUnreachable, TicketNotFound, WriteIncomplete
from cat_herder.sources.jira.client import JiraClient
from cat_herder.sources.jira.source import JiraSource
from cat_herder.sources.ticket_source import TicketSource
from tests.dates import parse
from tests.factories import new_change, new_link, new_sprint, new_ticket
from tests.jira_api import JIRA_CONFIG, JiraApi, jira_api_with_sat

ANA_EDIT = parse('2026-10-21T08:00:00Z')
VICTOR_EDIT = parse('2026-10-22T07:30:00Z')
AUTOMATION_EDIT = parse('2026-10-23T06:00:00Z')


def test_fetch_ticket_maps_the_issue_with_every_page_of_what_it_mentions() -> None:
    # GIVEN Jira answers with SAT-7, its comments and children in two pages each, and its changelog
    cut = _source(jira_api_with_sat)

    # WHEN
    ticket = cut.fetch_ticket('SAT-7')

    # THEN
    assert ticket == Ticket(
        source='jira',
        key='SAT-7',
        space='SAT',
        title='Retry failed meteo imports',
        type='Task',
        status='In progress',
        created=parse('2026-10-12T09:30:00Z'),
        updated=parse('2026-10-28T16:05:00Z'),
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
                start=parse('2026-10-20T08:00:00Z'),
                planned_end=parse('2026-11-03T12:00:00Z'),
                actual_end=parse('2026-11-03T15:00:00Z'),
            ),
            Sprint(
                source='jira',
                id='43',
                name='All Sprint 2',
                state=SprintState.IN_PROGRESS,
                start=parse('2026-11-03T16:00:00Z'),
                planned_end=parse('2026-11-17T12:00:00Z'),
            ),
        ),
        custom_fields={'size': '🔥', 'team': 'meteo-team'},
        comments=(
            Comment(
                author='account-ana',
                created=parse('2026-10-20T11:00:00Z'),
                body='Reproduced it with a 30 s timeout.',
            ),
            Comment(
                author=None,
                created=parse('2026-10-21T07:15:00Z'),
                body='Retries scheduled by automation.',
            ),
        ),
        attachments=(
            Attachment(
                id='501', filename='trace.log', size=48213, created=parse('2026-10-20T11:02:00Z')
            ),
        ),
        parent='SAT-2',
        children=(
            TicketSummary(source='jira', key='SAT-8', title='Add import metrics', status='To do', type='Task'),
            TicketSummary(source='jira', key='SAT-10', title='Alert on failed imports', status='Done', type='Sub-task'),
        ),
        links=(
            Link(from_key='SAT-7', relation='blocks', to_key='SAT-9'),
            Link(from_key='SAT-4', relation='blocks', to_key='SAT-7'),
        ),
        related_summaries=(
            TicketSummary(source='jira', key='SAT-2', title='Meteo pipeline', status='In progress', type='Epic'),
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
    cut = _source(jira_api)

    # WHEN
    with pytest.raises(Exception) as raised:
        cut.fetch_ticket('SAT-7')

    # THEN
    assert raised.type is expected_error


def test_fetch_ticket_raises_for_a_custom_field_with_several_values() -> None:
    # GIVEN a custom field configured on Jira's multi-select customfield_10050
    cut = _source(jira_api_with_sat, replace(JIRA_CONFIG, custom_fields={'channels': 'customfield_10050'}))

    # WHEN / THEN
    with pytest.raises(SourceError, match='Custom field channels holds'):
        cut.fetch_ticket('SAT-7')


def test_fetch_tickets_maps_the_spaces_tickets_as_fetch_ticket_does() -> None:
    # GIVEN the SAT space, with SAT-7 and its children SAT-8 and SAT-10, and SAT-7 fetched alone
    cut = _source(jira_api_with_sat)
    sat_7 = cut.fetch_ticket('SAT-7')

    # WHEN
    tickets = cut.fetch_tickets('SAT', None)

    # THEN
    assert [ticket.key for ticket in tickets] == ['SAT-7', 'SAT-8', 'SAT-10']
    assert tickets[0] == sat_7
    assert [ticket.parent for ticket in tickets] == ['SAT-2', 'SAT-7', 'SAT-7']


def test_fetch_tickets_asks_only_for_tickets_updated_since() -> None:
    # GIVEN a last sync ten minutes ago
    jira_api = JiraApi()
    cut = _source(jira_api)
    updated_since = datetime.now(UTC) - timedelta(minutes=10)

    # WHEN
    cut.fetch_tickets('SAT', updated_since)

    # THEN a minute of margin, and possibly another one passing during the test
    jql = json.loads(jira_api.requests[0].content)['jql']
    assert re.fullmatch(r'project = "SAT" AND updated >= -1[12]m ORDER BY key', jql)


def test_create_ticket_creates_it_with_its_fields_then_writes_its_links_and_status() -> None:
    # GIVEN a ticket for SAT, with links whose empty end stands for it
    jira_api = JiraApi()
    cut = _source(jira_api)
    ticket = new_ticket(
        key='',
        title='Alert on retries',
        status='Done',
        labels=('backend',),
        custom_fields={'size': '🕯️'},
        parent='SAT-7',
        links=(
            new_link(from_key='', relation='blocks', to_key='SAT-9'),
            new_link(from_key='SAT-4', relation='relates to', to_key=''),
        ),
    )

    # WHEN
    key = cut.create_ticket(ticket)

    # THEN Jira sets the rest
    assert key == 'SAT-11'
    assert jira_api.writes() == [
        ('POST', 'issue', {'fields': {
            'project': {'key': 'SAT'},
            'summary': 'Alert on retries',
            'issuetype': {'name': 'Task'},
            'customfield_10043': {'value': '🕯️'},
            'parent': {'key': 'SAT-7'},
            'labels': ['backend'],
        }}),
        ('POST', 'issueLink', {
            'type': {'name': 'Blocks'}, 'inwardIssue': {'key': 'SAT-11'}, 'outwardIssue': {'key': 'SAT-9'}
        }),
        ('POST', 'issueLink', {
            'type': {'name': 'Relates'}, 'inwardIssue': {'key': 'SAT-4'}, 'outwardIssue': {'key': 'SAT-11'}
        }),
        ('POST', 'issue/SAT-11/transitions', {'transition': {'id': '31'}}),
    ]


@pytest.mark.parametrize(('fields', 'message'), [
    pytest.param({'type': 'Story'}, 'SAT in jira has no type Story, only: Task, Bug', id='type'),
    pytest.param({'title': ''}, 'jira needs a title and a type to create a ticket', id='title'),
    pytest.param(
        {'links': (new_link(from_key='', relation='clones', to_key='SAT-9'),)},
        'jira has no relation clones, only: blocks, relates to',
        id='relation',
    ),
    pytest.param({'custom_fields': {'size': '🌋'}}, "size can't be 🌋, only: 🔥, 🕯️", id='option'),
    pytest.param(
        {'custom_fields': {'colour': 'red'}}, 'jira has no custom field colour in the config', id='custom-field'
    ),
])
def test_create_ticket_raises_without_creating_it_for_a_value_jira_doesnt_take(
    fields: dict[str, Any], message: str
) -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)

    # WHEN
    with pytest.raises(SourceError, match=re.escape(message)):
        cut.create_ticket(new_ticket(key='', **fields))

    # THEN
    assert jira_api.writes() == []


def test_create_ticket_reports_it_was_created_when_a_later_write_fails() -> None:
    # GIVEN Jira rejecting new links
    jira_api = JiraApi()
    jira_api.rejecting.add('POST issueLink')
    cut = _source(jira_api)
    ticket = new_ticket(key='', status='Done', links=(new_link(from_key='', relation='blocks', to_key='SAT-9'),))

    # WHEN
    with pytest.raises(WriteIncomplete) as raised:
        cut.create_ticket(ticket)

    # THEN
    assert str(raised.value).startswith(
        'SAT-11 got created, and not link SAT-11 blocks SAT-9, status Done: POST '
    )


def test_update_ticket_writes_the_fields_in_one_call_then_the_links_and_the_status_last() -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)
    sat_7 = cut.fetch_ticket('SAT-7')
    edited = replace(
        sat_7,
        title='Retry meteo imports',
        type='Bug',
        status='Done',
        assignee='account-bob',
        points=3,
        estimated_hours=1.5,
        custom_fields={'size': '🕯️', 'team': None},
        parent='SAT-3',
        sprints=(new_sprint(id='42', state=SprintState.ENDED), new_sprint(id='44', state=SprintState.NOT_STARTED)),
        labels=('backend', 'meteo'),
        components=(),
        description='**Retry** them',
        links=(
            new_link(from_key='SAT-7', relation='blocks', to_key='SAT-9'),
            new_link(from_key='SAT-7', relation='relates to', to_key='SAT-10'),
        ),
    )

    # WHEN
    cut.update_ticket(edited)

    # THEN
    description = {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Retry', 'marks': [{'type': 'strong'}]}, {'type': 'text', 'text': ' them'},
    ]}]}
    assert jira_api.writes() == [
        ('PUT', 'issue/SAT-7', {
            'fields': {
                'summary': 'Retry meteo imports',
                'issuetype': {'name': 'Bug'},
                'assignee': {'accountId': 'account-bob'},
                'customfield_10035': 3,
                'customfield_10043': {'value': '🕯️'},
                'customfield_10044': None,
                'parent': {'key': 'SAT-3'},
                'customfield_10020': 44,
                'labels': ['backend', 'meteo'],
                'components': [],
                'description': description,
            },
            'update': {'timetracking': [{'edit': {'originalEstimate': '90m'}}]},
        }),
        ('POST', 'issueLink', {
            'type': {'name': 'Relates'}, 'inwardIssue': {'key': 'SAT-7'}, 'outwardIssue': {'key': 'SAT-10'}
        }),
        ('DELETE', 'issueLink/10062', None),
        ('POST', 'issue/SAT-7/transitions', {'transition': {'id': '31'}}),
    ]


def test_update_ticket_clears_fields_set_to_none() -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)
    sat_7 = cut.fetch_ticket('SAT-7')
    edited = replace(
        sat_7,
        assignee=None,
        points=None,
        estimated_hours=None,
        parent=None,
        sprints=(new_sprint(id='42', state=SprintState.ENDED),),
        description=None,
    )

    # WHEN
    cut.update_ticket(edited)

    # THEN
    assert jira_api.writes() == [
        ('PUT', 'issue/SAT-7', {
            'fields': {
                'assignee': None,
                'customfield_10035': None,
                'parent': None,
                'customfield_10020': None,
                'description': None,
            },
            'update': {'timetracking': [{'edit': {'originalEstimate': ''}}]},
        }),
    ]


@pytest.mark.parametrize(('edits', 'message'), [
    pytest.param({'status': 'Blocked'}, "SAT-7 can't go to Blocked in jira, only to: Done", id='status'),
    pytest.param(
        {'links': (new_link(from_key='SAT-7', relation='clones', to_key='SAT-9'),)},
        'jira has no relation clones, only: blocks, relates to',
        id='relation',
    ),
    pytest.param(
        {'custom_fields': {'size': '🌋', 'team': 'meteo-team'}}, "size can't be 🌋, only: 🔥, 🕯️", id='option'
    ),
    pytest.param(
        {'sprints': (
            new_sprint(id='42', state=SprintState.ENDED),
            new_sprint(id='43', state=SprintState.IN_PROGRESS),
            new_sprint(id='44', state=SprintState.NOT_STARTED),
        )},
        "jira holds a ticket in one sprint that hasn't ended at most",
        id='two-sprints-not-ended',
    ),
    pytest.param(
        {'sprints': (new_sprint(id='43', state=SprintState.IN_PROGRESS),)},
        "jira can't add or remove ended sprints",
        id='ended-sprint',
    ),
])
def test_update_ticket_raises_without_writing_for_a_value_jira_doesnt_take(edits: dict[str, Any], message: str) -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)
    sat_7 = cut.fetch_ticket('SAT-7')

    # WHEN
    with pytest.raises(SourceError, match=re.escape(message)):
        cut.update_ticket(replace(sat_7, **edits))

    # THEN
    assert jira_api.writes() == []


def test_update_ticket_reports_what_was_and_wasnt_written_when_a_write_fails() -> None:
    # GIVEN Jira rejecting new links
    jira_api = JiraApi()
    jira_api.rejecting.add('POST issueLink')
    cut = _source(jira_api)
    sat_7 = cut.fetch_ticket('SAT-7')
    edited = replace(
        sat_7,
        title='Retry meteo imports',
        labels=(),
        status='Done',
        links=(new_link(from_key='SAT-7', relation='relates to', to_key='SAT-10'),),
    )

    # WHEN
    with pytest.raises(WriteIncomplete) as raised:
        cut.update_ticket(edited)

    # THEN
    assert str(raised.value).startswith(
        'SAT-7 got title, labels, and not link SAT-7 relates to SAT-10, unlink SAT-4 blocks SAT-7, '
        'unlink SAT-7 blocks SAT-9, status Done: POST '
    )
    assert [write[0] for write in jira_api.writes()] == ['PUT', 'POST']


def test_add_comment_posts_the_markdown_as_adf() -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)

    # WHEN
    cut.add_comment('SAT-7', 'Done in `main`')

    # THEN
    body = {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Done in '}, {'type': 'text', 'text': 'main', 'marks': [{'type': 'code'}]},
    ]}]}
    assert jira_api.writes() == [('POST', 'issue/SAT-7/comment', {'body': body})]


def test_update_ticket_writes_nothing_when_nothing_differs() -> None:
    # GIVEN
    jira_api = JiraApi()
    cut = _source(jira_api)

    # WHEN
    cut.update_ticket(cut.fetch_ticket('SAT-7'))

    # THEN
    assert jira_api.writes() == []


def test_writes_raise_ticket_not_found_for_a_ticket_jira_doesnt_have() -> None:
    # GIVEN
    cut = _source(JiraApi())

    # WHEN / THEN
    with pytest.raises(TicketNotFound, match='jira has no ticket SAT-9'):
        cut.update_ticket(new_ticket(key='SAT-9'))
    with pytest.raises(TicketNotFound, match='jira has no ticket SAT-9'):
        cut.add_comment('SAT-9', 'Gone')


def _source(
    jira_api: Callable[[httpx.Request], httpx.Response], config: JiraSourceConfig = JIRA_CONFIG
) -> TicketSource:
    client = JiraClient(config.url, lambda: ('ana@example.com', 'token'), transport=httpx.MockTransport(jira_api))
    return JiraSource(config, client)

