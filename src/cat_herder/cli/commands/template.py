import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.ticket_yaml import create_template, edit_template
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database
from cat_herder.store.git_repositories import current_git_repository


def configure(parser: argparse.ArgumentParser) -> None:
    key_or_project = parser.add_mutually_exclusive_group(required=True)
    key_or_project.add_argument(
        'key', nargs='?', help='the ticket key, such as SAT-7, or jira:SAT-7 to name its source, for an edit template'
    )
    key_or_project.add_argument('--project', help="a project's slug, for a create template")
    parser.add_argument('--type', dest='type_name', help='with --project, the ticket type whose values to list')
    parser.add_argument('--force-fetch', action='store_true', help="with a key, fetch even within the source's window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the create template for the project, or the edit template for the ticket.

    Returns:
        The exit code: 1 if the source doesn't have the ticket; 2 for --type with a key, --force-fetch with
        --project, or a project the config doesn't have or that has no ticket source, as for other usage errors.
    """
    if problem := _usage_problem(args, config):
        print(f'cat-herder template: {problem}', file=sys.stderr)
        return 2
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        if origin := args.project and config.project(args.project).tickets:
            config.check_writable(origin.source)
            allowed_values = tickets_service.creatable_values(origin, args.type_name)
            ticket_yaml = create_template(args.project, args.type_name, allowed_values)
        else:
            config.check_writable(tickets_service.source_of(args.key))
            ticket = tickets_service.show(args.key, force_fetch=args.force_fetch)
            if not ticket:
                print(f'cat-herder: {args.key} is not in its source', file=sys.stderr)
                return 1
            ticket_yaml = edit_template(ticket, config, tickets_service.editable_values(ticket))
    print(ticket_yaml, end='')
    return 0


def _usage_problem(args: argparse.Namespace, config: Config) -> str | None:
    if args.key and args.type_name:
        return '--type is only for --project'
    if args.project and args.force_fetch:
        return '--force-fetch is only for a key'
    if args.project and args.project not in {project.slug for project in config.projects}:
        return f'not a configured project: {args.project}'
    if args.project and not config.project(args.project).tickets:
        return f'{args.project} has no ticket source'
    return None
