import logging
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, TicketOrigin
from cat_herder.domain.ticket import Sprint, SprintState, Ticket, key_order
from cat_herder.sources.errors import SourceError, SourceUnreachable, TicketNotFound
from cat_herder.sources.ticket_source import TicketSource
from cat_herder.store.sprint_repository import SprintRepository
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.ticket_space_sync_repository import TicketSpaceSyncRepository

_logger = logging.getLogger(__name__)

# A sprint name that stands for whichever sprint is in progress.
CURRENT_SPRINT = 'current'


class KeyNotResolved(Exception):
    """The key isn't a ticket key, names a source that isn't a ticket one, or is in several. The message says which."""


class TicketsService:
    """Reads answer from the local copy, after fetching into it when the source's window has passed.

    If the source can't be reached or answers with an error, reads answer from the local copy and log a warning. Keys
    resolve from the config, with the current git repository's projects breaking ties between sources.

    Writes need the source to be reachable, and store the ticket as the source has it after.
    """

    def __init__(
        self, config: Config, session: Session, sources: Iterable[TicketSource], git_repository: str | None
    ) -> None:
        self._config = config
        self._ticket_repository = TicketRepository(session)
        self._sprint_repository = SprintRepository(session)
        self._ticket_space_sync_repository = TicketSpaceSyncRepository(session)
        self._source_by_slug = {source.slug: source for source in sources}
        self._git_repository = git_repository

    def show(self, key: str, force_fetch: bool = False) -> Ticket | None:
        """The ticket, or None if its source doesn't have it, which deletes the local copy.

        A qualified key, as in jira:SAT-7, names a ticket source. force_fetch fetches even within the source's window.

        Raises:
            KeyNotResolved: if the key doesn't resolve to one source.
            SourceUnreachable: if the source can't be reached and the ticket isn't stored.
            SourceError: if the source answers with any other error and the ticket isn't stored.
        """
        source, source_key = self._resolve(key)
        return self._read(source, source_key, force_fetch)

    def sync(self, force_fetch: bool = False, project_slugs: Sequence[str] = ()) -> None:
        """Fetch the projects' spaces into the local copy.

        A space is read whole the first time, and then for what changed since.
        One synced within its source's window is skipped.
        If a source can't be reached or answers with an error, its spaces log a warning.

        Args:
            force_fetch: re-read every space whole, deleting the local copy of tickets gone from it.
            project_slugs: the projects whose spaces to fetch. Empty fetches every project's.
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

    def find_sprints(self, name: str, source: str | None = None) -> list[Sprint]:
        """The stored sprints with that name, ordered by source.

        Args:
            name: the sprint's name.
            source: the slug of the only source to look in. None looks in every source.
        """
        return self._sprint_repository.find(name, source)

    def find_sprints_by_id(self, sprint_id: str, source: str | None = None) -> list[Sprint]:
        """The stored sprints with that ID, ordered by source.

        Args:
            sprint_id: the sprint's ID in its source.
            source: the slug of the only source to look in. None looks in every source.
        """
        return self._sprint_repository.find_by_id(sprint_id, source)

    def sprint_names(self, source: str) -> dict[str, str]:
        """The names of the source's stored sprints, by ID."""
        return self._sprint_repository.names_by_id(source)

    def source_of(self, key: str) -> str:
        """The slug of the ticket source the key resolves to.

        Raises:
            KeyNotResolved: if the key doesn't resolve to one source.
        """
        return self._resolve(key)[0]

    def create(self, ticket: Ticket) -> str:
        """Create the ticket in its source, as TicketSource.create_ticket does, and return its key.

        The new ticket is then stored as the source has it, as far as the source can be reached.

        Raises:
            SourceUnreachable: if the source can't be reached before creating it.
            WriteIncomplete: if the source fails once it's created.
            SourceError: if the source doesn't take a value, or answers with any other error.
        """
        key = self._source_by_slug[ticket.source].create_ticket(ticket)
        with suppress(SourceError, SourceUnreachable):
            self._fetch(ticket.source, key)
        return key

    def edit(self, edited: Ticket) -> None:
        """Write the edited ticket to its source, which writes only what differs from what it has.

        The local copy is then refreshed, as far as the source can be reached, whether the write worked or not.

        Raises:
            SourceUnreachable: if the source can't be reached.
            TicketNotFound: if the source doesn't have the ticket.
            WriteIncomplete: if the source fails after writing part of the edit.
            SourceError: if the source doesn't take a value, or answers with any other error.
        """
        try:
            self._source_by_slug[edited.source].update_ticket(edited)
        finally:
            # best-effort refresh in any case, update_ticket might have written partially
            with suppress(SourceError, SourceUnreachable):
                self._fetch(edited.source, edited.key)

    def comment(self, key: str, body: str) -> None:
        """Add a comment, in markdown, to the ticket.

        The ticket is then stored as the source has it, as far as the source can be reached.

        Raises:
            KeyNotResolved: if the key doesn't resolve to one source.
            SourceUnreachable: if the source can't be reached.
            TicketNotFound: if the source doesn't have the ticket.
            SourceError: if the source answers with any other error.
        """
        source, source_key = self._resolve(key)
        self._source_by_slug[source].add_comment(source_key, body)
        with suppress(SourceError, SourceUnreachable):
            self._fetch(source, source_key)

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
        # returns the source and its own key
        source, separator, unqualified = key.rpartition(':')
        if separator:
            if source not in self._config.ticket_sources():
                raise KeyNotResolved(f'{source} is not a configured ticket source')
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
            return self._fetch(source, key)
        except TicketNotFound:
            return None
        except SourceUnreachable:
            if not stored:
                raise SourceUnreachable(f'{source} unreachable, and {key} has no local copy') from None
            _warn_local_copy(source, 'unreachable', key, stored.fetched_at)
            return stored.ticket
        except SourceError as error:
            if not stored:
                raise
            _warn_local_copy(source, 'failed', key, stored.fetched_at, error)
            return stored.ticket

    def _fetch(self, source: str, key: str) -> Ticket:
        try:
            ticket = self._source_by_slug[source].fetch_ticket(key)
        except TicketNotFound:
            self._ticket_repository.delete(source, key)
            raise
        self._ticket_repository.save(ticket, datetime.now(UTC))
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
            _warn_local_copy(source, 'unreachable', space, synced_at)
            return
        except SourceError as error:
            _warn_local_copy(source, 'failed', space, synced_at, error)
            return

        if not updated_since:
            # A full read finds every ticket in the space, so the stored ones it doesn't find are gone.
            for key in self._ticket_repository.keys_in_space(source, space) - {ticket.key for ticket in tickets}:
                self._ticket_repository.delete(source, key)
        for ticket in tickets:
            self._ticket_repository.save(ticket, now)
        self._ticket_space_sync_repository.save(source, space, now)


def _warn_local_copy(
    source: str, problem: str, read: str, copied_at: datetime | None, error: SourceError | None = None
) -> None:
    # read is the ticket or space read, and copied_at when its local copy is from, None if it has none.
    if copied_at:
        local_copy = f'is a local copy from {copied_at.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}'
    else:
        local_copy = 'was never synced'
    detail = f': {error}' if error else ''
    _logger.warning('%s %s, %s %s%s', source, problem, read, local_copy, detail)

