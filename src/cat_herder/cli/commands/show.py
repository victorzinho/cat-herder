import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.cli.ticket_yaml import ticket_to_yaml
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('key', help='the ticket key, such as SAT-7, or jira:SAT-7 to name its source')
    parser.add_argument('--brief', action='store_true', help='leave out comments and attachments')
    parser.add_argument('--changes', action='store_true', help="add the ticket's Changes")
    parser.add_argument('--force-fetch', action='store_true', help="fetch even within the source's window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the ticket, or report that its source doesn't have it.

    Returns:
        The exit code.
    """
    sources = build_ticket_sources(config, environ)
    with database_session(open_database(config.data_dir)) as session:
        service = TicketsService(config, session, sources, current_git_repository(config, cwd))
        ticket = service.show(args.key, force_fetch=args.force_fetch)

    if not ticket:
        print(f'cat-herder: {args.key} is not in its source', file=sys.stderr)
        return 1

    print(ticket_to_yaml(ticket, config, brief=args.brief, changes=args.changes), end='')
    return 0
