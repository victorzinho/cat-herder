import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, TicketOrigin
from cat_herder.domain.ticket import SprintState, Ticket, key_order
from cat_herder.sources.errors import SourceUnreachable, TicketNotFound
from cat_herder.sources.ticket_source import TicketSource
from cat_herder.store.ticket_repository import StoredTicket, TicketRepository
from cat_herder.store.ticket_space_sync_repository import TicketSpaceSyncRepository

_logger = logging.getLogger(__name__)

# A sprint name that stands for whichever sprint is in progress.
CURRENT_SPRINT = 'current'


class KeyNotResolved(Exception):
    """The key isn't a ticket key, or is in several sources. The message says which."""


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
        self._ticket_space_sync_repository = TicketSpaceSyncRepository(session)
        self._source_by_slug = {source.slug: source for source in sources}
        self._git_repository = git_repository

    def show(self, key: str, force_fetch: bool = False) -> Ticket | None:
        """The ticket, or None if its source doesn't have it, which deletes the local copy.

        A qualified key, as in jira:SAT-7, names a ticket source. force_fetch fetches even within the source's window.

        Raises:
            KeyNotResolved: if the key doesn't resolve to one source.
            SourceUnreachable: if the source can't be reached and the ticket isn't stored.
            SourceError: if the source answers with any other error.
        """
        source, source_key = self._resolve(key)
        return self._read(source, source_key, force_fetch)

    def sync(self, force_fetch: bool = False, project_slugs: Sequence[str] = ()) -> None:
        """Fetch the spaces of those projects, or of every project, into the local copy.

        A space is read whole the first time, and then for what changed since. One synced within its source's window
        is skipped. force_fetch re-reads everything, which deletes the
        local copy of tickets gone from the space. If a source can't be reached, its spaces log a warning.
        """
        for origin in self._origins(project_slugs):
            self._sync_space(origin, force_fetch)

    def list_tickets(
        self,
        project_slugs: Sequence[str] = (),
        statuses: Sequence[str] = (),
        sprint_name: str | None = None,
        assignee_slug: str | None = None,
        updated_since: datetime | None = None,
        force_fetch: bool = False,
    ) -> list[Ticket]:
        """The full tickets matching every filter given, sorted by key, after syncing their projects' spaces."""
        origins = self._origins(project_slugs)
        for origin in origins:
            self._sync_space(origin, force_fetch)
        current = sprint_name == CURRENT_SPRINT
        tickets = self._ticket_repository.find(
            origins,
            statuses=statuses,
            sprint_name=None if current else sprint_name,
            sprint_state=SprintState.IN_PROGRESS if current else None,
            assignee_by_source=self._assignee_by_source(assignee_slug) if assignee_slug else None,
            updated_since=updated_since,
        )
        return sorted(tickets, key=lambda ticket: key_order(ticket.key))

    def _assignee_by_source(self, person_slug: str) -> dict[str, str]:
        person = self._config.person(person_slug)
        return {source: str(identity) for source, identity in person.identity_by_source.items()}

    def _origins(self, project_slugs: Sequence[str]) -> list[TicketOrigin]:
        # The ticket origins of those projects, or of every project, each once.
        origins = {
            project.tickets
            for project in self._config.projects
            if project.tickets and (not project_slugs or project.slug in project_slugs)
        }
        return sorted(origins, key=lambda origin: (origin.source, origin.space))

    def _resolve(self, key: str) -> tuple[str, str]:
        # Returns the source and its own key.
        source, separator, unqualified = key.rpartition(':')
        if separator:
            return source, unqualified

        prefix, dash, number = key.rpartition('-')
        if not dash or not prefix or not number:
            raise KeyNotResolved(f'{key} is not a ticket key, such as SAT-7')
        candidates = self._config.ticket_sources_for_key_prefix(prefix)
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

    def _sync_space(self, origin: TicketOrigin, force_fetch: bool) -> None:
        source, space = origin.source, origin.space
        now = datetime.now(UTC)
        window = timedelta(seconds=self._config.source(source).fetch_window_seconds)
        synced_at = self._ticket_space_sync_repository.get_last_sync(source, space)
        if synced_at and not force_fetch and now - synced_at < window:
            return

        updated_since = None if force_fetch else synced_at
        try:
            tickets = self._source_by_slug[source].fetch_tickets(space, updated_since)
        except SourceUnreachable:
            local_copy = f'is a local copy from {synced_at:%Y-%m-%d}' if synced_at else 'was never synced'
            _logger.warning('%s unreachable, %s %s', source, space, local_copy)
            return

        if not updated_since:
            # A full read finds every ticket in the space, so the stored ones it doesn't find are gone.
            for key in self._ticket_repository.keys_in_space(source, space) - {ticket.key for ticket in tickets}:
                self._ticket_repository.delete(source, key)
        for ticket in tickets:
            self._ticket_repository.save(ticket, now)
        self._ticket_space_sync_repository.save(source, space, now)


def _local_copy(source: str, key: str, stored: StoredTicket | None) -> Ticket:
    if not stored:
        raise SourceUnreachable(f'{source} unreachable, and {key} has no local copy')
    _logger.warning('%s unreachable, %s is a local copy from %s', source, key, f'{stored.fetched_at:%Y-%m-%d}')
    return stored.ticket

