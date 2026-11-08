import argparse
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.config import check_writable
from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('key', help='the ticket key, such as SAT-7, or jira:SAT-7 to name its source')
    parser.add_argument('text', help='the comment, in markdown')
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Add the comment to the ticket.

    Returns:
        The exit code.
    """
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        check_writable(config, tickets_service.source_of(args.key))
        tickets_service.comment(args.key, args.text)
    return 0
