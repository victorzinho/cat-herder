import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Ticket
from cat_herder.sources.errors import SourceUnreachable, TicketNotFound
from cat_herder.sources.ticket_source import TicketSource
from cat_herder.store.ticket_repository import StoredTicket, TicketRepository

_logger = logging.getLogger(__name__)


class KeyNotResolved(Exception):
    """The key isn't a ticket key, names no ticket source, or is in several sources. The message says which."""


class TicketsService:
    """Reads answer from the local copy, after fetching into it when the source's window has passed.

    If the source can't be reached, reads answer from the local copy and log a warning. Keys resolve from the config,
    with the current git repository's projects breaking ties between sources.
    """

    def __init__(
        self, config: Config, session: Session, sources: Iterable[TicketSource], git_repository: str | None
    ) -> None:
        self._config = config
        self._ticket_repository = TicketRepository(session)
        self._source_by_slug = {source.slug: source for source in sources}
        self._git_repository = git_repository

    def show(self, key: str, force_fetch: bool = False) -> Ticket | None:
        """The ticket, or None if its source doesn't have it, which deletes the local copy.

        force_fetch fetches even within the source's window.

        Raises:
            KeyNotResolved: if the key doesn't resolve to one source.
            SourceUnreachable: if the source can't be reached and the ticket isn't stored.
            SourceError: if the source answers with any other error.
        """
        source, source_key = self._resolve(key)
        return self._read(source, source_key, force_fetch)

    def _resolve(self, key: str) -> tuple[str, str]:
        # Returns the source and its own key.
        source, separator, unqualified = key.rpartition(':')
        if separator:
            if source not in self._config.ticket_sources():
                raise KeyNotResolved(f'{source} is not a ticket source: {", ".join(self._config.ticket_sources())}')
            return source, unqualified

        prefix, dash, number = key.rpartition('-')
        if not dash or not prefix or not number:
            raise KeyNotResolved(f'{key} is not a ticket key, such as SAT-7')
        candidates = self._config.sources_for_key_prefix(prefix)
        if len(candidates) == 1:
            return candidates[0], key

        preferred = {
            project.tickets.source
            for project in self._config.projects
            if project.tickets and project.tickets.space == prefix and self._git_repository in project.repositories
        }
        if len(preferred) == 1:
            return preferred.pop(), key
        options = ', '.join(f'{candidate}:{key}' for candidate in candidates)
        raise KeyNotResolved(f'{key} is in several sources, use one of: {options}')

    def _read(self, source: str, key: str, force_fetch: bool) -> Ticket | None:
        now = datetime.now(UTC)
        window = timedelta(seconds=self._config.source(source).fetch_window_seconds)
        stored = self._ticket_repository.get(source, key)
        if stored and not force_fetch and now - stored.fetched_at < window:
            return stored.ticket

        try:
            ticket = self._source_by_slug[source].fetch_ticket(key)
        except SourceUnreachable:
            return _local_copy(source, key, stored)
        except TicketNotFound:
            self._ticket_repository.delete(source, key)
            return None

        self._ticket_repository.save(ticket, now)
        return ticket

def _local_copy(source: str, key: str, stored: StoredTicket | None) -> Ticket:
    if not stored:
        raise SourceUnreachable(f'{source} unreachable, and {key} has no local copy')
    _logger.warning('%s unreachable, %s is a local copy from %s', source, key, f'{stored.fetched_at:%Y-%m-%d}')
    return stored.ticket
