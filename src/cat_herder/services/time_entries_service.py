import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, TimeOrigin
from cat_herder.domain.ticket import Ticket
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.sources.errors import SourceError, SourceUnreachable
from cat_herder.sources.time_source import TimeSource
from cat_herder.store.sprint_repository import SprintRepository
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.ticket_space_sync_repository import TicketSpaceSyncRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from cat_herder.store.time_source_sync_repository import TimeSourceSync, TimeSourceSyncRepository

_logger = logging.getLogger(__name__)

# Days a sync after the window re-reads, picking up entries deleted or edited since.
REFRESH_DAYS = 30
SECONDS_PER_HOUR = 3600


class TimeEntriesService:
    """Reads answer from the local copy, after syncing into it when the source's window has passed.

    A time source is synced whole, all its configured spaces at once: the first time from its history_from until today,
    then the last REFRESH_DAYS. A change in its configured spaces syncs it from history_from again. If the source can't
    be reached or answers with an error, reads answer from the local copy and log a warning, and the next sync starts
    over.
    """

    def __init__(self, config: Config, session: Session, sources: Iterable[TimeSource]) -> None:
        self._config = config
        self._time_entry_repository = TimeEntryRepository(session)
        self._ticket_repository = TicketRepository(session)
        self._sprint_repository = SprintRepository(session)
        self._time_source_sync_repository = TimeSourceSyncRepository(session)
        self._ticket_space_sync_repository = TicketSpaceSyncRepository(session)
        self._source_by_slug = {source.slug: source for source in sources}

    def sync(self, force_fetch: bool = False) -> None:
        """Sync every time source. force_fetch re-reads from history_from, picking up edits older than REFRESH_DAYS."""
        for origin in self._origins(()):
            self._sync_source(origin, force_fetch)

    def spent_hours(self, ticket: Ticket) -> float | None:
        """Hours of the entries on the ticket, after syncing its project's time source.

        None if the project has no time source, or it was never synced.
        """
        project = self._config.project_of_ticket(ticket)
        if not project or not project.time:
            return None
        [origin] = self._origins([project.time.source])
        self._sync_source(origin, force_fetch=False)
        if not self._time_source_sync_repository.get_last_sync(origin):
            return None
        entries = self._time_entry_repository.find(project.time, ticket_key=ticket.key)
        return sum((entry.end - entry.start).total_seconds() for entry in entries) / SECONDS_PER_HOUR

    def _origins(self, source_slugs: Sequence[str]) -> list[TimeOrigin]:
        # The time origins of every project, merged into one per source, of those sources or of every source.
        spaces_by_source: defaultdict[str, list[str]] = defaultdict(list)
        for project in self._config.projects:
            if project.time and (not source_slugs or project.time.source in source_slugs):
                spaces_by_source[project.time.source].extend(project.time.spaces)
        return [TimeOrigin(source=source, spaces=tuple(spaces)) for source, spaces in sorted(spaces_by_source.items())]

    def _sync_source(self, origin: TimeOrigin, force_fetch: bool) -> None:
        config = self._config.time_source(origin.source)
        now = datetime.now(UTC)

        last_sync = self._time_source_sync_repository.get_last_sync(origin)
        if last_sync and not force_fetch and now - last_sync.synced_at < timedelta(seconds=config.fetch_window_seconds):
            return

        start = config.history_from if (force_fetch or not last_sync) else last_sync.resume_from
        try:
            self._walk(self._source_by_slug[origin.source], origin, start, now)
        except SourceUnreachable:
            self._warn_local_copy(origin, 'unreachable')
        except SourceError as error:
            self._warn_local_copy(origin, 'failed', error)

    def _walk(self, source: TimeSource, origin: TimeOrigin, start: date, now: datetime) -> None:
        until = date.today() + timedelta(days=1)
        while start < until:
            end = min(start + timedelta(days=source.max_fetch_days), until)
            start_at, end_at = _local_midnight(start), _local_midnight(end)
            entries = source.fetch_time_entries(origin.spaces, start_at, end_at)
            self._time_entry_repository.replace(origin, start_at, end_at, [self._validated(entry) for entry in entries])
            start = end

        sync = TimeSourceSync(resume_from=date.today() - timedelta(days=REFRESH_DAYS), synced_at=now)
        self._time_source_sync_repository.save(origin, sync)

    def _validated(self, entry: TimeEntry) -> TimeEntry:
        # Drops a ticket outside the entry's project, a ticket missing from a synced space and a missing sprint, with a
        # flag saying so.
        project = self._config.project_of_time_entry(entry)
        assert project
        ticket_key, sprint, flags = entry.ticket_key, entry.sprint, set(entry.flags)
        if ticket_key:
            tickets = project.tickets
            if not tickets or ticket_key.rpartition('-')[0] != tickets.space:
                flags.add(TimeEntryFlag.TICKET_IN_OTHER_PROJECT)
                ticket_key = None
            elif self._ticket_space_sync_repository.get_last_sync(
                tickets.source, tickets.space
            ) and not self._ticket_repository.exists(tickets.source, ticket_key):
                flags.add(TimeEntryFlag.TICKET_NOT_FOUND)
                ticket_key = None
        if sprint and not self._sprint_repository.exists(sprint):
            flags.add(TimeEntryFlag.SPRINT_NOT_FOUND)
            sprint = None
        return replace(entry, ticket_key=ticket_key, sprint=sprint, flags=frozenset(flags))

    def _warn_local_copy(self, origin: TimeOrigin, problem: str, error: SourceError | None = None) -> None:
        sync = self._time_source_sync_repository.get_last_sync(origin)
        local_copy = f'are a local copy from {sync.synced_at:%Y-%m-%d}' if sync else 'were never synced'
        detail = f': {error}' if error else ''
        _logger.warning('%s %s, its time entries %s%s', origin.source, problem, local_copy, detail)


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time()).astimezone()
