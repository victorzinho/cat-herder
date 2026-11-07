import argparse
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--force-fetch', action='store_true', help="re-read everything, even within the window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Sync the configured spaces into the local copy.

    Returns:
        The exit code.
    """
    sources = build_ticket_sources(config, environ)
    with database_session(open_database(config.data_dir)) as session:
        TicketsService(config, session, sources, current_git_repository(config, cwd)).sync(args.force_fetch)
    return 0
