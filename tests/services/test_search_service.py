from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from cat_herder.domain.ticket import Ticket
from cat_herder.embeddings.encoder import EncoderUnavailable
from cat_herder.services.search_service import SearchHit, SearchService
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.ticket_search_repository import TicketSearchRepository
from tests.helpers import FakeEncoder, new_comment, new_ticket

SYNONYMS = (('storage', 'disk'), ('failure', 'crash', 'error'))


def test_search_finds_tickets_by_their_words(session: Session):
    # GIVEN
    tickets = _save(
        session,
        new_ticket(key='SAT-1', title='Imports', description='The importer retries every night.'),
        new_ticket(key='SAT-2', title='Website', description='New copy for the home page.'),
    )
    cut = _search_service(session, FakeEncoder())

    # WHEN
    hits = cut.search('retry', tickets, 10)

    # THEN
    assert hits[0] == SearchHit(ticket=tickets[0], snippet='The importer retries every night.')


def test_search_finds_tickets_by_their_meaning(session: Session):
    # GIVEN
    tickets = _save(
        session,
        new_ticket(key='SAT-1', title='Import crash', description='Nightly imports stop halfway.'),
        new_ticket(key='SAT-2', title='Website', description='New copy for the home page.'),
    )
    cut = _search_service(session, FakeEncoder(SYNONYMS))

    # WHEN
    hits = cut.search('error', tickets, 10)

    # THEN
    assert hits[0] == SearchHit(ticket=tickets[0], snippet='Nightly imports stop halfway.')


def test_search_ranks_first_a_ticket_found_by_both_words_and_meaning(session: Session):
    # GIVEN
    tickets = _save(
        session,
        new_ticket(key='SAT-1', title='Storage'),
        new_ticket(key='SAT-2', title='Disk usage report')
    )
    cut = _search_service(session, FakeEncoder(SYNONYMS))

    # WHEN
    hits = cut.search('disk', tickets, 10)

    # THEN
    assert [hit.ticket.key for hit in hits] == ['SAT-2', 'SAT-1']


def test_search_searches_by_words_only_with_a_warning_without_the_encoder(
    session: Session, caplog: pytest.LogCaptureFixture
):
    # GIVEN
    tickets = _save(session, new_ticket(key='SAT-1', title='Disk usage'), new_ticket(key='SAT-2', title='Storage'))
    cut = _search_service(session, None)

    # WHEN
    hits = cut.search('disk', tickets, 10)

    # THEN
    assert hits == [SearchHit(ticket=tickets[0], snippet='')]
    assert caplog.messages == ['searching by words only, as search by meaning is unavailable: no network']


def test_search_takes_word_snippets_from_the_description_or_comments_only(session: Session):
    # GIVEN a long title with the word, and a description with it too, or without it
    title = 'One two three four five six seven eight nine ten eleven twelve thirteen disk'
    tickets = _save(
        session,
        new_ticket(key='SAT-1', title=title, description='Nothing to see here.'),
        new_ticket(key='SAT-2', title=title, description='The disk is full.'),
    )
    cut = _search_service(session, None)

    # WHEN
    hits = cut.search('disk', tickets, 10)

    # THEN
    assert {hit.ticket.key: hit.snippet for hit in hits} == {'SAT-1': '', 'SAT-2': 'The disk is full.'}


def test_search_ignores_words_too_common_to_tell_tickets_apart(session: Session):
    # GIVEN
    tickets = _save(session, new_ticket(key='SAT-1', title='The disk'))
    cut = _search_service(session, None)

    # WHEN
    hits = cut.search('the', tickets, 10)

    # THEN
    assert hits == []


def test_search_finds_only_among_the_tickets_given(session: Session):
    # GIVEN
    sat_1, _ = _save(session, new_ticket(key='SAT-1', title='Disk'), new_ticket(key='SAT-2', title='Disk'))
    cut = _search_service(session, FakeEncoder())

    # WHEN
    hits = cut.search('disk', [sat_1], 10)

    # THEN
    assert [hit.ticket.key for hit in hits] == ['SAT-1']


def test_search_leaves_out_tickets_unrelated_by_words_and_meaning(session: Session):
    # GIVEN
    tickets = _save(
        session,
        new_ticket(key='SAT-1', title='Disk usage'),
        new_ticket(key='SAT-2', title='Storage'),
        new_ticket(key='SAT-3', title='Website', description='New copy for the home page.'),
    )
    cut = _search_service(session, FakeEncoder(SYNONYMS))

    # WHEN
    hits = cut.search('disk', tickets, 10)

    # THEN
    assert {hit.ticket.key for hit in hits} == {'SAT-1', 'SAT-2'}


def test_search_returns_at_most_limit_tickets(session: Session):
    # GIVEN
    tickets = _save(session, *(new_ticket(key=f'SAT-{number}', title='Disk') for number in range(1, 4)))

    # WHEN
    hits = _search_service(session, FakeEncoder()).search('disk', tickets, 2)

    # THEN
    assert len(hits) == 2


def test_search_chunks_each_ticket_under_its_title_in_windows_and_each_comment_apart(session: Session):
    # GIVEN an encoder reading 8 tokens, which leaves 5 for text under a one-word title, and a paragraph of 7
    encoder = FakeEncoder(max_tokens=8)
    tickets = _save(session, new_ticket(
        key='SAT-1',
        title='Plan',
        description='one two three\n\nfour five\n\nsix seven eight nine ten eleven twelve',
        comments=(new_comment(body='A note'),),
    ))
    cut = _search_service(session, encoder)

    # WHEN
    cut.search('plan', tickets, 10)

    # THEN paragraphs packed while they fit, the long one in windows overlapping by a quarter, then the comment
    assert encoder.encoded == [
        'Plan\none two three\n\nfour five',
        'Plan\nsix seven eight nine ten',
        'Plan\nten eleven twelve',
        'Plan\nA note',
        'plan',
    ]


def test_search_cuts_long_snippets(session: Session):
    # GIVEN
    tickets = _save(session, new_ticket(key='SAT-1', title='Crash', description='word ' * 40))
    cut = _search_service(session, FakeEncoder(SYNONYMS))

    # WHEN
    hits = cut.search('error', tickets, 10)

    # THEN 100 characters, the last an ellipsis
    assert hits[0].snippet == f'{"word " * 19}word…'


def test_search_drops_the_embeddings_of_any_other_model(session: Session):
    # GIVEN SAT-1 embedded by an old model
    tickets = _save(session, new_ticket(key='SAT-1', title='Disk'))
    _search_service(session, FakeEncoder(model='old')).search('disk', tickets, 10)
    cut = _search_service(session, FakeEncoder(model='new'))

    # WHEN
    cut.search('disk', tickets, 10)

    # THEN
    repository = TicketSearchRepository(session)
    assert repository.find_embeddings('old', tickets) == []


def _save(session: Session, *tickets: Ticket) -> list[Ticket]:
    repository = TicketRepository(session)
    for ticket in tickets:
        repository.save(ticket, datetime.now(UTC))
    stored = [repository.get(ticket.source, ticket.key) for ticket in tickets]
    return [each.ticket for each in stored if each]


def _search_service(session: Session, encoder: FakeEncoder | None) -> SearchService:
    def load_encoder() -> FakeEncoder:
        if not encoder:
            raise EncoderUnavailable('no network')
        return encoder

    return SearchService(session, load_encoder)
