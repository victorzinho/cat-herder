import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.cli.ticket_yaml import ticket_to_yaml
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.services.time_entries_service import TimeEntriesService
from cat_herder.sources.factory import build_ticket_sources, build_time_sources
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
        The exit code: 2 for a key qualified with a source that isn't a configured ticket source, as for other usage
        errors.
    """
    source, separator, _ = args.key.rpartition(':')
    if separator and source not in config.ticket_sources():
        print(f'cat-herder show: not a configured ticket source: {source}', file=sys.stderr)
        return 2
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        time_entries_service = TimeEntriesService(config, session, build_time_sources(config, environ))
        ticket = tickets_service.show(args.key, force_fetch=args.force_fetch)
        spent_hours = time_entries_service.spent_hours(ticket) if ticket else None
        sprint_names = tickets_service.sprint_names(ticket.source) if ticket and args.changes else {}

    if not ticket:
        print(f'cat-herder: {args.key} is not in its source', file=sys.stderr)
        return 1

    output = ticket_to_yaml(
        ticket, config, spent_hours, brief=args.brief, changes=args.changes, sprint_names=sprint_names
    )
    print(output, end='')
    return 0
