from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

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

