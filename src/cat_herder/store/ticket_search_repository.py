import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy
from sqlalchemy import ForeignKey, delete, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from cat_herder.domain.ticket import Ticket
from cat_herder.store.base import Base

type Vector = numpy.ndarray[tuple[int], numpy.dtype[numpy.float32]]

# The FTS5 table of each ticket's words, which SQLAlchemy can't declare: SQL reads and writes it directly.
WORDS_TABLE = 'ticket_words'
# Words in titles count 10 times as much as in descriptions or comments.
_BM25_WEIGHTS = '10.0, 1.0, 1.0, 0.0'
# The most tokens, mostly words, a word match's snippet shows around the words matched.
_SNIPPET_TOKENS = 12
# Words too common to tell tickets apart, which would otherwise make nearly every ticket match.
_WORDS_TOO_COMMON_TO_SEARCH = frozenset(
    'a an and are as at be by for from has have in is it its not of on or should so that the this to was were with'
    .split()
)


class TicketEmbeddingRow(Base):
    """One chunk of a ticket's text, embedded by one model. text_hash is the caller's, the same for every chunk."""

    __tablename__ = 'ticket_embeddings'

    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'), primary_key=True)
    model: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    text_hash: Mapped[str]
    text: Mapped[str]
    vector: Mapped[bytes]


@dataclass(frozen=True, kw_only=True)
class TicketMatch:
    """A ticket matching a query, with the part of its description or comments that matches best, empty if only its
    title matches.
    """

    ticket: Ticket
    snippet: str


@dataclass(frozen=True, kw_only=True)
class Chunk:
    text: str
    vector: Vector


@dataclass(frozen=True, kw_only=True)
class TicketEmbeddings:
    """A ticket's chunks, in order, embedded by one model. text_hash tells which text of the ticket they came from."""

    ticket: Ticket
    text_hash: str
    chunks: tuple[Chunk, ...]


class TicketSearchRepository:
    """The local copy's search indexes of full tickets: their words, matched by query, and their chunks' embeddings.

    Every method takes tickets read from the local copy, as only those have an internal_id. Both indexes go with the
    ticket when it's deleted.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_words(self, tickets: Sequence[Ticket]) -> None:
        """Index the words of those tickets whose text changed since they were last indexed."""
        indexed_hash_by_id: dict[int, str] = {
            ticket_id: text_hash
            for ticket_id, text_hash in self._session.execute(text(f'SELECT rowid, text_hash FROM {WORDS_TABLE}'))
        }
        for ticket in tickets:
            ticket_id = _internal_id(ticket)
            comments = '\n\n'.join(comment.body for comment in ticket.comments)
            text_hash = _hash(ticket.title, ticket.description or '', comments)
            if indexed_hash_by_id.get(ticket_id) == text_hash:
                continue
            self._session.execute(text(f'DELETE FROM {WORDS_TABLE} WHERE rowid = :id'), {'id': ticket_id})
            self._session.execute(
                text(
                    f'INSERT INTO {WORDS_TABLE} (rowid, title, description, comments, text_hash) '
                    'VALUES (:id, :title, :description, :comments, :text_hash)'
                ),
                {
                    'id': ticket_id,
                    'title': ticket.title,
                    'description': ticket.description or '',
                    'comments': comments,
                    'text_hash': text_hash,
                },
            )

    def find_word_matches(self, query: str, tickets: Sequence[Ticket]) -> list[TicketMatch]:
        """Those of the tickets with any of the query's words, as save_words indexed them, best first.

        Words match stemmed, those in titles weigh the most, and those too common to tell tickets apart are ignored.
        """
        words = [word for word in re.findall(r'\w+', query.lower()) if word not in _WORDS_TOO_COMMON_TO_SEARCH]
        if not words:
            return []
        ticket_by_id = {_internal_id(ticket): ticket for ticket in tickets}
        # Each word quoted, so that none reads as an operator.
        expression = ' OR '.join(f'"{word}"' for word in words)
        # Ranked by every column, and the snippet taken from the description or comments only, as the title is shown.
        rows = self._session.execute(
            text(
                f'SELECT ranked.rowid, body.snippet FROM '
                f'(SELECT rowid, bm25({WORDS_TABLE}, {_BM25_WEIGHTS}) AS rank FROM {WORDS_TABLE} '
                f'WHERE {WORDS_TABLE} MATCH :expression) AS ranked '
                f"LEFT JOIN (SELECT rowid, snippet({WORDS_TABLE}, -1, '', '', '…', {_SNIPPET_TOKENS}) AS snippet "
                f'FROM {WORDS_TABLE} WHERE {WORDS_TABLE} MATCH :body_expression) AS body ON body.rowid = ranked.rowid '
                'ORDER BY ranked.rank'
            ),
            {'expression': expression, 'body_expression': f'{{description comments}} : ({expression})'},
        )
        return [
            TicketMatch(ticket=ticket_by_id[ticket_id], snippet=snippet or '')
            for ticket_id, snippet in rows
            if ticket_id in ticket_by_id
        ]

    def find_embeddings(self, model: str, tickets: Sequence[Ticket]) -> list[TicketEmbeddings]:
        """The embeddings that model made of those of the tickets it embedded."""
        ticket_by_id = {_internal_id(ticket): ticket for ticket in tickets}
        rows = self._session.scalars(
            select(TicketEmbeddingRow)
            .where(TicketEmbeddingRow.model == model)
            .order_by(TicketEmbeddingRow.ticket_id, TicketEmbeddingRow.position)
        )
        rows_by_ticket_id: dict[int, list[TicketEmbeddingRow]] = {}
        for row in rows:
            if row.ticket_id in ticket_by_id:
                rows_by_ticket_id.setdefault(row.ticket_id, []).append(row)
        return [
            TicketEmbeddings(
                ticket=ticket_by_id[ticket_id],
                text_hash=ticket_rows[0].text_hash,
                chunks=tuple(
                    Chunk(text=row.text, vector=numpy.frombuffer(row.vector, dtype=numpy.float32))
                    for row in ticket_rows
                ),
            )
            for ticket_id, ticket_rows in rows_by_ticket_id.items()
        ]

    def save_embeddings(self, model: str, embeddings: Sequence[TicketEmbeddings]) -> None:
        """Store the tickets' embeddings by that model, replacing what it had embedded of them."""
        ticket_ids = [_internal_id(each.ticket) for each in embeddings]
        self._session.execute(
            delete(TicketEmbeddingRow).where(
                TicketEmbeddingRow.model == model, TicketEmbeddingRow.ticket_id.in_(ticket_ids)
            )
        )
        self._session.add_all(
            TicketEmbeddingRow(
                ticket_id=ticket_id,
                model=model,
                position=position,
                text_hash=each.text_hash,
                text=chunk.text,
                vector=chunk.vector.tobytes(),
            )
            for ticket_id, each in zip(ticket_ids, embeddings, strict=True)
            for position, chunk in enumerate(each.chunks)
        )
        self._session.flush()

    def delete_embeddings_of_other_models(self, model: str) -> None:
        """Drop the embeddings made by any model but that one."""
        self._session.execute(delete(TicketEmbeddingRow).where(TicketEmbeddingRow.model != model))


def _internal_id(ticket: Ticket) -> int:
    if ticket.internal_id is None:
        raise ValueError(f'{ticket.source}:{ticket.key} was not read from the local copy')
    return ticket.internal_id


def _hash(*texts: str) -> str:
    return hashlib.sha1('\0'.join(texts).encode()).hexdigest()
