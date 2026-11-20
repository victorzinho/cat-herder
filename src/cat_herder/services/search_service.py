import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy
from sqlalchemy.orm import Session

from cat_herder.domain.ticket import Ticket
from cat_herder.embeddings.encoder import Encoder, EncoderUnavailable
from cat_herder.store.ticket_search_repository import Chunk, TicketEmbeddings, TicketMatch, TicketSearchRepository

_logger = logging.getLogger(__name__)

# Part of every embedded text's hash: changing it, when chunking changes, embeds every ticket again.
_CHUNKING_VERSION = '1'
# Reciprocal rank fusion's constant, the usual one: rank 1 and rank 2 count almost the same, so neither ranking can
# outweigh the other on its own.
_RRF_K = 60
# The markers the encoder adds around every text, [CLS] and [SEP] for MiniLM, which take tokens from the limit.
_MARKER_TOKENS = 2
# Windows of a paragraph too long for one chunk overlap by a quarter, so a sentence cut at one's edge is whole in the
# next.
_WINDOW_OVERLAP = 4
_SNIPPET_CHARACTERS = 100


@dataclass(frozen=True, kw_only=True)
class SearchHit:
    """A ticket found, with the part of its text that best matches, cut short: the words, or the chunk closest in
    meaning. Empty if only the title matches.
    """

    ticket: Ticket
    snippet: str


class SearchService:
    """Ranks the tickets related to a query by their words or by their meaning, fusing both rankings.

    Each search first indexes the tickets that changed since they were last indexed. Searching by meaning needs the
    encoder: if it can't be loaded, results come from words alone, with a warning.
    """

    def __init__(self, session: Session, load_encoder: Callable[[], Encoder]) -> None:
        self._repository = TicketSearchRepository(session)
        self._load_encoder = load_encoder

    def search(self, query: str, tickets: Sequence[Ticket], limit: int) -> list[SearchHit]:
        """Those of the full tickets matching the query by any of its words or related to it in meaning, best first,
        at most limit.
        """
        self._repository.save_words(tickets)
        rankings = [self._repository.find_word_matches(query, tickets), self._find_meaning_matches(query, tickets)]
        return [SearchHit(ticket=match.ticket, snippet=_short(match.snippet)) for match in _fuse(rankings)[:limit]]

    def _find_meaning_matches(self, query: str, tickets: Sequence[Ticket]) -> list[TicketMatch]:
        # The tickets related in meaning to the query, closest first, each with the text of its chunk closest to it.
        # Empty without an encoder.
        try:
            encoder = self._load_encoder()
        except EncoderUnavailable as error:
            _logger.warning('searching by words only, as search by meaning is unavailable: %s', error)
            return []
        embeddings = self._embeddings(encoder, tickets)
        if not embeddings:
            return []
        vectors = numpy.stack([chunk.vector for each in embeddings for chunk in each.chunks])
        scores = vectors @ encoder.encode([query])[0]
        matches: list[TicketMatch] = []
        best_scores: list[float] = []
        start = 0
        for each in embeddings:
            ticket_scores = scores[start:start + len(each.chunks)]
            best = int(numpy.argmax(ticket_scores))
            start += len(each.chunks)
            if ticket_scores[best] <= encoder.min_similarity:
                continue
            matches.append(TicketMatch(ticket=each.ticket, snippet=each.chunks[best].text))
            best_scores.append(float(ticket_scores[best]))
        return [matches[index] for index in sorted(range(len(matches)), key=lambda index: -best_scores[index])]

    def _embeddings(self, encoder: Encoder, tickets: Sequence[Ticket]) -> list[TicketEmbeddings]:
        # The tickets' embeddings, embedding first those whose text changed since they were last embedded.
        self._repository.delete_embeddings_of_other_models(encoder.model)
        current_by_source_and_key = {
            (each.ticket.source, each.ticket.key): each
            for each in self._repository.find_embeddings(encoder.model, tickets)
            if each.text_hash == _text_hash(each.ticket)
        }
        changed = [ticket for ticket in tickets if (ticket.source, ticket.key) not in current_by_source_and_key]
        embedded = _embed(encoder, changed)
        self._repository.save_embeddings(encoder.model, embedded)
        return [*current_by_source_and_key.values(), *embedded]


def _embed(encoder: Encoder, tickets: Sequence[Ticket]) -> list[TicketEmbeddings]:
    # Each chunk is embedded under its ticket's title, the strongest hint at what the ticket is about.
    chunks_of_tickets = [_chunks(ticket, encoder) for ticket in tickets]
    texts = [
        f'{ticket.title}\n{chunk}'
        for ticket, chunks in zip(tickets, chunks_of_tickets, strict=True)
        for chunk in chunks
    ]
    if not texts:
        return []
    vectors = iter(encoder.encode(texts))
    return [
        TicketEmbeddings(
            ticket=ticket,
            text_hash=_text_hash(ticket),
            chunks=tuple(Chunk(text=chunk, vector=next(vectors)) for chunk in chunks),
        )
        for ticket, chunks in zip(tickets, chunks_of_tickets, strict=True)
    ]


def _text_hash(ticket: Ticket) -> str:
    texts = [_CHUNKING_VERSION, ticket.title, ticket.description or '', *(comment.body for comment in ticket.comments)]
    return hashlib.sha1('\0'.join(texts).encode()).hexdigest()


def _chunks(ticket: Ticket, encoder: Encoder) -> list[str]:
    # The texts of the ticket's chunks, which fit under its title in what the encoder reads: the description's
    # paragraphs packed, then each comment's. One empty text for a ticket with neither.
    # A title too long to leave room for text is cut by the encoder, so its chunks still get half the room.
    budget = max(
        encoder.max_tokens - _MARKER_TOKENS - len(encoder.token_spans(f'{ticket.title}\n')), encoder.max_tokens // 2
    )
    chunks = _packed(_paragraphs(ticket.description or ''), budget, encoder)
    for comment in ticket.comments:
        chunks += _packed(_paragraphs(comment.body), budget, encoder)
    return chunks or ['']


def _paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r'\n\s*\n', text) if paragraph.strip()]


def _packed(paragraphs: Sequence[str], budget: int, encoder: Encoder) -> list[str]:
    # Consecutive paragraphs joined while they fit in the budget, a paragraph longer than it in windows.
    packed: list[str] = []
    current = ''
    for paragraph in paragraphs:
        for part in _windows(paragraph, budget, encoder):
            joined = f'{current}\n\n{part}' if current else part
            if current and len(encoder.token_spans(joined)) > budget:
                packed.append(current)
                current = part
            else:
                current = joined
    if current:
        packed.append(current)
    return packed


def _windows(paragraph: str, budget: int, encoder: Encoder) -> list[str]:
    # The paragraph whole if it fits, or in overlapping windows of budget tokens covering all of it.
    spans = encoder.token_spans(paragraph)
    if len(spans) <= budget:
        return [paragraph]
    step = budget - budget // _WINDOW_OVERLAP
    starts = range(0, len(spans) - budget + step, step)
    return [paragraph[spans[start][0]:spans[min(start + budget, len(spans)) - 1][1]] for start in starts]


def _fuse(rankings: Sequence[Sequence[TicketMatch]]) -> list[TicketMatch]:
    # Reciprocal rank fusion: each ranking adds 1 / (_RRF_K + rank) to the tickets in it, by rank alone, as the
    # rankings' own scores aren't comparable. Ties keep the order the tickets were first seen in. Each ticket keeps
    # the first match with a snippet, in the rankings' order.
    score_by_source_and_key: dict[tuple[str, str], float] = {}
    match_by_source_and_key: dict[tuple[str, str], TicketMatch] = {}
    for ranking in rankings:
        for rank, match in enumerate(ranking, start=1):
            source_and_key = (match.ticket.source, match.ticket.key)
            score = score_by_source_and_key.get(source_and_key, 0.0)
            score_by_source_and_key[source_and_key] = score + 1 / (_RRF_K + rank)
            kept = match_by_source_and_key.get(source_and_key)
            if not kept or not kept.snippet:
                match_by_source_and_key[source_and_key] = match
    return sorted(
        match_by_source_and_key.values(),
        key=lambda match: -score_by_source_and_key[match.ticket.source, match.ticket.key],
    )


def _short(text: str) -> str:
    flat = ' '.join(text.split())
    return flat if len(flat) <= _SNIPPET_CHARACTERS else f'{flat[:_SNIPPET_CHARACTERS - 1].rstrip()}…'
