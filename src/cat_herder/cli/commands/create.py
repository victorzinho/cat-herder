import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.ticket_yaml import new_ticket, read_ticket_yaml, ticket_origin
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database
from cat_herder.store.git_repositories import current_git_repository


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('file', nargs='?', type=Path, help='the ticket YAML; stdin if left out')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help=(
            'check everything create checks before creating, without creating: '
            'not the status or the linked keys, which are checked once created'
        ),
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Create the ticket in the ticket YAML, and print its key, or with --dry-run, only check it can be.

    Returns:
        The exit code.
    """
    document = read_ticket_yaml(args.file.read_text() if args.file else sys.stdin.read())
    origin = ticket_origin(document, config)
    config.check_writable(origin.source)
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        sprint_by_name = {
            name: sprints[0]
            for name in document.get('sprints', [])
            if (sprints := tickets_service.find_sprints(name, origin.source))
        }
        ticket = new_ticket(document, origin, config, sprint_by_name)
        if args.dry_run:
            tickets_service.check_create(ticket)
            print(f'Dry run: create would work in {document["project"]}')
            return 0
        key = tickets_service.create(ticket)
    print(key)
    return 0
