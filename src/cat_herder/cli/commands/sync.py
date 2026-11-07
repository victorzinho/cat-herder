import argparse
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.services.time_entries_service import TimeEntriesService
from cat_herder.sources.factory import build_ticket_sources, build_time_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--force-fetch', action='store_true', help="re-read everything, even within the window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Sync the configured spaces into the local copy, tickets first so that time entries are validated against them.

    Returns:
        The exit code.
    """
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        time_entries_service = TimeEntriesService(config, session, build_time_sources(config, environ))
        tickets_service.sync(args.force_fetch)
        time_entries_service.sync(args.force_fetch)
    print('Sync done.')
    return 0
