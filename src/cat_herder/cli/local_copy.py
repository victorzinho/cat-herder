from collections.abc import Mapping, Sequence

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.services.time_entries_service import TimeEntriesService
from cat_herder.sources.factory import build_ticket_sources, build_time_sources


def sync_local_copy(
    config: Config,
    session: Session,
    environ: Mapping[str, str],
    force_fetch: bool,
    project_slugs: Sequence[str] = (),
) -> None:
    """Sync the tickets and then the time sources of the projects.

    Tickets go first, so that time entries are validated against them.

    Args:
        config: the projects and sources to sync.
        session: the local copy's.
        environ: where the sources' credentials are read from.
        force_fetch: re-read everything, even within the sources' windows.
        project_slugs: the projects to sync. Empty syncs every project.
    """
    TicketsService(config, session, build_ticket_sources(config, environ), None).sync(force_fetch, project_slugs)
    TimeEntriesService(config, session, build_time_sources(config, environ)).sync(force_fetch, project_slugs)
