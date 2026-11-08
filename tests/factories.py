from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from cat_herder.domain.config import Access, EnvCredential, JiraSourceConfig, TogglSourceConfig
from cat_herder.domain.ticket import (
    Attachment,
    Change,
    Comment,
    Link,
    Sprint,
    SprintState,
    Ticket,
    TicketSummary,
)
from cat_herder.domain.time_entry import TimeEntry
from tests.dates import parse

# Valid defaults. A test sets every field it asserts on or depends on, and leaves the rest to these.
_DATE = datetime(2026, 10, 1, 9, tzinfo=UTC)
_SPRINT = Sprint(
    source='jira',
    id='1',
    name='Sprint 1',
    state=SprintState.IN_PROGRESS,
    start=_DATE,
    planned_end=datetime(2026, 10, 15, 9, tzinfo=UTC),
)
_COMMENT = Comment(author='account-ana', created=_DATE, body='A comment')
_ATTACHMENT = Attachment(id='1', filename='notes.txt', size=1024, created=_DATE)
_TICKET = Ticket(
    source='jira',
    key='SAT-1',
    space='SAT',
    title='A ticket',
    type='Task',
    status='To do',
    created=_DATE,
    updated=_DATE,
)
_TICKET_SUMMARY = TicketSummary(source='jira', key='SAT-2', title='Another ticket', status='To do', type='Task')
_LINK = Link(from_key='SAT-1', relation='blocks', to_key='SAT-2')
_JIRA_SOURCE_CONFIG = JiraSourceConfig(
    slug='jira',
    access=Access.FULL,
    fetch_window_seconds=60,
    done_statuses=('Done',),
    url='https://example.atlassian.net',
    email=EnvCredential(name='JIRA_EMAIL'),
    token=EnvCredential(name='JIRA_TOKEN'),
)
_TOGGL_SOURCE_CONFIG = TogglSourceConfig(
    slug='toggl',
    access=Access.READ_ONLY,
    fetch_window_seconds=900,
    workspace=1,
    history_from=parse('2026-01-01T00:00:00Z'),
    token=EnvCredential(name='TOGGL_TOKEN'),
)
_TIME_ENTRY = TimeEntry(
    source='toggl',
    id='1',
    space='SAT',
    person='456',
    description='Some work',
    start=_DATE,
    end=_DATE + timedelta(hours=1),
)
_CHANGE = Change(field='status', author='account-ana', before='To do', after='In progress', date=_DATE)


def new_sprint(**overrides: Any) -> Sprint:
    return replace(_SPRINT, **overrides)


def new_comment(**overrides: Any) -> Comment:
    return replace(_COMMENT, **overrides)


def new_attachment(**overrides: Any) -> Attachment:
    return replace(_ATTACHMENT, **overrides)


def new_ticket(**overrides: Any) -> Ticket:
    return replace(_TICKET, **overrides)


def new_ticket_summary(**overrides: Any) -> TicketSummary:
    return replace(_TICKET_SUMMARY, **overrides)


def new_link(**overrides: Any) -> Link:
    return replace(_LINK, **overrides)


def new_change(**overrides: Any) -> Change:
    return replace(_CHANGE, **overrides)


def new_jira_source_config(**overrides: Any) -> JiraSourceConfig:
    return replace(_JIRA_SOURCE_CONFIG, **overrides)


def new_toggl_source_config(**overrides: Any) -> TogglSourceConfig:
    return replace(_TOGGL_SOURCE_CONFIG, **overrides)


def new_time_entry(**overrides: Any) -> TimeEntry:
    return replace(_TIME_ENTRY, **overrides)
