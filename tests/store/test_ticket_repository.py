from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from cat_herder.domain.ticket import SprintState
from cat_herder.store.database import database_session, open_database
from cat_herder.store.ticket_repository import StoredTicket, TicketRepository
from tests.factories import (
    new_attachment,
    new_change,
    new_comment,
    new_link,
    new_sprint,
    new_ticket,
    new_ticket_summary,
)

FETCHED_AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return open_database(tmp_path)


@pytest.fixture
def session(engine: Engine) -> Generator[Session]:
    with database_session(engine) as session:
        yield session


def test_get_returns_the_saved_ticket_with_what_it_mentions(session: Session) -> None:
    # GIVEN a ticket with every field set, and everything it can mention
    repository = TicketRepository(session)
    ticket = new_ticket(
        key='SAT-7',
        space='SAT',
        title='Retry failed meteo imports',
        type='Task',
        status='In progress',
        created=datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
        updated=datetime(2026, 10, 28, 16, 5, tzinfo=UTC),
        description='The import fails silently when the provider times out...',
        labels=('backend',),
        components=('import',),
        assignee='account-ana',
        points=5,
        estimated_hours=5,
        sprints=(
            new_sprint(
                id='42',
                name='All Sprint 1',
                state=SprintState.ENDED,
                start=datetime(2026, 10, 20, tzinfo=UTC),
                planned_end=datetime(2026, 11, 3, tzinfo=UTC),
                actual_end=datetime(2026, 11, 4, tzinfo=UTC),
            ),
        ),
        custom_fields={'size': '🔥', 'reach': 3},
        comments=(
            new_comment(author='account-ana', created=datetime(2026, 10, 20, 11, tzinfo=UTC), body='Reproduced'),
            new_comment(author=None, created=datetime(2026, 10, 21, 8, tzinfo=UTC), body='Retried'),
        ),
        attachments=(
            new_attachment(
                id='501', filename='trace.log', size=48213, created=datetime(2026, 10, 20, 11, 2, tzinfo=UTC)
            ),
        ),
        parent=new_ticket_summary(key='SAT-2', title='Meteo pipeline', status='In progress', type='Epic'),
        children=(new_ticket_summary(key='SAT-8', title='Add import metrics', status='To do', type='Task'),),
        links=(
            new_link(from_key='SAT-7', relation='blocks', to_key='SAT-9'),
            new_link(from_key='SAT-4', relation='blocks', to_key='SAT-7'),
        ),
        linked=(
            new_ticket_summary(key='SAT-9', title='Publish meteo layer', status='To do', type='Task'),
            new_ticket_summary(key='SAT-4', title='Rotate API keys', status='Resolved', type='Task'),
        ),
        changes=(
            new_change(
                field='status',
                author='account-ana',
                before='To do',
                after='In progress',
                date=datetime(2026, 10, 21, 8, tzinfo=UTC),
            ),
            new_change(
                field='assignee',
                author=None,
                before=None,
                after='account-ana',
                date=datetime(2026, 10, 21, 9, tzinfo=UTC),
            ),
        ),
    )
    repository.save(ticket, FETCHED_AT)

    # WHEN
    stored = repository.get('jira', 'SAT-7')

    # THEN
    assert stored == StoredTicket(ticket=ticket, fetched_at=FETCHED_AT)


def test_get_treats_a_ticket_known_only_through_another_as_missing(session: Session) -> None:
    # GIVEN SAT-9 is only known through a link from SAT-7
    repository = TicketRepository(session)
    ticket = new_ticket(
        key='SAT-7',
        links=(new_link(from_key='SAT-7', to_key='SAT-9'),),
        linked=(new_ticket_summary(key='SAT-9'),),
    )
    repository.save(ticket, FETCHED_AT)

    # WHEN / THEN
    assert repository.get('jira', 'SAT-9') is None


def test_get_returns_the_children_in_key_order(session: Session) -> None:
    # GIVEN SAT-7 with children SAT-10 and SAT-8
    repository = TicketRepository(session)
    children = (new_ticket_summary(key='SAT-8'), new_ticket_summary(key='SAT-10'))
    repository.save(new_ticket(key='SAT-7', children=children[::-1]), FETCHED_AT)

    # WHEN
    stored = repository.get('jira', 'SAT-7')

    # THEN
    assert stored
    assert stored.ticket.children == children


def test_saving_again_replaces_what_was_stored(session: Session) -> None:
    # GIVEN SAT-7 stored with a parent, a child, a link, a sprint, a comment, an attachment and a change
    repository = TicketRepository(session)
    repository.save(
        new_ticket(
            key='SAT-7',
            status='In progress',
            sprints=(new_sprint(),),
            comments=(new_comment(),),
            attachments=(new_attachment(),),
            parent=new_ticket_summary(key='SAT-2'),
            children=(new_ticket_summary(key='SAT-8'),),
            links=(new_link(from_key='SAT-7', to_key='SAT-9'),),
            linked=(new_ticket_summary(key='SAT-9'),),
            changes=(new_change(),),
        ),
        FETCHED_AT,
    )
    later = datetime(2026, 11, 7, tzinfo=UTC)
    refetched = new_ticket(key='SAT-7', status='Resolved')

    # WHEN
    repository.save(refetched, later)

    # THEN
    assert repository.get('jira', 'SAT-7') == StoredTicket(ticket=refetched, fetched_at=later)


def test_a_mention_updates_a_stored_ticket_but_keeps_the_rest(session: Session) -> None:
    # GIVEN SAT-9 is stored in full, and SAT-7 then mentions it with a new title and status
    repository = TicketRepository(session)
    sat_9 = new_ticket(key='SAT-9', title='Publish layer', status='To do', description='Kept as it was')
    repository.save(sat_9, FETCHED_AT)
    mention = new_ticket_summary(key='SAT-9', title='Publish meteo layer', status='In progress')
    link = new_link(from_key='SAT-7', to_key='SAT-9')
    sat_7 = new_ticket(key='SAT-7', links=(link,), linked=(mention,))

    # WHEN
    repository.save(sat_7, FETCHED_AT)

    # THEN
    stored = repository.get('jira', 'SAT-9')
    assert stored
    assert stored.ticket == replace(
        sat_9,
        title='Publish meteo layer',
        status='In progress',
        links=(link,),
        linked=(new_ticket_summary(key='SAT-7', title=sat_7.title, status=sat_7.status, type=sat_7.type),),
    )


def test_delete_removes_the_ticket_its_links_and_its_childrens_parent(session: Session) -> None:
    # GIVEN SAT-7 stored, with its child SAT-8 and SAT-9, which it blocks, stored too
    repository = TicketRepository(session)
    sat_7 = new_ticket_summary(key='SAT-7')
    repository.save(new_ticket(key='SAT-8', parent=sat_7), FETCHED_AT)
    repository.save(new_ticket(
        key='SAT-9',
        links=(new_link(from_key='SAT-7', to_key='SAT-9'),),
        linked=(sat_7,),
    ), FETCHED_AT)
    repository.save(new_ticket(key='SAT-7'), FETCHED_AT)

    # WHEN
    repository.delete('jira', 'SAT-7')

    # THEN
    sat_8, sat_9 = repository.get('jira', 'SAT-8'), repository.get('jira', 'SAT-9')
    assert sat_8
    assert sat_9
    assert repository.get('jira', 'SAT-7') is None
    assert sat_8.ticket.parent is None
    assert sat_9.ticket.links == ()


def test_saving_a_naive_datetime_raises(session: Session) -> None:
    # GIVEN
    repository = TicketRepository(session)
    naive = new_ticket(created=datetime(2026, 10, 12, 9, 30))

    # WHEN / THEN
    with pytest.raises(StatementError, match='Naive datetime 2026-10-12 09:30:00'):
        repository.save(naive, FETCHED_AT)
