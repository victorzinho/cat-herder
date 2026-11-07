import argparse
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.cli.ticket_yaml import tickets_to_yaml
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import CURRENT_SPRINT, TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database

FILTERS = ('project', 'sprint', 'status', 'assignee', 'updated_since')


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--project', action='append', default=[], help='a project slug; repeat for any of several')
    parser.add_argument('--sprint', help=f'a sprint name, or {CURRENT_SPRINT} for the one in progress')
    parser.add_argument('--status', action='append', default=[], help="a status's name; repeat for any of several")
    parser.add_argument('--assignee', help="a person's slug")
    parser.add_argument('--updated-since', type=_datetime, help='an ISO date or datetime, local if it has no zone')
    parser.add_argument('--force-fetch', action='store_true', help="fetch even within the source's window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the tickets matching the filters, after syncing their projects.

    Returns:
        The exit code: 2 without any filter, or for a project or person the config doesn't have, as for other
        usage errors.
    """
    if problem := _usage_problem(args, config):
        print(f'cat-herder list: {problem}', file=sys.stderr)
        return 2
    sources = build_ticket_sources(config, environ)
    with database_session(open_database(config.data_dir)) as session:
        tickets = TicketsService(config, session, sources, current_git_repository(config, cwd)).list_tickets(
            project_slugs=args.project,
            statuses=args.status,
            sprint_name=args.sprint,
            assignee_slug=args.assignee,
            updated_since=args.updated_since,
            force_fetch=args.force_fetch,
        )
    print(tickets_to_yaml(tickets, config), end='')
    return 0


def _usage_problem(args: argparse.Namespace, config: Config) -> str | None:
    if not any(getattr(args, name) for name in FILTERS):
        return 'give at least one filter'
    projects = {project.slug for project in config.projects}
    if unknown := [slug for slug in args.project if slug not in projects]:
        return f'not configured projects: {", ".join(unknown)}'
    if args.assignee and args.assignee not in {person.slug for person in config.people}:
        return f'not a configured person: {args.assignee}'
    return None


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f'{value} is not an ISO date or datetime') from error
    return parsed if parsed.tzinfo else parsed.astimezone()
