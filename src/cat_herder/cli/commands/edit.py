import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.config import check_writable
from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.cli.ticket_yaml import edited_ticket, read_ticket_yaml
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.errors import WriteIncomplete
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('key', help='the ticket key, such as SAT-7, or jira:SAT-7 to name its source')
    parser.add_argument('file', nargs='?', type=Path, help='the ticket YAML; stdin if left out')
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Write the fields in the ticket YAML that differ from the ticket's.

    Returns:
        The exit code: 1 if the source doesn't have the ticket.
    """
    document = read_ticket_yaml(args.file.read_text() if args.file else sys.stdin.read())
    incomplete: WriteIncomplete | None = None
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        check_writable(config, tickets_service.source_of(args.key))

        ticket = tickets_service.show(args.key, force_fetch=True)
        if not ticket:
            print(f'cat-herder: {args.key} is not in its source', file=sys.stderr)
            return 1

        sprint_by_name = {
            name: sprints[0]
            for name in document.get('sprints', [])
            if (sprints := tickets_service.find_sprints(name, ticket.source))
        } | {sprint.name: sprint for sprint in ticket.sprints}
        edited = edited_ticket(document, ticket, config, sprint_by_name)
        try:
            tickets_service.edit(edited)
        except WriteIncomplete as error:
            # Raised once the session commits, which keeps the ticket as the service refreshed it.
            incomplete = error
    if incomplete:
        raise incomplete
    return 0
